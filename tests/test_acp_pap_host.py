"""Synthetic-peer tests for the opt-in ACP-PAP host adapter (no model, agent or account)."""

import asyncio
import json
import os
import signal
from pathlib import Path

import pytest

pytest.importorskip("acp_pap")
PEER = Path("/Users/landjunge/ACP-PAP/tests/agent_peer.py")
# The peer runs in the ACP-PAP venv: the launch environment drops PYTHONPATH by design.
PEER_PYTHON = Path("/Users/landjunge/ACP-PAP/.venv/bin/python")
if not PEER.is_file() or not PEER_PYTHON.is_file():
    pytest.skip("ACP-PAP synthetic peer not present", allow_module_level=True)

import acp_pap  # noqa: E402

from kirabridge.agent_manager.acp_pap_host import ACPPAPHostAdapter, OwnedTask  # noqa: E402
from kirabridge.bridge_core.config import AgentConfig  # noqa: E402
from kirabridge.bridge_core.models import (  # noqa: E402
    AgentInput,
    BridgeError,
    UncertainExecution,
    digest,
)


class Setup:
    def __init__(self, tmp_path, prompt, mode="normal", extra=()):
        self.cwd = str(tmp_path)
        self.args = AgentInput(agent="peer", prompt=prompt, cwd=self.cwd, timeout=20)
        self.task = {
            "id": "task-" + prompt[:8],
            "principal": "local",
            "args": self.args.model_dump(),
        }
        self.config = AgentConfig(
            kind="acp_pap", executable=str(PEER_PYTHON), acp_pap_args=[str(PEER), mode, *extra]
        )
        self.roots = [self.cwd]
        self.running, self.progress = [], []

    async def run(self, adapter, **overrides):
        async def running(e):
            self.running.append(e)

        async def progress(e):
            self.progress.append(e)

        return await adapter.execute(
            self.task,
            self.args,
            self.config,
            self.roots,
            overrides.get("running", running),
            overrides.get("progress", progress),
        )


async def test_owned_task_session_and_grant_lookup(tmp_path):
    adapter = ACPPAPHostAdapter()
    seen = []
    original = adapter.session_update

    async def spy(session_id, update, **kwargs):
        seen.append((adapter.owned.copy(), kwargs["pap_binding"]))
        await original(session_id, update, **kwargs)

    adapter.session_update = spy
    s = Setup(tmp_path, "hello")
    result = await s.run(adapter)
    assert result["success"] and result["text"] == "hello"
    assert result["evidence"]["task_id"] == s.task["id"]
    assert result["evidence"]["request_sha256"] == digest(s.task["args"])
    ((owned, binding),) = seen
    record = owned[(binding.connection_id, binding.session_id)]
    assert record.task_id == s.task["id"] and record.principal == "local"
    assert binding.grant_ref == record.grant_ref and binding.cwd == str(Path(tmp_path).resolve())
    assert s.running[0]["task_id"] == s.task["id"] and len(s.running) == 1
    assert adapter.owned == {} and adapter._texts == {} and adapter._notify == {}


async def test_same_wire_session_id_in_two_connections(tmp_path):
    adapter = ACPPAPHostAdapter()
    a, b = Setup(tmp_path, "alpha", "fixed-id"), Setup(tmp_path, "bravo", "fixed-id")
    ra, rb = await asyncio.gather(a.run(adapter), b.run(adapter))
    assert (ra["text"], rb["text"]) == ("alpha", "bravo")
    assert ra["evidence"]["session_id"] == rb["evidence"]["session_id"] == "shared-wire-id"
    assert {e["task_id"] for e in a.running + a.progress} == {a.task["id"]}
    assert {e["task_id"] for e in b.running + b.progress} == {b.task["id"]}


async def test_forged_binding_and_foreign_session_have_no_effect(tmp_path, monkeypatch):
    reads = []
    from kirabridge.filesystem_manager import FilesystemManager

    monkeypatch.setattr(FilesystemManager, "read", lambda *a, **k: reads.append(a) or {"text": ""})
    # Owned: the peer's forged pap_binding is replaced by the trusted one and the
    # request reaches the existing read policy exactly once.
    owned = await Setup(tmp_path, "ingress|read_text_file|owned").run(ACPPAPHostAdapter())
    assert json.loads(owned["text"])["status"] == "delivered" and len(reads) == 1
    # Foreign session ID: rejected before any host handler runs.
    foreign = await Setup(tmp_path, "ingress|read_text_file|other").run(ACPPAPHostAdapter())
    assert json.loads(foreign["text"])["status"] == "rejected" and len(reads) == 1


async def test_peer_path_checked_by_existing_policy(tmp_path):
    s = Setup(tmp_path, "ingress|read_text_file|owned")
    result = await s.run(ACPPAPHostAdapter())
    assert json.loads(result["text"]) == {
        "method": "read_text_file",
        "status": "rejected",
        "code": -32602,
    }  # /synthetic-only is outside the principal roots


async def test_unimplemented_and_foreign_operations_rejected(tmp_path):
    for method in ("write_text_file", "create_terminal", "kill_terminal"):
        s = Setup(tmp_path, f"ingress|{method}|owned")
        result = await s.run(ACPPAPHostAdapter())
        assert json.loads(result["text"])["status"] == "rejected"


async def test_duplicate_session_closes_connection_without_alias(tmp_path):
    adapter = ACPPAPHostAdapter()
    s = Setup(tmp_path, "x", "duplicate")
    launch = acp_pap.LaunchSpec(PEER_PYTHON, args=tuple(s.config.acp_pap_args), cwd=Path(tmp_path))
    from acp.schema import ClientCapabilities

    async with acp_pap.connect(launch, host=adapter, capabilities=ClientCapabilities()) as agent:
        first = await agent.session(cwd=str(tmp_path), grant_ref="grant-1")
        with pytest.raises(ValueError):
            await agent.session(cwd=str(tmp_path), grant_ref="grant-2")
        assert first.session_id == "shared-wire-id"
        with pytest.raises(RuntimeError):
            await agent.task(first.session_id, "replay")  # closed: no replay, no alias


