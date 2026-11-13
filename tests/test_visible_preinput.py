# Imported fixtures are used through pytest's dependency injection.
# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from test_visible_dispatch_wait import enqueue
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError


def become_busy_before_paste(monkeypatch, bridge, transport):
    original = bridge.visible_handoffs.check_target
    checks = []

    async def check(principal, target, binding, *, ready=False):
        if ready:
            checks.append(target)
            if len(checks) == 2:
                transport["text"] = "╭──────╮\nThinking… [stop]\n│ ❯      │\n╰────── Grok 1.0 ─╯"
        return await original(principal, target, binding, ready=ready)

    monkeypatch.setattr(bridge.visible_handoffs, "check_target", check)
    return original, checks


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_second_preinput_check_preserves_newly_busy_agent_and_records_no_input(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    _, checks = become_busy_before_paste(monkeypatch, bridge, transport)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.execute(
            {"id": "became-busy-before-input", "principal": sender},
            AgentInput(agent="grok", prompt="One authorized task", cwd="/tmp"),
            callback,
            callback,
        )
    assert exc.value.code == "visible_target_working"
    assert checks == ["grok", "grok"] and transport["calls"] == []
    status = bridge.visible_handoffs.status(sender, "became-busy-before-input")
    assert status["state"] == "interrupted"
    assert status["evidence"] == {
        "reason": "visible_target_working",
        "preinput_abort": True,
        "terminal_input_attempted": False,
        "automatic_retry": False,
    }
    assert all(
        event["state"] not in {"inserting", "inserted", "submitting", "return_sent", "sent"}
        for event in status["events"]
    )
    message = bridge.messages.get(sender, status["message_id"])
    assert message["acknowledged"] is None


class LocalRecipientPool:
    def __init__(self, bridge, recipient):
        self.bridge, self.recipient = bridge, recipient

    async def call(self, connection, tool, arguments):
        assert connection == "daemon"
        if tool == "message_receive":
            value = self.bridge.messages.receive(self.recipient, **arguments)
        elif tool == "message_get":
            value = self.bridge.messages.get(self.recipient, arguments["message_id"])
        elif tool == "message_ack":
            value = self.bridge.messages.ack(
                self.recipient, arguments["message_id"], arguments["receipt"]
            )
        else:
            raise AssertionError("Unexpected recipient operation: " + tool)
        return SimpleNamespace(structuredContent=value, isError=False)


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app"])
async def test_proven_preinput_abort_can_resume_once_without_replaying_a_return(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    sent = enqueue(bridge, sender=sender, key="preinput-race-then-ready")
    receiver = bridge.message_receiver
    message, first_run = receiver._claim(sent["id"])
    original, checks = become_busy_before_paste(monkeypatch, bridge, transport)
    pool = LocalRecipientPool(bridge, "grok")
    await receiver._process(pool, message, first_run)
    queued = bridge.messages.get(sender, sent["id"])
    assert checks == ["grok", "grok"] and transport["calls"] == []
    assert queued["processing"]["state"] == "queued"
    assert queued["processing"]["run_id"] is None
    assert queued["processing"]["started"] is None
    assert queued["processing"]["evidence"]["terminal_input_attempted"] is False
    assert bridge.visible_handoffs.status(sender, first_run)["state"] == "interrupted"
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 0

    # Only the proved pre-input abort permits another observation and a new run.
    monkeypatch.setattr(bridge.visible_handoffs, "check_target", original)
    transport["text"] = "╭──────╮\n│ ❯      │\n╰────── Grok 1.0 ─╯"
    await bridge.visible_handoffs.dispatch_ready(sender, "grok")
    message, second_run = receiver._claim(sent["id"])
    assert second_run != first_run
    await receiver._process(pool, message, second_run)
    completed = bridge.messages.get(sender, sent["id"])
    assert completed["processing"]["state"] == "completed", completed
    assert completed["acknowledged"] is not None
    assert transport["calls"] == ["insert", "return"]
    assert bridge.visible_handoffs.status(sender, first_run)["state"] == "interrupted"
    assert bridge.visible_handoffs.status(sender, second_run)["state"] == "completed"
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
    assert receiver._claim(sent["id"]) is None
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_authenticated_ack_of_queued_work_completes_without_terminal_readiness(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    recipient = "codex" if sender == "grok" else "grok"
    sent = enqueue(bridge, sender=sender, target=recipient, key="externally-received")
    incoming = bridge.messages.receive(recipient)["messages"][0]
    bridge.messages.ack(recipient, incoming["id"], incoming["receipt"])

    async def forbidden(*args, **kwargs):
        raise AssertionError("Already acknowledged work must not observe or operate a terminal")

    def forbidden_pool(*args, **kwargs):
        raise AssertionError("Already acknowledged work must not start a receiver transport")

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", forbidden)
    monkeypatch.setattr(bridge.sessions, "read", forbidden)
    monkeypatch.setattr(bridge.sessions, "insert", forbidden)
    monkeypatch.setattr(bridge.sessions, "press_return", forbidden)
    monkeypatch.setattr("kirabridge.message_manager.receiver.MCPClientPool", forbidden_pool)
    assert not await bridge.message_receiver._dispatch_next()
    result = bridge.messages.get(sender, sent["id"])
    assert result["processing"]["state"] == "completed"
    assert result["processing"]["evidence"]["externally_acknowledged"] is True
    assert result["processing"]["started"] is None
    assert result["processing"]["run_id"] is None
    assert result["processing"]["reply_id"] is None
    assert transport["calls"] == []
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 0
    notices = bridge.store.db.execute("SELECT payload FROM completion_notices").fetchall()
    assert len(notices) == 1 and '"outcome":"not_executed"' in notices[0][0]
    assert not await bridge.message_receiver._dispatch_next()
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
