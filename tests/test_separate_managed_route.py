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


class _Recipient:
    def __init__(self, bridge, recipient):
        self.bridge, self.recipient = bridge, recipient

    async def call(self, connection, tool, arguments):
        assert connection == "daemon"
        messages = self.bridge.messages
        if tool == "message_receive":
            value = messages.receive(self.recipient, **arguments)
        elif tool == "message_get":
            value = messages.get(self.recipient, arguments["message_id"])
        elif tool == "message_ack":
            value = messages.ack(
                self.recipient, arguments["message_id"], arguments["receipt"]
            )
        elif tool == "message_send":
            from kirabridge.message_manager import MessageSend

            value = messages.send(
                self.recipient, MessageSend.model_validate(arguments["message"])
            )
        else:
            raise AssertionError(tool)
        return type("Call", (), {"structuredContent": value, "isError": False})()


class _Pool:
    def __init__(self, bridge):
        self.bridge = bridge

    def __call__(self, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def connect(self, connection):
        return None

    async def call(self, connection, tool, arguments):
        return await _Recipient(self.bridge, "probe").call(connection, tool, arguments)


def _parties(config):
    from kirabridge.bridge_core.config import AgentConfig

    for name, peers in {
        "chatgpt": ["probe", "codex"],
        "probe": ["chatgpt"],
        "codex": ["chatgpt"],
    }.items():
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["message.send", "message.read", "message.ack", "agent.execute"]
        policy.approval_mode = "automatic"
        policy.message_peers = peers
        policy.agents = ["probe", "codex"]
        config.principals[name] = policy
    config.agents["probe"] = AgentConfig(kind="codex", executable="/usr/bin/true")
    config.agents["codex"] = AgentConfig(kind="codex", executable="/usr/bin/true")
    config.visible_handoffs.enabled = True
    config.messaging.separate_managed_after = 1_000


def _plant_old(bridge):
    from kirabridge.message_manager import MessageSend

    held = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="old-held",
            idempotency_key="old-held",
            body="old held",
            kind="note",
            dispatch=False,
        ),
    )
    unknown = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="old-unknown",
            idempotency_key="old-unknown",
            body="old unknown",
            kind="note",
            dispatch=False,
        ),
    )
    bridge.store.db.execute(
        "UPDATE messages SET created=10 WHERE id IN (?,?)", (held["id"], unknown["id"])
    )
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state,evidence) VALUES (?,'queued','{}'),(?,'unknown','{}')",
        (held["id"], unknown["id"]),
    )
    bridge.store.db.execute(
        "INSERT INTO queue_holds(queue_id,item_id,actor,created,reason) VALUES ('messages',?,?,?,?)",
        (held["id"], "test", 10, "preserved"),
    )
    return held["id"], unknown["id"]


def _arm(monkeypatch, bridge, adapter, *, replace_execute=True, use_process=False):
    pool = _Pool(bridge)
    monkeypatch.setattr(
        "kirabridge.message_manager.receiver.MCPClientPool", lambda **kwargs: pool
    )
    monkeypatch.setattr("kirabridge.message_manager.receiver.peer", lambda *args: None)

    if use_process:
        pass
    elif replace_execute:

        async def execute(task, args, principal, running, progress, **kwargs):
            return await adapter(task, args, kwargs)

        monkeypatch.setattr(bridge.agents, "execute", execute)
    else:

        async def adapter_execute(task, args, config, roots, running, progress, **kwargs):
            return await adapter(task, args, kwargs)

        bridge.agents.adapters["codex"].execute = adapter_execute

    async def visible_dispatch(*args, **kwargs):
        raise AssertionError("visible handoff was used")

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", visible_dispatch)


def _send_new(bridge, key):
    from kirabridge.bridge_core.config import ReceiverConfig
    from kirabridge.message_manager import MessageSend

    bridge.config.messaging.receivers["probe"] = ReceiverConfig(
        cwd=bridge.config.principals["probe"].roots[0], timeout=5
    )
    return bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="probe",
            conversation_id=key,
            idempotency_key=key,
            body="Neue isolierte Frage",
            kind="work",
            dispatch=True,
        ),
    )


def _states(bridge, held_id, unknown_id):
    rows = dict(
        bridge.store.db.execute(
            "SELECT message_id,state FROM message_jobs WHERE message_id IN (?,?)",
            (held_id, unknown_id),
        )
    )
    return rows[held_id], rows[unknown_id]


