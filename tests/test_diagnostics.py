import asyncio
import json

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.diagnostics import AuditObserver, export_audit, task_report
from kirabridge.mcp_gateway.client import MCPClientPool, ObservedClientSession, Peer
from kirabridge.readiness import ReadinessInput, readiness


async def test_workflow_requirements_fail_before_any_task_and_minimize_audit(bridge, tmp_path):
    secret_path = str(tmp_path / "SENSITIVE_OUTSIDE_PROJECT")
    async with bridge:
        result = readiness(
            bridge,
            "local",
            ReadinessInput(
                workflow_id="workflow-1",
                read_paths=[secret_path],
                executables=["/bin/cat"],
                operations=["file.read", "nonexistent.operation"],
            ),
        )
        assert result["requested_prerequisites_ready"] is False
        assert result["diagnostic"]["accepted"] is False
        assert result["diagnostic"]["started"] is False
        assert result["diagnostic"]["workflow_id"] == "workflow-1"
        assert result["operation_checks"][1]["code"] == "unknown_operation"
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        audit = [dict(r) for r in bridge.store.db.execute("SELECT * FROM audit")]
        assert secret_path not in json.dumps(audit)
        assert "workflow-1" in json.dumps(audit) and verify(bridge.store)["valid"]


@pytest.mark.parametrize(
    "operation,args,code",
    [
        ("file.read", {"path": "/outside-private-project"}, "path_denied"),
        (
            "terminal.execute",
            {"argv": ["/bin/cat", "NEVER_LOG_ARGUMENT"], "cwd": "/bad"},
            "executable_denied",
        ),
    ],
)
async def test_task_preflight_preserves_accept_start_distinction_and_returns_report(
    bridge, operation, args, code
):
    bridge.config.principals["local"].approval_mode = "automatic"
    value = request(operation, args)
    async with bridge:
        bridge.prepare("local", value)
        result = await bridge.tasks.wait("local", value.task_id)
        assert result["state"] == "failed" and result["accepted"] is not None
        assert result["started"] is None
        report = bridge.task("local", value.task_id)["diagnostic"]
        assert report["error_code"] == code
        assert report["execution_runtime"]["instance_id"] == bridge.runtime["instance_id"]
        assert report["accepted"] and not report["started"] and not report["completed"]
        assert not report["automatic_retry"]
        assert "unknown" in report["external_tunnel_lifecycle"]
        assert args not in [report.get("args")]
        assert "NEVER_LOG_ARGUMENT" not in json.dumps(report)
        assert "/outside-private-project" not in json.dumps(report)
        with pytest.raises(BridgeError):
            task_report(bridge, "other", value.task_id)
        assert (
            sum(e["state"] == "accepted" for e in bridge.events("local", value.task_id)["events"])
            == 1
        )


def test_historical_report_and_submission_rejection_do_not_invent_execution_runtime(bridge):
    value = request(arguments={"path": "/wrong"})
    token = bridge.security.grant("local", value)
    bridge.submit("local", value, token)
    bridge.store.claim("synthetic-owner", 30)
    bridge.store.transition(
        value.task_id, "failed", {"safe_to_retry": True}, error={"code": "path_denied"}
    )
    report = task_report(bridge, "local", value.task_id)
    assert report["execution_runtime"] == "unknown; no execution-runtime record"
    assert report["reader_runtime"]["instance_id"] == bridge.runtime["instance_id"]
    with pytest.raises(BridgeError) as failure:
        bridge.prepare("local", request("not.supported", task_id="rejected"))
    assert failure.value.diagnostic["state"] == "not_submitted"
    assert not failure.value.diagnostic["accepted"]
    assert set(value.model_dump()) == {
        "api_version",
        "task_id",
        "operation",
        "arguments",
        "idempotency_key",
        "parent_id",
    }


async def test_runtime_load_links_config_change_without_raw_paths(tmp_path):
    path = tmp_path / "SENSITIVE_CONFIG_LOCATION.toml"
    path.write_text("data_dir=" + json.dumps(str(tmp_path / "state")) + "\nconcurrency=1\n")
    async with Bridge(load_config(str(path))) as first:
        original = first.runtime["instance_id"]
    path.write_text(path.read_text().replace("concurrency=1", "concurrency=2"))
    async with Bridge(load_config(str(path))) as second:
        rows = second.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='diagnostic.runtime.loaded' ORDER BY seq"
        ).fetchall()
        last = json.loads(rows[-1][0])
        assert last["config_changed"] is True
        assert last["previous_runtime"]["instance_id"] == original
        assert "SENSITIVE_CONFIG_LOCATION" not in json.dumps(last)
        assert verify(second.store)["valid"]


def test_audit_budget_and_bounded_rotation_preserve_existing_chain(bridge, tmp_path):
    bridge.config.diagnostics.max_events_per_day = 10
    bridge.config.diagnostics.max_records = 10
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    for _ in range(15):
        observer("connection", {"phase": "connect.started", "prompt": "DO_NOT_LOG"})
    assert observer.status()["recording"] == "budget_exhausted" and observer.dropped == 5
    assert verify(bridge.store)["records"] == 10
    first = export_audit(bridge.store, tmp_path / "audit-001.json", limit=3)
    second = export_audit(
        bridge.store, tmp_path / "audit-002.json", after=first["next_cursor"], limit=3
    )
    assert first["exported_records"] == second["exported_records"] == 3
    assert second["next_cursor"] == 6
    assert (tmp_path / "audit-001.json").stat().st_mode & 0o077 == 0
    assert "DO_NOT_LOG" not in (tmp_path / "audit-001.json").read_text()
    with pytest.raises(FileExistsError):
        export_audit(bridge.store, tmp_path / "audit-001.json", limit=1)
    assert verify(bridge.store)["valid"] and verify(bridge.store)["records"] == 10
    async_ready = readiness(
        bridge,
        "local",
        ReadinessInput(
            workflow_id="budget-full",
            operations=["file.read"],
        ),
    )
    assert async_ready["requested_prerequisites_ready"] is False
    assert async_ready["diagnostic"]["error_code"] == "diagnostic_recording_unavailable"


