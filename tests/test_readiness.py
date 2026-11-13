import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import request
from pydantic import ValidationError

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.readiness import ReadinessInput, readiness, runtime_snapshot


async def test_project_read_roots_do_not_expand_writes_terminal_or_other_identity(bridge, tmp_path):
    project = tmp_path / "Projects" / "help" / ".worktrees" / "review" / "docs"
    project.mkdir(parents=True)
    file = project / "handoff.md"
    file.write_text("owned handoff")
    bridge.config.principals["local"].read_roots = [str(tmp_path / "Projects" / "help")]
    bridge.config.principals["local"].approval_mode = "automatic"
    bridge.config.principals["other"].approval_mode = "automatic"

    async def run(op, args, key, principal="local"):
        value = request(op, args, task_id=key)
        bridge.prepare(principal, value)
        return await bridge.tasks.wait(principal, key)

    async with bridge:
        result = await run("file.read", {"path": str(file)}, "read")
        assert result["result"]["text"] == "owned handoff"
        assert (await run("file.list", {"path": str(project)}, "list"))["state"] == "completed"
        denied = await run("file.read", {"path": str(file)}, "other", "other")
        assert denied["error"]["code"] == "path_denied" and denied["started"] is None
        write = await run(
            "file.write", {"path": str(file), "text": "bad", "overwrite": True}, "write"
        )
        assert write["error"]["code"] == "path_denied" and file.read_text() == "owned handoff"
        executable = bridge.config.principals["local"].executables[0]
        cwd = await run(
            "terminal.execute", {"argv": [executable, "-V"], "cwd": str(project)}, "cwd"
        )
        assert cwd["error"]["code"] == "path_denied" and cwd["started"] is None


async def test_readiness_reports_specific_denials_without_contents_or_execution(bridge, tmp_path):
    policy = bridge.config.principals["local"]
    root = Path(policy.roots[0])
    file = root / "readable.md"
    file.write_text("PRIVATE_CONTENT_MUST_NOT_APPEAR")
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE")
    (root / "escape").symlink_to(outside)
    policy.executables = ["/missing/allowed-program"]
    async with bridge:
        before = bridge.store.db.total_changes  # The dispatcher has recorded its actual load.
        result = readiness(
            bridge,
            "local",
            ReadinessInput(
                read_paths=[
                    str(file),
                    str(outside),
                    str(root / "escape"),
                    str(root / "missing"),
                    str(bridge.config.state_path / "bridge.sqlite3"),
                ],
                executables=["/bin/cat", "/usr/bin/python3", "/missing/allowed-program"],
            ),
        )
        assert result["dispatcher_active"]
        assert result["requested_prerequisites_ready"] is False
        assert [x["code"] for x in result["read_path_checks"]] == [
            "available",
            "path_denied",
            "path_unavailable",
            "path_missing",
            "path_denied",
        ]
        assert [x["code"] for x in result["executable_checks"]] == [
            "executable_denied",
            "executable_denied",
            "executable_unavailable",
        ]
        assert "PRIVATE_CONTENT" not in json.dumps(result)
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert not bridge.terminal.sessions
        assert readiness(bridge, "local", ReadinessInput())["requested_prerequisites_ready"] is None
        good = readiness(bridge, "local", ReadinessInput(read_paths=[str(file)]))
        assert good["requested_prerequisites_ready"] is True
        assert bridge.store.db.total_changes == before


async def test_readiness_preserves_file_capabilities_and_principal_boundary(bridge, tmp_path):
    policy = bridge.config.principals["local"]
    policy.capabilities = ["bridge.health"]
    target = Path(policy.roots[0]) / "file"
    target.write_text("not allowed")
    result = readiness(bridge, "local", ReadinessInput(read_paths=[str(target)]))
    assert result["read_path_checks"][0]["code"] == "forbidden"
    assert all(not x["ok"] for x in result["root_checks"])
    with pytest.raises(BridgeError, match="Capability not granted"):
        readiness(bridge, "unknown", ReadinessInput())
    with pytest.raises(ValidationError):
        ReadinessInput(read_paths=[str(target)] * 17)