async def test_new_message_roundtrip_leaves_old_jobs_untouched(bridge, config, monkeypatch):
    _parties(config)
    held_id, unknown_id = _plant_old(bridge)
    seen = {}

    async def adapter(task, args, kwargs):
        seen["separate"] = kwargs["separate_managed"]
        seen["visible_id"] = task["visible_message_id"]
        seen["prompt"] = args.prompt
        return {"success": True, "text": "Isolierte Antwort", "evidence": {}}

    _arm(monkeypatch, bridge, adapter)
    sent = _send_new(bridge, "fresh-roundtrip")
    assert await bridge.message_receiver._dispatch_next("probe") is True
    completed = bridge.messages.get("chatgpt", sent["id"])
    assert completed["acknowledged"] is not None
    assert completed["processing"]["state"] == "completed"
    assert completed["processing"]["evidence"]["session_scope"] == "separate_managed_session"
    assert completed["processing"]["reply_id"]
    reply = bridge.messages.get("probe", completed["processing"]["reply_id"])
    assert reply["body"] == "Isolierte Antwort"
    assert reply["reply_to"] == sent["id"] and reply["kind"] == "result"
    assert (
        bridge.store.db.execute(
            "SELECT 1 FROM message_jobs WHERE message_id=?", (reply["id"],)
        ).fetchone()
        is None
    )
    assert seen["separate"] is True and seen["visible_id"] is None
    assert "Neue isolierte Frage" in seen["prompt"]
    assert "KiraBridge addressed communication" in seen["prompt"]
    assert _states(bridge, held_id, unknown_id) == ("queued", "unknown")
    assert bridge.message_receiver._claim(held_id) is None
    assert bridge.message_receiver._claim(unknown_id) is None
    assert _states(bridge, held_id, unknown_id) == ("queued", "unknown")


async def test_timeout_and_restart_do_not_replay_unknown_or_held_jobs(bridge, config, monkeypatch):
    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.bridge_core.config import ReceiverConfig

    _parties(config)
    held_id, unknown_id = _plant_old(bridge)

    calls = {"n": 0}

    async def slow(task, args, kwargs):
        import asyncio

        calls["n"] += 1
        await asyncio.sleep(1)
        return {"success": True, "text": "zu spät", "evidence": {}}

    _arm(monkeypatch, bridge, slow, replace_execute=False)
    sent = _send_new(bridge, "fresh-timeout")
    bridge.config.messaging.receivers["probe"] = ReceiverConfig(
        cwd=config.principals["probe"].roots[0], timeout=0.05
    )
    await bridge.message_receiver._dispatch_next("probe")
    failed = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert failed["state"] == "unknown" and failed["error"] == "agent_timeout"
    assert calls["n"] == 1
    assert await bridge.message_receiver._dispatch_next("probe") is False
    reopened = Bridge(config)
    try:
        assert reopened.messages.get("chatgpt", sent["id"])["processing"]["state"] == "unknown"
        assert reopened.message_receiver._claim(sent["id"]) is None
        assert reopened.message_receiver._claim(held_id) is None
        assert reopened.message_receiver._claim(unknown_id) is None
    finally:
        reopened.store.close()
    assert _states(bridge, held_id, unknown_id) == ("queued", "unknown")


async def test_cancelled_turn_stays_unknown_and_a_later_message_still_completes(
    bridge, config, monkeypatch
):
    import asyncio

    _parties(config)
    held_id, unknown_id = _plant_old(bridge)
    calls = {"n": 0}

    async def adapter(task, args, kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError
        return {"success": True, "text": "Nach dem Abbruch", "evidence": {}}

    _arm(monkeypatch, bridge, adapter)
    first = _send_new(bridge, "fresh-cancel")
    with pytest.raises(asyncio.CancelledError):
        await bridge.message_receiver._dispatch_next("probe")
    cancelled = bridge.messages.get("chatgpt", first["id"])["processing"]
    assert cancelled["state"] == "unknown" and cancelled["error"] == "receiver_interrupted"
    assert await bridge.message_receiver._dispatch_next("probe") is False
    second = _send_new(bridge, "fresh-after-cancel")
    assert await bridge.message_receiver._dispatch_next("probe") is True
    done = bridge.messages.get("chatgpt", second["id"])
    assert done["processing"]["state"] == "completed"
    assert done["acknowledged"] is not None
    assert _states(bridge, held_id, unknown_id) == ("queued", "unknown")


async def test_local_process_replies_without_touching_old_jobs(bridge, config, monkeypatch):
    from pathlib import Path

    _parties(config)
    held_id, unknown_id = _plant_old(bridge)
    workspace = Path(config.principals["local"].roots[0])
    program = workspace / "fake-codex"
    program.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "for event in (\n"
        '    {"type": "thread.started", "thread_id": "local-thread"},\n'
        '    {"type": "turn.started"},\n'
        '    {"type": "item.completed", "item": {"type": "agent_message", "text": "Prozessantwort"}},\n'
        '    {"type": "turn.completed"},\n'
        "):\n"
        "    print(json.dumps(event), flush=True)\n"
    )
    program.chmod(0o755)
    config.agents["probe"].executable = str(program)
    _arm(monkeypatch, bridge, None, use_process=True)
    sent = _send_new(bridge, "fresh-process")
    assert await bridge.message_receiver._dispatch_next("probe") is True
    completed = bridge.messages.get("chatgpt", sent["id"])
    assert completed["acknowledged"] is not None
    assert completed["processing"]["state"] == "completed"
    assert completed["processing"]["evidence"]["session_scope"] == "separate_managed_session"
    assert completed["processing"]["evidence"]["pid"] > 0
    reply = bridge.messages.get("probe", completed["processing"]["reply_id"])
    assert reply["body"] == "Prozessantwort"
    assert _states(bridge, held_id, unknown_id) == ("queued", "unknown")
