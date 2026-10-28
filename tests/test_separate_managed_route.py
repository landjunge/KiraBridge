"""Default-off managed route for messages created after an explicit cutoff."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kirabridge.agent_manager import AgentManager
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import AgentInput
from kirabridge.message_manager.receiver import separate_managed_eligible
from kirabridge.terminal_manager import TerminalManager


def test_managed_route_is_off_and_visible_handoff_stays_mandatory(tmp_path):
    config = Config(data_dir=str(tmp_path))
    assert config.messaging.separate_managed_after is None
    assert config.messaging.receivers == {}
    assert config.visible_handoffs.enabled is True
    assert separate_managed_eligible(config, 10_000) is False
    with pytest.raises(ValidationError):
        Config(data_dir=str(tmp_path), visible_handoffs={"enabled": False})


def test_only_messages_at_or_after_the_cutoff_are_eligible(tmp_path):
    config = Config(data_dir=str(tmp_path), messaging={"separate_managed_after": 1_000})
    assert config.visible_handoffs.enabled is True
    assert separate_managed_eligible(config, 999) is False
    assert separate_managed_eligible(config, 1_000) is True
    assert separate_managed_eligible(config, 1_001) is True


class _Visible:
    def __init__(self):
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        return {"success": True, "text": "visible", "evidence": {}}


class _Adapter:
    interface_version = "1"

    def __init__(self):
        self.calls = []

    async def execute(self, task, args, config, roots, running, progress, **kwargs):
        self.calls.append(task)
        return {"success": True, "text": "managed", "evidence": {}}


def _manager(tmp_path):
    config = Config(
        data_dir=str(tmp_path),
        agents={"codex": {"kind": "codex", "executable": "/usr/bin/true"}},
        messaging={"separate_managed_after": 1_000},
    )
    manager = AgentManager(config, TerminalManager(config.terminal))
    manager.adapters["codex"] = _Adapter()
    manager.visible_handoffs = _Visible()
    return manager


def _args(tmp_path):
    return AgentInput(agent="codex", prompt="new marker", cwd=str(tmp_path), timeout=5)


def _policy():
    return PrincipalConfig(
        approval_mode="automatic",
        capabilities=["message.read", "agent.execute"],
        agents=["codex"],
        roots=["/tmp"],
    )


async def _run(manager, tmp_path, separate_managed):
    async def unused(_evidence):
        return None

    return await manager.execute(
        {"id": "run-1", "principal": "codex"},
        _args(tmp_path),
        _policy(),
        unused,
        unused,
        separate_managed=separate_managed,
    )


async def test_default_execution_still_uses_the_visible_handoff(tmp_path):
    manager = _manager(tmp_path)
    result = await _run(manager, tmp_path, False)
    assert result["text"] == "visible"
    assert manager.visible_handoffs.calls == 1
    assert manager.adapters["codex"].calls == []


async def test_explicit_new_message_uses_the_adapter_without_a_visible_window(tmp_path):
    manager = _manager(tmp_path)
    result = await _run(manager, tmp_path, True)
    assert result["text"] == "managed"
    assert manager.visible_handoffs.calls == 0
    assert manager.adapters["codex"].calls[0]["id"] == "run-1"
    assert manager.config.visible_handoffs.enabled is True