def test_config_origin_snapshot_does_not_change_after_file_edit(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('concurrency=1\n[principals.chatgpt]\nread_roots=["/project"]\n')
    config = load_config(str(path))
    snapshot = runtime_snapshot(config)
    assert snapshot["config_path"] == str(path)
    path.write_text(path.read_text().replace("concurrency=1", "concurrency=2"))
    assert runtime_snapshot(config)["config_sha256"] == snapshot["config_sha256"]
    assert runtime_snapshot(load_config(str(path)))["config_sha256"] != snapshot["config_sha256"]
    assert "read_roots" in config.principals["chatgpt"].model_dump()


async def test_owned_stop_readiness_separates_abort_from_optional_durable_barrier(bridge):
    bridge.config.principals["local"].approval_mode = "automatic"
    async with bridge:
        value = readiness(bridge, "local", ReadinessInput(operations=["workflow.stop"]))
        assert value["requested_prerequisites_ready"] is True
        operation = value["operation_checks"][0]
        assert operation["owned_abort_available"] is True
        assert operation["barrier_confirmed"] is False
        assert operation["durable_barrier_prerequisites"] == {
            "ok": False,
            "code": "workflow_control_unavailable",
        }
        bridge.config.principals["local"].capabilities.remove("process.terminate")
        denied = readiness(bridge, "local", ReadinessInput(operations=["workflow.stop"]))
        assert denied["requested_prerequisites_ready"] is False
        assert denied["operation_checks"][0]["code"] == "forbidden"
        assert "owned_abort_available" not in denied["operation_checks"][0]
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_opencode_http_preflight_does_not_require_an_executable(bridge):
    from kirabridge.bridge_core.config import AgentConfig
    from kirabridge.readiness import task_preflight

    bridge.config.agents["http"] = AgentConfig(
        kind="opencode_http",
        model="deepseek/deepseek-flash",
        server_url="http://127.0.0.1:58836",
    )
    bridge.config.principals["local"].agents.append("http")
    task = {
        "id": "http-preflight",
        "principal": "local",
        "operation": "agent.execute",
        "args": {
            "agent": "http",
            "prompt": "hello",
            "cwd": bridge.config.principals["local"].roots[0],
            "timeout": 5,
        },
    }
    result = task_preflight(bridge, task)
    agent_check = next(item for item in result["checks"] if item["kind"] == "agent")
    assert agent_check["ok"] is True
    assert result["ready"] is True


def test_readiness_reports_pending_approval_without_changing_tasks_or_policy(bridge):
    policy = bridge.config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.approval_mode = "automatic"
    queued = request("file.read", {"path": str(Path(policy.roots[0]) / "queued")}, task_id="queued")
    bridge.prepare("local", queued)
    policy.approval_mode = "manual"
    original = policy.model_dump()
    before = bridge.store.db.total_changes
    value = readiness(bridge, "local", ReadinessInput(operations=["file.read", "session.catalog"]))
    for item in value["operation_checks"]:
        assert item["authorized"] and not item["automatic"] and item["approval_required"]
        assert item["ok"] is False and item["code"] == "approval_required"
    assert value["requested_prerequisites_ready"] is False
    assert bridge.store.get("queued")["state"] == "queued"
    assert bridge.store.db.total_changes == before
    assert policy.model_dump() == original


def test_readiness_checks_secondary_capabilities_before_calling_an_operation(bridge):
    policy = bridge.config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.approval_mode = "automatic"
    policy.capabilities.remove("session.input")
    value = readiness(bridge, "local", ReadinessInput(operations=["terminal.visible"]))
    item = value["operation_checks"][0]
    assert item["authorized"] is False and item["code"] == "forbidden"
    assert item["missing_capabilities"] == ["session.input"]
    assert value["requested_prerequisites_ready"] is False


def test_readiness_reports_native_platform_blocker_from_passive_metadata(bridge, monkeypatch):
    bridge.config.principals["local"].approval_mode = "automatic"
    bridge.config.principals["local"].capabilities.append("session.inspect")
    monkeypatch.setattr(
        type(bridge.sessions.terminal_app), "available", property(lambda self: False)
    )
    bridge.sessions.catalog = AsyncMock(side_effect=AssertionError("No terminal probe allowed"))
    value = readiness(bridge, "local", ReadinessInput(operations=["terminal.visible"]))
    item = value["operation_checks"][0]
    assert item["authorized"] and item["automatic"]
    assert item["ok"] is False and item["code"] == "unsupported_platform"
    bridge.sessions.catalog.assert_not_called()


async def test_readiness_leaves_unprobed_transports_unknown_without_database_or_peer_io(
    bridge, monkeypatch
):
    policy = bridge.config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.approval_mode = "automatic"
    monkeypatch.setattr(
        type(bridge.sessions.terminal_app), "available", property(lambda self: True)
    )
    bridge.sessions.catalog = AsyncMock(side_effect=AssertionError("No terminal probe allowed"))
    bridge.threaddesk.connect = AsyncMock(side_effect=AssertionError("No peer connection allowed"))
    bridge.threaddesk.check_configuration = lambda: None
    async with bridge:
        statements = []
        bridge.store.db.set_trace_callback(statements.append)
        try:
            value = readiness(
                bridge,
                "local",
                ReadinessInput(
                    operations=[
                        "terminal.visible",
                        "session.catalog",
                        "threaddesk.read",
                        "threaddesk.manage",
                    ]
                ),
            )
        finally:
            bridge.store.db.set_trace_callback(None)
        assert statements == []
        assert value["dispatcher_active"]
        assert value["requested_prerequisites_ready"] is None
        assert "diagnostic" not in value
        for item in value["operation_checks"]:
            assert item["ok"] is None and item["code"] == "transport_not_probed"
            assert item["authorized"] and item["automatic"] and not item["approval_required"]
        assert (
            readiness(bridge, "local", ReadinessInput(operations=["file.read"]))[
                "requested_prerequisites_ready"
            ]
            is True
        )
        bridge.sessions.catalog.assert_not_called()
        bridge.threaddesk.connect.assert_not_called()
        audited = readiness(
            bridge,
            "local",
            ReadinessInput(
                operations=["session.catalog"],
                workflow_id="explicit-audit",
            ),
        )
        assert audited["audit_recorded"] is True
        record = bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='diagnostic.workflow.preflight' "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert json.loads(record["metadata"])["outcome"] == "unknown"


def test_readiness_separates_empty_executable_allowlist_from_operation_permission(bridge):
    policy = bridge.config.principals["local"]
    executable = policy.executables[0]
    policy.executables = []
    policy.allow_any_executable = False
    policy.approval_mode = "automatic"
    value = readiness(
        bridge,
        "local",
        ReadinessInput(
            executables=[executable],
            operations=["terminal.execute"],
        ),
    )
    assert value["operation_checks"][0]["authorized"] is True
    assert value["operation_checks"][0]["code"] == "executable_denied"
    assert value["executable_checks"][0]["code"] == "executable_denied"
    assert value["requested_prerequisites_ready"] is False


@pytest.mark.parametrize("operation", ["terminal.execute", "admin.execute"])
@pytest.mark.parametrize("client_type", ["chatgpt", "agent"])
@pytest.mark.parametrize("native_available", [False, True])
async def test_readiness_aliases_follow_visible_route_without_blocking_internal_execution(
    bridge, monkeypatch, operation, client_type, native_available
):
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    policy.client_type = client_type
    policy.capabilities.append("session.inspect")
    monkeypatch.setattr(
        type(bridge.sessions.terminal_app), "available", property(lambda self: native_available)
    )
    bridge.sessions.catalog = AsyncMock(side_effect=AssertionError("No terminal probe allowed"))
    bridge.terminal.execute = AsyncMock(side_effect=AssertionError("No execution allowed"))
    async with bridge:
        value = readiness(bridge, "local", ReadinessInput(operations=[operation]))
        item = value["operation_checks"][0]
        assert item["authorized"] and item["automatic"]
        if client_type == "agent":
            assert item["ok"] is True and item["code"] == "available"
            assert value["requested_prerequisites_ready"] is True
        elif native_available:
            assert item["ok"] is None and item["code"] == "transport_not_probed"
            assert value["requested_prerequisites_ready"] is None
        else:
            assert item["ok"] is False and item["code"] == "unsupported_platform"
            assert value["requested_prerequisites_ready"] is False
        bridge.sessions.catalog.assert_not_called()
        bridge.terminal.execute.assert_not_called()