async def test_host_handler_failure_keeps_terminal_response_and_records_delivery(tmp_path):
    s = Setup(tmp_path, "deliver")

    async def broken_running(event):
        raise RuntimeError("synthetic host persistence failure")

    result = await s.run(ACPPAPHostAdapter(), running=broken_running)
    assert result["success"] and result["text"] == "deliver"  # terminal response kept
    assert result["evidence"]["stop_reason"] == "end_turn"
    (failure,) = result["evidence"]["delivery_failures"]
    assert failure["task_id"] == s.task["id"] and failure["target"] == "host"
    persisted = [e for e in s.progress if e["event"] == "delivery_failure"]
    assert persisted[0]["task_id"] == s.task["id"] and persisted[0]["error_type"] == "RuntimeError"


async def test_failing_diagnostic_write_does_not_erase_response(tmp_path):
    s = Setup(tmp_path, "deliver")

    async def broken(event):
        raise RuntimeError("down")

    result = await s.run(ACPPAPHostAdapter(), running=broken, progress=broken)
    assert result["success"] and result["evidence"]["delivery_failures"]


async def test_permission_is_denied_without_new_approval_flow(tmp_path):
    s = Setup(tmp_path, "permission")
    result = await s.run(ACPPAPHostAdapter())
    assert result["evidence"]["stop_reason"] == "cancelled" and not result["success"]
    assert any(e["event"] == "permission_denied" for e in s.progress)


async def test_tool_scope_and_foreign_cwd_denied_before_spawn(tmp_path):
    adapter = ACPPAPHostAdapter()
    s = Setup(tmp_path, "x")
    s.args = s.args.model_copy(update={"local_tools": True})
    s.task["args"] = s.args.model_dump()
    with pytest.raises(BridgeError) as denied:
        await s.run(adapter)
    assert denied.value.code == "agent_tools_denied"
    s = Setup(tmp_path, "x")
    s.roots = [str(tmp_path / "elsewhere")]
    with pytest.raises(BridgeError) as outside:
        await s.run(adapter)
    assert outside.value.code == "path_denied"


async def test_eof_during_prompt_is_unknown_and_not_retried(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    calls = []
    original = acp_pap.client.ConnectedAgent.task

    async def counted(self, *a, **k):
        calls.append(1)
        return await original(self, *a, **k)

    monkeypatch.setattr(acp_pap.client.ConnectedAgent, "task", counted)
    s = Setup(tmp_path, "wait", extra=(str(pidfile),))

    async def killer():
        while not pidfile.exists() or not pidfile.read_text():
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        os.kill(int(pidfile.read_text()), signal.SIGKILL)

    kill = asyncio.create_task(killer())
    with pytest.raises(UncertainExecution) as unknown:
        await s.run(ACPPAPHostAdapter())
    await kill
    assert unknown.value.code == "agent_interrupted" and calls == [1]


async def test_local_wait_cancellation_stays_unknown_and_not_retried(tmp_path, monkeypatch):
    calls = []
    original = acp_pap.client.ConnectedAgent.task

    async def counted(self, *a, **k):
        calls.append(1)
        return await original(self, *a, **k)

    monkeypatch.setattr(acp_pap.client.ConnectedAgent, "task", counted)
    s = Setup(tmp_path, "wait")
    adapter = ACPPAPHostAdapter()
    with pytest.raises(TimeoutError):  # the AgentManager turns this into UNKNOWN
        async with asyncio.timeout(1.5):
            await s.run(adapter)
    assert calls == [1] and adapter.owned == {}


async def test_explicit_close_during_prompt_stays_unknown_and_not_retried(tmp_path, monkeypatch):
    calls = []
    original = acp_pap.client.ConnectedAgent.task

    async def closing(self, *a, **k):
        calls.append(1)
        asyncio.get_running_loop().call_later(0.7, lambda: asyncio.ensure_future(self.close()))
        return await original(self, *a, **k)

    monkeypatch.setattr(acp_pap.client.ConnectedAgent, "task", closing)
    s = Setup(tmp_path, "wait")
    with pytest.raises(UncertainExecution) as unknown:
        await s.run(ACPPAPHostAdapter())
    assert unknown.value.code == "agent_interrupted" and calls == [1]


async def test_read_handler_uses_trusted_binding_and_existing_roots(tmp_path):
    from acp import RequestError

    inside, outside = tmp_path / "root", tmp_path / "other"
    inside.mkdir()
    outside.mkdir()
    (inside / "a.txt").write_text("in")
    (outside / "b.txt").write_text("out")
    adapter = ACPPAPHostAdapter()
    binding = acp_pap.SessionBinding("c1", "s1", str(inside), "g1")
    adapter.owned[("c1", "s1")] = OwnedTask("t", "local", "h", str(inside), (str(inside),), "g1")
    assert (
        await adapter.read_text_file("s1", str(inside / "a.txt"), pap_binding=binding)
    ).content == "in"
    with pytest.raises(RequestError):  # path outside the principal's roots
        await adapter.read_text_file("s1", str(outside / "b.txt"), pap_binding=binding)
    for forged in (
        acp_pap.SessionBinding("c2", "s1", str(inside), "g1"),  # other connection, same wire ID
        acp_pap.SessionBinding("c1", "s1", str(inside), "forged"),  # forged grant reference
    ):
        with pytest.raises(RequestError):
            await adapter.read_text_file("s1", str(inside / "a.txt"), pap_binding=forged)
