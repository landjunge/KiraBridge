import asyncio
import json
import sys
from pathlib import Path

import pytest
from conftest import request
from pydantic import ValidationError

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.config import PrincipalConfig
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.security_manager import request_hash


@pytest.mark.parametrize("entry", ["prepare", "submit"])
async def test_automatic_tasks_execute_once_without_a_token(bridge, config, entry):
    config.principals["local"].approval_mode = "automatic"
    root = Path(config.principals["local"].roots[0])
    target = root / "once.txt"
    value = request("file.write", {"path": str(target), "text": "once"})
    initial = getattr(bridge, entry)("local", value)
    assert initial["state"] == "queued"
    assert initial["receipt"] is None and initial["started"] is None
    assert not target.exists()
    assert bridge.prepare("local", value)["id"] == value.task_id
    assert bridge.health("local")["approval_required"] is False
    assert bridge.health("other")["approval_required"] is True
    assert bridge.store.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    audit = bridge.store.db.execute(
        "SELECT metadata FROM audit WHERE kind='task.auto_approved'"
    ).fetchall()
    assert len(audit) == 1
    assert json.loads(audit[0][0]) == {
        "source": "principal_policy",
        "approval_mode": "automatic",
        "operation": "file.write",
        "request_hash": request_hash(value),
    }
    with pytest.raises(BridgeError, match="different request"):
        bridge.prepare(
            "local",
            value.model_copy(update={"arguments": {"path": str(target), "text": "changed"}}),
        )
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "completed" and final["started"] is not None
        assert target.read_text() == "once"
        assert bridge.prepare("local", value)["state"] == "completed"
        events = bridge.events("local", value.task_id)["events"]
        assert [event["state"] for event in events] == [
            "created",
            "queued",
            "accepted",
            "running",
            "completed",
        ]
        with pytest.raises(BridgeError, match="not found"):
            bridge.task("other", value.task_id)
        assert verify(bridge.store)["valid"]


async def test_automatic_mode_keeps_capability_path_and_executable_limits(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].executables = []
    config.principals["empty"] = PrincipalConfig(approval_mode="automatic")
    root = config.principals["local"].roots[0]
    with pytest.raises(BridgeError, match="Capability"):
        bridge.prepare("empty", request(arguments={"path": root}))
    commands = [
        request("file.read", {"path": str(Path(root).parent / "outside")}, task_id="outside"),
        request(
            "terminal.execute",
            {"argv": [sys.executable, "-c", "print(1)"], "cwd": root},
            task_id="binary",
        ),
    ]
    async with bridge:
        for value in commands:
            bridge.prepare("local", value)
            final = await bridge.tasks.wait("local", value.task_id)
            assert final["state"] == "failed" and final["started"] is None
        assert final["error"]["code"] == "executable_denied"


def test_manual_default_and_switch_back_restore_individual_approvals(bridge, config):
    assert PrincipalConfig().approval_mode == "manual"
    for invalid in ["none", "unrestricted", False]:
        with pytest.raises(ValidationError):
            PrincipalConfig(approval_mode=invalid)
    config.principals["local"].approval_mode = "automatic"
    value = request(arguments={"path": config.principals["local"].roots[0]})
    assert bridge.prepare("local", value)["state"] == "queued"
    config.principals["local"].approval_mode = "manual"
    pending = value.model_copy(update={"task_id": "pending", "idempotency_key": "pending"})
    assert bridge.prepare("local", pending)["state"] == "created"
    new = value.model_copy(update={"task_id": "new", "idempotency_key": "new"})
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", new)
    assert bridge.store.get(pending.task_id)["started"] is None


def test_explicit_tokens_are_still_validated_in_automatic_mode(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    value = request(arguments={"path": config.principals["local"].roots[0]})
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", value, "invalid-token")
    token = bridge.security.grant("local", value)
    bridge.submit("local", value, token)
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0] is not None
    second = value.model_copy(update={"task_id": "second", "idempotency_key": "second"})
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", second, token)


async def test_automatic_mode_never_reexecutes_an_interrupted_task(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    target = Path(config.principals["local"].roots[0]) / "must-not-write"
    value = request("file.write", {"path": str(target), "text": "no"})
    bridge.prepare("local", value)
    bridge.store.claim("previous-worker", 30)
    bridge.store.transition(value.task_id, State.RUNNING, {"external_start_observed": True})
    async with bridge:
        assert (await bridge.tasks.wait("local", value.task_id))["state"] == "unknown"
        with pytest.raises(BridgeError, match="never started"):
            bridge.tasks.retry("local", value.task_id, value, "")
        assert not target.exists()


async def test_real_stdio_automatic_mode_and_optional_token(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    config = tmp_path / "automatic.toml"
    config.write_text(
        f"data_dir={json.dumps(str(tmp_path / 'state'))}\n"
        '[principals.local]\napproval_mode="automatic"\n'
        'capabilities=["bridge.health","task.read","file.list"]\n'
        f"roots=[{json.dumps(str(root))}]\n"
    )
    async with MCPClientPool() as clients:
        await clients.connect(
            Peer(
                "auto",
                command=sys.executable,
                args=("-m", "kirabridge.cli", "--config", str(config), "serve"),
            )
        )
        health = (await clients.call("auto", "bridge_health", {})).structuredContent
        assert health["approval_mode"] == "automatic" and not health["approval_required"]
        for tool in ["task_request", "task_submit"]:
            value = request(arguments={"path": str(root)}, task_id=tool)
            initial = await clients.call("auto", tool, {"request": value.model_dump()})
            assert not initial.isError and initial.structuredContent["state"] == "queued"
            async with asyncio.timeout(10):
                while True:
                    final = (
                        await clients.call("auto", "task_get", {"task_id": value.task_id})
                    ).structuredContent
                    if final["state"] == "completed":
                        break
                    await asyncio.sleep(0.02)
        catalog = (await clients.call("auto", "operation_catalog", {})).structuredContent
        assert catalog["operations"]["file.list"]["approval_required"] is False
        tools = (await clients.sessions["auto"].list_tools()).tools
        for tool in tools:
            if tool.name in {"task_submit", "clipboard_read", "clipboard_write"}:
                assert "approval" not in tool.inputSchema.get("required", [])
