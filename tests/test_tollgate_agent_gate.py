"""TollGate daily-budget gate at the single AgentManager.execute hook (fake TollGate)."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge.agent_manager import AgentManager, tollgate_gate
from kirabridge.bridge_core.config import AgentConfig, Config
from kirabridge.bridge_core.models import AgentInput, BridgeError, digest


def verdict(decision, source="none", plan=None, reason="r"):
    return {
        "decision": decision,
        "reason": reason,
        "limit_source": source,
        "day": {"spent_usd": 5.2, "limit_usd": 5.0, "usd_kind": "measured"},
        "plan": plan,
        "valid_until": None,
    }


class Harness:
    def __init__(self, tmp_path, gate, **config):
        self.calls, self.runs = [], []
        self.manager = AgentManager(Config(**config), None)
        harness = self

        class Adapter:
            interface_version = "1"

            async def execute(self, task, args, config, roots, running, progress):
                harness.runs.append(task["id"])
                return {"success": True, "text": "ok", "evidence": {"adapter": "fake"}}

        def fake_gate(consumer):
            self.calls.append(consumer)
            if isinstance(gate, BaseException):
                raise gate
            if callable(gate):
                return gate(consumer)
            return gate

        self.manager.adapters["opencode_http"] = Adapter()
        self.manager.config.agents["grok"] = AgentConfig(
            kind="opencode_http",
            model="m/x",
            server_url="http://127.0.0.1:1",
            server_username_env="U",
            server_password_env="P",
        )
        self.manager.tollgate_loader = lambda: fake_gate
        self.principal = SimpleNamespace(
            agents=["grok"], permission_level=None, roots=[str(tmp_path)], capabilities=[]
        )
        self.args = AgentInput(agent="grok", prompt="p", cwd=str(tmp_path), timeout=5)

    async def run(self, task_id="t1"):
        return await self.manager.execute(
            {"id": task_id, "principal": "local"},
            self.args,
            self.principal,
            AsyncMock(),
            AsyncMock(),
        )


async def test_deny_from_user_envelope_blocks_the_run(tmp_path):
    h = Harness(tmp_path, verdict("deny", "user_envelope"))
    with pytest.raises(BridgeError) as raised:
        await h.run()
    assert raised.value.code == "tollgate_budget_reached"
    assert "grok" in str(raised.value) and "5.2" in str(raised.value) and "5.0" in str(raised.value)
    assert h.runs == [] and h.calls == ["grok"]


async def test_allow_runs_with_evidence(tmp_path):
    h = Harness(tmp_path, verdict("allow", "user_envelope"))
    result = await h.run()
    assert h.runs == ["t1"]
    assert result["evidence"]["tollgate"] == {
        "decision": "allow",
        "reason": "r",
        "limit_source": "user_envelope",
        "plan_exhausted": False,
    }


async def test_unknown_runs(tmp_path):
    h = Harness(tmp_path, verdict("unknown", "unavailable"))
    result = await h.run()
    assert h.runs == ["t1"] and result["evidence"]["tollgate"]["decision"] == "unknown"


async def test_deny_without_user_envelope_never_blocks(tmp_path):
    h = Harness(tmp_path, verdict("deny", "none"))
    await h.run()
    assert h.runs == ["t1"]


async def test_plan_exhausted_note(tmp_path):
    h = Harness(tmp_path, verdict("allow", "none", plan={"exhausted": True}))
    result = await h.run()
    assert result["evidence"]["tollgate"]["plan_exhausted"] is True


@pytest.mark.parametrize("failure", [RuntimeError("boom"), ImportError("x"), ValueError("pin")])
async def test_exception_runs_with_unavailable_evidence(tmp_path, failure):
    h = Harness(tmp_path, failure)
    result = await h.run()
    assert h.runs == ["t1"]
    assert result["evidence"]["tollgate_unavailable"] is True
    assert result["evidence"]["tollgate"]["decision"] == "unavailable"


async def test_loader_failure_runs_with_unavailable_evidence(tmp_path):
    h = Harness(tmp_path, verdict("allow"))

    def broken():
        raise ImportError("no tollgate")

    h.manager.tollgate_loader = broken
    result = await h.run()
    assert h.runs == ["t1"] and result["evidence"]["tollgate_unavailable"] is True


async def test_timeout_runs_with_unavailable_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tollgate_gate, "GATE_TIMEOUT_SECONDS", 0.05)
    h = Harness(tmp_path, lambda consumer: time.sleep(0.5) or verdict("deny", "user_envelope"))
    started = time.monotonic()
    result = await h.run()
    assert time.monotonic() - started < 0.4
    assert h.runs == ["t1"] and result["evidence"]["tollgate_unavailable"] is True


async def test_malformed_answer_runs(tmp_path):
    h = Harness(tmp_path, {"nonsense": 1})
    result = await h.run()
    assert h.runs == ["t1"] and result["evidence"]["tollgate_unavailable"] is True


async def test_switch_off_makes_no_call(tmp_path):
    h = Harness(tmp_path, verdict("deny", "user_envelope"), workflow_control={"budget": False})
    result = await h.run()
    assert h.calls == [] and h.runs == ["t1"]
    assert "tollgate" not in result["evidence"]


async def test_retry_of_same_task_calls_gate_again_without_duplicate_run(tmp_path):
    answers = iter([verdict("deny", "user_envelope"), verdict("allow", "user_envelope")])
    h = Harness(tmp_path, lambda consumer: next(answers))
    with pytest.raises(BridgeError):
        await h.run("same")
    assert h.runs == []
    await h.run("same")
    assert h.calls == ["grok", "grok"] and h.runs == ["same"]


async def test_not_granted_agent_is_not_gated(tmp_path):
    h = Harness(tmp_path, verdict("allow"))
    h.principal.agents = []
    with pytest.raises(BridgeError) as raised:
        await h.run()
    assert raised.value.code == "agent_denied" and h.calls == []


async def test_default_loader_without_pin_is_unavailable_not_an_exception(tmp_path):
    manager = AgentManager(Config(), None)
    note = await tollgate_gate.check_budget(manager.tollgate_loader, "grok")
    assert note["decision"] == "unavailable"


def test_budget_switch_is_strict_and_keeps_the_config_digest():
    assert Config().workflow_control.budget is True
    assert "budget" not in Config().model_dump()["workflow_control"]
    assert digest(Config().model_dump()) == digest(Config(workflow_control={}).model_dump())
    assert (
        Config(workflow_control={"budget": False}).model_dump()["workflow_control"]["budget"]
        is False
    )
    with pytest.raises(ValidationError):
        Config(workflow_control={"budget": "no"})
