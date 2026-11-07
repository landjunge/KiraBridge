"""Schema compilation is reusable; every instance and schema change is validated."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import SchemaError, ValidationError
from mcp.types import CallToolResult
from test_mcp import http_bridge  # noqa: F401

import kirabridge
from kirabridge.mcp_gateway.client import MCPClientPool, ObservedClientSession, Peer
from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache


def test_cached_schema_revalidates_every_instance_and_in_place_edits():
    cache = SchemaValidatorCache()
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}
    cache.validate({"count": 1}, schema)
    cache.validate({"count": 2}, schema)
    with pytest.raises(ValidationError):
        cache.validate({"count": "wrong"}, schema)
    assert cache.schema_checks == 1
    schema["properties"]["count"]["type"] = "string"
    cache.validate({"count": "fresh"}, schema)
    with pytest.raises(ValidationError):
        cache.validate({"count": 1}, schema)
    assert cache.schema_checks == 2


def test_content_bound_cache_is_bounded_and_does_not_modify_peer_schema():
    cache = SchemaValidatorCache(max_entries=2, max_bytes=40)
    for schema, instance in [
        ({"type": "integer"}, 1),
        ({"type": "string"}, "x"),
        ({"type": "boolean"}, True),
    ]:
        original = dict(schema)
        cache.validate(instance, schema)
        assert schema == original
    assert len(cache.validators) == 2 and cache.canonical_bytes <= 40
    assert '{"type":"integer"}' not in cache.validators


def test_local_references_work_and_external_references_never_fetch(monkeypatch):
    cache = SchemaValidatorCache()
    schema = {
        "$defs": {"count": {"type": "integer"}},
        "properties": {"count": {"$ref": "#/$defs/count"}},
    }
    cache.validate({"count": 1}, schema)
    with pytest.raises(ValidationError):
        cache.validate({"count": "bad"}, schema)

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("External schema retrieval is forbidden")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_fetch)
    with pytest.raises(Exception, match="Unresolvable"):
        cache.validate({}, {"$ref": "https://invalid.example/never-fetch"})


@pytest.mark.parametrize(
    "schema", [{"type": "invalid"}, {"default": float("nan")}, {"title": "\ud800"}]
)
def test_invalid_schemas_are_not_cached(schema):
    cache = SchemaValidatorCache()
    with pytest.raises(SchemaError):
        cache.validate({}, schema)
    assert not cache.validators


async def test_sdk_result_validation_preserves_schema_refresh_and_missing_content_errors():
    session = ObservedClientSession(SimpleNamespace(), SimpleNamespace(), notice=lambda *_: None)
    schema = {"type": "object", "required": ["fresh"]}

    async def listing():
        session._tool_output_schemas["known"] = schema

    session.list_tools = AsyncMock(side_effect=listing)
    good = CallToolResult(content=[], structuredContent={"fresh": True})
    await session._validate_tool_result("known", good)
    await session._validate_tool_result("known", good)
    session.list_tools.assert_awaited_once()
    assert session.output_validators.schema_checks == 1
    schema["required"] = ["changed"]
    with pytest.raises(RuntimeError, match="Invalid structured content"):
        await session._validate_tool_result("known", good)
    with pytest.raises(RuntimeError, match="did not return structured"):
        await session._validate_tool_result("known", CallToolResult(content=[]))
    assert session.output_validators.schema_checks == 2


async def test_inherited_sdk_error_response_bypasses_output_schema_validation():
    session = ObservedClientSession(SimpleNamespace(), SimpleNamespace(), notice=lambda *_: None)
    result = CallToolResult(content=[], isError=True)
    session.send_request = AsyncMock(return_value=result)
    session._validate_tool_result = AsyncMock(side_effect=AssertionError("error has no schema"))
    assert await session.call_tool("known", {}) is result
    session._validate_tool_result.assert_not_awaited()


async def test_real_sdk_reuses_only_output_schemas_and_explicit_lists_are_fresh(
    http_bridge,  # noqa: F811
):
    bridge, endpoint = http_bridge
    async with MCPClientPool() as pool:
        await pool.connect(Peer("test", url=endpoint, token="local-test-" + "a" * 40))
        for _ in range(3):
            result = await pool.call("test", "clipboard_info", {})
            assert result.structuredContent["content_read"] is False
        session = pool.sessions["test"]
        assert session.output_validators.schema_checks == 1
        before = await pool.list_tools("test")
        bridge.config.principals["local"].capabilities.remove("file.write")
        after = await pool.list_tools("test")
        assert before[0].meta["kirabridge"]["revision"] != after[0].meta["kirabridge"]["revision"]
        assert await pool.call("test", "clipboard_info", {})
        assert session.output_validators.schema_checks == 1


async def test_real_stdio_proxy_rejects_invalid_input_before_daemon_dispatch(
    http_bridge,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"local": "local-test-" + "a" * 40}))
    credentials.chmod(0o600)
    config = tmp_path / "proxy.toml"
    config.write_text(
        "data_dir=" + json.dumps(str(tmp_path / "proxy-state")) + "\n"
        "port=" + endpoint.split(":")[-1].split("/")[0] + "\n"
        "credentials_file=" + json.dumps(str(credentials)) + "\n"
        '[principals.local]\ntoken_env="PROXY_SCHEMA_TEST_TOKEN"\n'
    )
    calls, original = [], bridge.task

    def task(principal, task_id):
        calls.append(task_id)
        return original(principal, task_id)

    monkeypatch.setattr(bridge, "task", task)
    async with MCPClientPool() as pool:
        await pool.connect(
            Peer(
                "proxy",
                command=sys.executable,
                args=("-m", "kirabridge.cli", "--config", str(config), "connect"),
                env={"PYTHONPATH": str(Path(kirabridge.__file__).resolve().parent.parent)},
            )
        )
        for arguments in ({}, {"task_id": []}):
            invalid = await pool.call("proxy", "task_get", arguments)
            assert invalid.isError and "Input validation error" in invalid.content[0].text
            assert not calls
        valid = await pool.call("proxy", "task_get", {"task_id": "absent"})
        assert valid.structuredContent["error"]["code"] == "not_found"
        assert calls == ["absent"]
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
