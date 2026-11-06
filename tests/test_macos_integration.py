"""Provider integration across authenticated discovery, cached and queued calls."""

from types import SimpleNamespace

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401 -- shared authenticated HTTP fixture

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_query import ReadQuery, read_query_async


def native_facts(bridge):
    bridge.macos.capability_probe.facts["platform"] = "darwin"
    bridge.macos.capability_probe.facts["os_version"] = "15.7.4"
    bridge.macos.capability_probe.executable = lambda path: True


async def test_explicit_helper_diagnostics_share_status_routes_without_grants(
    http_bridge,  # noqa: F811 -- shared HTTP fixture
    monkeypatch,
):
    bridge, endpoint = http_bridge
    native_facts(bridge)
    calls = []
    diagnostic = {
        "diagnostic_only": True,
        "authorizes_future_helpers": False,
        "identity": {"pid": 123, "executable": "/usr/bin/osascript"},
    }

    async def observe():
        calls.append("explicit")
        return diagnostic

    monkeypatch.setattr(
        "kirabridge.platform_adapters.macos.helper_permissions.inspect_helper_permissions",
        observe,
    )
    monkeypatch.setattr(
        bridge.macos.permission_probe,
        "reader",
        lambda resource: {"state": "unknown", "method": "isolated_test"},
    )
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        await clients.list_tools("local")
        await clients.call("local", "bridge_health", {})
        ordinary = (await clients.call("local", "macos_status", {})).structuredContent
        assert not calls
        assert "helper_diagnostics" not in ordinary
        before = bridge.macos.snapshot()["revision"]
        direct = (
            await clients.call("local", "macos_status", {"check_helpers": True})
        ).structuredContent
        cached = (
            await clients.call(
                "local",
                "read_query",
                {"query": {"operation": "platform.status", "check_helpers": True}},
            )
        ).structuredContent
        value = request("platform.status", {"check_helpers": True}, task_id="helper-status")
        token = bridge.security.grant("local", value)
        bridge.submit("local", value, token)
        task = await bridge.tasks.wait("local", value.task_id, 10)
        assert task["state"] == "completed", task
        queued = task["result"]
        assert calls == ["explicit"] * 3
        assert direct["helper_diagnostics"] == cached["helper_diagnostics"] == diagnostic
        assert queued["helper_diagnostics"] == diagnostic
        assert bridge.macos.snapshot()["revision"] == before
        assert bridge.macos.actor_identities == {}
        assert all(row["actor"] == "core" for row in bridge.macos.permission_probe.snapshot())
        bridge.config.principals["local"].capabilities.remove("bridge.health")
        denied = (
            await clients.call("local", "macos_status", {"check_helpers": True})
        ).structuredContent
        assert denied["error"]["code"] == "forbidden"
        assert len(calls) == 3


def test_helper_diagnostic_selector_is_strict_and_status_only():
    from pydantic import ValidationError

    from kirabridge.platform_adapters.macos.status import PlatformStatusInput

    with pytest.raises(ValidationError):
        ReadQuery(operation="session.catalog", check_helpers=True)
    with pytest.raises(ValidationError):
        PlatformStatusInput(check_helpers="true")
    with pytest.raises(ValidationError):
        PlatformStatusInput(check_helpers=True, target="arbitrary.application")


async def test_http_status_and_catalog_share_provider_revision_without_ui(
    http_bridge,  # noqa: F811 -- shared HTTP fixture
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    config.principals["local"].capabilities.append("session.inspect")
    native_facts(bridge)
    # This fixture models an absent native app, regardless of the operator's
    # actual desktop. Permission denial and transport presence are distinct.
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": False,
        "reason": "native_app_protocol_unavailable",
    }
    probes = []

    def permission(resource):
        probes.append(resource)
        return {"state": "unknown", "raw_granted": False, "method": "test_no_prompt"}

    bridge.macos.permission_probe.reader = permission

    async def empty_catalog(principal, *, transport=None):
        return {"status": "available", "sessions": []}

    monkeypatch.setattr(bridge.sessions, "catalog", empty_catalog)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        tools = await clients.list_tools("local")
        assert {"macos_status", "session_enter"} <= {tool.name for tool in tools}
        assert not probes, "tools/list must not perform permission checks"
        status = (await clients.call("local", "macos_status", {})).structuredContent
        resources = ["accessibility", "screen_capture", "post_events", "input_monitoring"]
        assert probes == resources
        assert {row["resource"] for row in status["permissions"]} == set(resources)
        assert status["permissions"][0]["actor"] == "core"
        assert status["capabilities"]["capture"]["available"] is False
        rows = {row["operation"]: row for row in status["operations"]}
        assert rows["file.read"]["approval_required"] is True
        assert rows["file.read"]["eligible_for_submission"] is True
        assert rows["file.read"]["os_permission_state"] == "requires_native_target_check"
        catalogue = (await clients.call("local", "operation_catalog", {})).structuredContent
        assert "platform.status" in catalogue["operations"]
        assert catalogue["discovery"]["platform"]["revision"] == status["revision"]
        assert probes == resources
        config.principals["local"].capabilities.remove("bridge.health")
        denied = (await clients.call("local", "macos_status", {})).structuredContent
        assert denied["error"]["code"] == "forbidden"
        assert probes == resources


