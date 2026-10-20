import json

import httpx
import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.control_center import configure_access
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.operator_application import operator_application
from kirabridge.permissions import decision, permission_summary
from kirabridge.terminal_access import terminal_access


@pytest.mark.parametrize("level", ["full", "medium", "ask"])
@pytest.mark.parametrize("exception", [False, True])
@pytest.mark.parametrize("capability", [False, True])
@pytest.mark.parametrize("buffer", [False, True])
def test_effective_decision_matches_queue_and_terminal_display(
    bridge, config, level, exception, capability, buffer
):
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = level
    policy.automatic_operations = ["session.input"] if exception else []
    if not capability:
        policy.capabilities.remove("terminal.execute")
    config.session_input_policy.enabled = buffer
    config.session_input_policy.principals = ["local"]
    task = request("session.input", {"pane_id": "%1", "expected_pid": 1, "text": "hello"})
    effective = decision(config, "local", task.operation, text="hello")
    displayed = terminal_access(config, "local")
    assert displayed["input_decision"] == effective
    assert effective["config_revision"] == bridge.runtime["effective_config_sha256"]
    assert effective["authorized"] is capability
    if not capability:
        assert effective["reason"] == "missing_capability"
        with pytest.raises(BridgeError) as error:
            bridge.prepare("local", task)
        assert error.value.code == "forbidden"
        assert not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()
        return
    automatic = exception or (level == "full" and not buffer)
    assert effective["automatic"] is automatic
    queued = bridge.prepare("local", task)
    assert queued["state"] == ("queued" if automatic else "created")
    audit = bridge.store.db.execute(
        "SELECT metadata FROM audit WHERE kind IN ('task.requested','task.queued')"
    ).fetchone()
    assert json.loads(audit[0])["permission_decision"] == effective


def test_terminal_marker_does_not_replace_missing_capability_or_normal_approval(config):
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "ask"
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    effective = decision(config, "local", "session.input", text="hello go-go-go")
    assert effective["buffer_enabled"] and not effective["buffer_required"]
    assert effective["approval_required"]
    policy.capabilities.remove("session.inspect")
    policy.automatic_operations = ["session.input"]
    assert not decision(config, "local", "session.input", text="hello go-go-go")["authorized"]


def test_explicit_revocation_survives_full_selection_and_updates(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[principals.chatgpt]\npermission_level="full"\ncapabilities=["terminal.execute"]\n'
        'automatic_operations=["session.input"]\n'
        '[principals.grok_app]\npermission_level="full"\ncapabilities=["terminal.execute"]\n'
        'automatic_operations=["session.input"]\n'
    )
    configure_access(path, level="ask")
    config = load_config(str(path))
    assert "dauerhafte Ausnahme" in permission_summary(config, "chatgpt")["label"]
    assert decision(config, "chatgpt", "session.input")["automatic"]
    configure_access(path, revoke_operations={"chatgpt": ["session.input"]})
    for level in [None, "full", "medium", "ask", None]:
        configure_access(path, level=level)
        config = load_config(str(path))
        assert config.principals["chatgpt"].automatic_operations == []
        assert config.principals["grok_app"].automatic_operations == ["session.input"]
    assert decision(config, "chatgpt", "session.input")["approval_required"]
    assert not permission_summary(config, "chatgpt")["exceptions"]


@pytest.mark.parametrize(
    "invalid", [{"absent": ["session.input"]}, {"chatgpt": ["*"]}, ["chatgpt"]]
)
def test_invalid_revocation_preserves_config(tmp_path, invalid):
    path = tmp_path / "config.toml"
    path.write_text('[principals.chatgpt]\npermission_level="full"\n')
    original = path.read_bytes()
    with pytest.raises(BridgeError):
        configure_access(path, revoke_operations=invalid)
    assert path.read_bytes() == original


def test_revision_tracks_effective_config_without_reloading_another_file(config):
    before = decision(config, "local", "file.read")
    config.principals["local"].permission_level = "full"
    after = decision(config, "local", "file.read")
    assert before["permission_revision"] != after["permission_revision"]
    assert after["automatic"]


async def test_real_catalog_and_task_use_same_buffer_decision(http_bridge, config):  # noqa: F811
    bridge, endpoint = http_bridge
    config.principals["local"].capabilities += ["session.inspect"]
    config.principals["local"].permission_level = "full"
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    async with MCPClientPool() as clients:
        await clients.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        result = (await clients.call("caller", "operation_catalog", {})).structuredContent
        shown = result["operations"]["session.input"]
        assert shown["approval_required"]
        assert shown["permission_decision"] == result["terminal_access"]["input_decision"]
        task = request("session.input", {"pane_id": "%1", "expected_pid": 1, "text": "hello"})
        queued = (
            await clients.call("caller", "task_request", {"request": task.model_dump()})
        ).structuredContent
        assert queued["state"] == "created"
        assert bridge.store.claim("not-a-transport", 30) is None


async def test_revocation_requires_authenticated_local_route(bridge, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        '[principals.chatgpt]\npermission_level="ask"\nautomatic_operations=["session.input"]\n'
    )
    bridge.config._source_path = str(path)
    key = "local-operator-" + "k" * 48
    app = ApprovalConsole(operator_application(bridge), key)

    async def activated(*, text=None, expected_config_sha=None):
        # Activation supervision is tested separately; this test owns the
        # authenticated route and the real candidate/revocation transformation.
        assert expected_config_sha == load_config(str(path))._source_sha256
        from kirabridge.grok_connector.runtime import replace_private

        replace_private(path, text)
        return {"dispatcher_active": True, "runtime": {}}

    monkeypatch.setattr(app.control_center.service.operations, "activate", activated)
    payload = {"revoke_operations": {"chatgpt": ["session.input"]}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        denied = await client.post("/api/control/permissions", json=payload)
        assert denied.status_code == 401
        assert load_config(str(path)).principals["chatgpt"].automatic_operations
        result = await client.post(
            "/api/control/permissions",
            json=payload,
            headers={"Authorization": "Bearer " + signed_token(key, "session"), "Origin": ORIGIN},
        )
        assert result.status_code == 200, result.text
        reloaded = load_config(str(path))
        assert reloaded.principals["chatgpt"].automatic_operations == []
        assert reloaded.principals["chatgpt"].permission_level == "ask"