async def test_actual_handshake_and_reconnect_trace_uses_existing_audit_chain(
    http_bridge,  # noqa: F811
):
    bridge, endpoint = http_bridge
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    async with MCPClientPool(observer=observer) as pool:
        peer = Peer("daemon", url=endpoint, token="local-test-" + "a" * 40)
        await pool.connect(peer)
        first_id = pool.connection_ids["daemon"]
        await pool.call("daemon", "bridge_health", {})
        await pool.disconnect("daemon")
        await pool.connect(peer)
        assert first_id != pool.connection_ids["daemon"]
    entries = [
        json.loads(r[0])
        for r in bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='diagnostic.connection' ORDER BY seq"
        )
    ]
    phases = [x["phase"] for x in entries]
    assert phases.index("initialize.started") < phases.index("initialize.response")
    assert phases.index("initialize.response") < phases.index("initialized.sent")
    assert phases.index("initialized.sent") < phases.index("connection.ready")
    assert any(e.get("previous_connection_id") == first_id for e in entries)
    assert "local-test-" not in json.dumps(entries)
    assert endpoint not in json.dumps(entries)
    assert all(e["external_tunnel"] == "unknown" for e in entries)
    assert verify(bridge.store)["valid"]


async def test_observer_failure_cannot_mask_success_or_replay_remote_call(http_bridge):  # noqa: F811
    _, endpoint = http_bridge

    class BrokenObserver:
        def __call__(self, *args, **kwargs):
            raise OSError("DO_NOT_LOG_PRIVATE_STORAGE_PATH")

        def close(self):
            raise OSError("DO_NOT_LOG_PRIVATE_STORAGE_PATH")

    async with MCPClientPool(observer=BrokenObserver()) as pool:
        await pool.connect(Peer("daemon", url=endpoint, token="local-test-" + "a" * 40))
        result = await pool.call("daemon", "bridge_health", {})
        assert result.structuredContent["dispatcher_active"]
    assert pool.observation_failures > 0


async def test_lost_write_response_is_diagnosed_then_reconciled_once(
    http_bridge,  # noqa: F811
    monkeypatch,
):
    bridge, endpoint = http_bridge
    bridge.config.principals["local"].approval_mode = "automatic"
    root = bridge.config.principals["local"].roots[0]
    value = request("file.write", {"path": root + "/private-target", "text": "PRIVATE_BODY"})
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    async with MCPClientPool(observer=observer) as pool:
        peer = Peer("daemon", url=endpoint, token="local-test-" + "a" * 40)
        await pool.connect(peer)
        original = pool.sessions["daemon"].call_tool
        calls = []

        async def lose(*args, **kwargs):
            calls.append(args[0])
            await original(*args, **kwargs)
            raise TimeoutError("RAW_PRIVATE_TRANSPORT_ERROR")

        monkeypatch.setattr(pool.sessions["daemon"], "call_tool", lose)
        with pytest.raises(BridgeError, match="do not retry blindly"):
            await pool.call("daemon", "task_request", {"request": value.model_dump()})
        assert calls == ["task_request"]
        await bridge.tasks.wait("local", value.task_id)
        await pool.disconnect("daemon")
        await pool.connect(peer)
        report = (
            await pool.call("daemon", "task_diagnose", {"task_id": value.task_id})
        ).structuredContent
        assert report["state"] == "completed" and report["started"]
        assert not report["automatic_retry"]
        assert any(e["phase"] == "call.outcome_unknown" for e in report["connection_evidence"])
        assert any(e["phase"] == "initialized.sent" for e in report["connection_evidence"])
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert (
            sum(e["state"] == "running" for e in bridge.events("local", value.task_id)["events"])
            == 1
        )
        assert "PRIVATE_BODY" not in json.dumps(report)
        assert "private-target" not in json.dumps(report)
        assert "RAW_PRIVATE_TRANSPORT_ERROR" not in json.dumps(report)


async def test_initialize_timeout_reports_unknown_remote_state_without_retry(
    http_bridge,  # noqa: F811
    monkeypatch,
):
    bridge, endpoint = http_bridge

    async def stall(session, *args, **kwargs):
        session.notice("initialize.started")
        await asyncio.sleep(10)

    monkeypatch.setattr(ObservedClientSession, "send_request", stall)
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    async with MCPClientPool(call_timeout=0.05, observer=observer) as pool:
        with pytest.raises(BridgeError) as failure:
            await pool.connect(Peer("daemon", url=endpoint, token="local-test-" + "a" * 40))
        report = failure.value.diagnostic
        assert report["error_code"] == "peer_connection"
        assert report["accepted"] == report["started"] == "unknown"
        assert report["automatic_retry"] is False and report["connection_id"]
        assert endpoint not in json.dumps(report)
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