async def test_matching_native_denial_blocks_transport_before_any_worker(bridge, monkeypatch):
    native_facts(bridge)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.sys", SimpleNamespace(platform="darwin")
    )
    identity = {"pid": 123, "start": "bound-test-helper"}
    bridge.macos.actor_identities["/usr/bin/osascript"] = identity
    bridge.macos.permission_probe.record(
        "accessibility",
        actor="/usr/bin/osascript",
        observation={"state": "denied"},
        identity=identity,
    )

    async def forbidden_probe():
        pytest.fail("Denied native permission must stop before desktop/worker access")

    monkeypatch.setattr(
        bridge.sessions.terminal_app.desktop, "require_interactive", forbidden_probe
    )
    with pytest.raises(BridgeError, match="Matching native permission"):
        await bridge.sessions.terminal_app.native("MUST_NOT_RUN", mutation=True)


async def test_cached_file_read_and_queued_file_read_share_technical_guard(bridge, config):
    native_facts(bridge)
    bridge.macos.capability_probe.facts["os_version"] = "unknown"
    path = config.principals["local"].roots[0] + "/unread.txt"
    from pathlib import Path

    Path(path).write_text("guarded fixture")
    with pytest.raises(BridgeError) as direct:
        await read_query_async(bridge, "local", ReadQuery(operation="file.read", path=path))
    assert direct.value.code == "macos_capability_unavailable"
    value = request("file.read", {"path": path})
    async with bridge:
        token = bridge.security.grant("local", value)
        bridge.submit("local", value, token)
        result = await bridge.tasks.wait("local", value.task_id, 5)
    assert result["state"] == "failed"
    assert result["error"]["code"] == direct.value.code


async def test_explicit_enter_tool_uses_existing_task_model_and_approval(
    http_bridge,  # noqa: F811 -- shared HTTP fixture
):
    bridge, endpoint = http_bridge
    bridge.config.principals["local"].capabilities.append("session.inspect")
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        result = (
            await clients.call(
                "local",
                "session_enter",
                {
                    "task_id": "return-explicit",
                    "idempotency_key": "return-explicit",
                    "pane_id": "terminal:123:ttys004",
                    "expected_pid": 345,
                    "expected_cursor": "a" * 64,
                    "expected_agent_pid": 678,
                },
            )
        ).structuredContent
        assert result["error"]["code"] == "approval_required", result
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM tasks WHERE id='return-explicit'"
            ).fetchone()[0]
            == 0
        )
        # A separate empty literal call fails before persistence or dispatch.
        invalid = (
            await clients.call(
                "local",
                "action_request",
                {
                    "request": {
                        "task_id": "empty-invalid",
                        "idempotency_key": "empty-invalid",
                        "operation": "session.input",
                        "arguments": {
                            "pane_id": "terminal:123:ttys004",
                            "expected_pid": 345,
                            "text": "",
                        },
                    }
                },
            )
        ).structuredContent
        assert invalid["error"]["code"] == "invalid_arguments"
        assert "session_enter" in invalid["error"]["message"]
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM tasks WHERE id='empty-invalid'"
            ).fetchone()[0]
            == 0
        )


def test_visible_route_uses_authenticated_principal_and_leaves_tmux_alone(bridge, config):
    native_facts(bridge)
    config.principals["local"].client_type = "chatgpt"
    assert bridge.platform_operation("terminal.execute", {}, "local") == "terminal.visible"
    assert bridge.platform_operation("terminal.execute", {"background": True}, "local") is None
    assert bridge.platform_operation("session.input", {"pane_id": "%1"}, "local") is None
    assert bridge.platform_operation("session.catalog", {}, "local") is None


async def test_native_unavailability_keeps_mixed_tmux_tools_and_status_visible(
    http_bridge,  # noqa: F811 -- shared HTTP fixture
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    native_facts(bridge)
    config.principals["local"].capabilities.append("session.inspect")
    bridge.macos.capability_probe.executable = lambda path: False

    async def catalog(principal, *, transport=None):
        return {"status": "available", "sessions": [{"pane_id": "%1", "transport": "tmux"}]}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        names = {tool.name for tool in await clients.list_tools("local")}
        assert {"session_catalog", "session_read", "clipboard_info", "macos_status"} <= names
        assert "session_enter" not in names
        rows = (await clients.call("local", "operation_catalog", {})).structuredContent
        assert {
            "session.catalog",
            "session.read",
            "session.input",
            "session.focus",
            "session.close",
        } <= set(rows["operations"])
        assert not rows["operations"]["session.input"]["platform"]["eligible_for_submission"]
