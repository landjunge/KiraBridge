import sqlite3
import time
from types import SimpleNamespace

import pytest
from conftest import request

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.message_manager import MessageSend


@pytest.fixture
def voices(config):
    names = ["grok_app", "chatgpt", "grok", "codex", "local"]
    for name in names:
        policy = config.principals["local"].model_copy(deep=True)
        policy.approval_mode = "automatic"
        policy.capabilities += ["message.read", "message.send", "message.ack"]
        policy.message_peers = [other for other in names if other != name]
        config.principals[name] = policy
    instance = Bridge(config)
    yield instance
    instance.store.close()


def message(recipient="codex", body="Daniels Diktat", key="one", **kwargs):
    return MessageSend(
        recipient=recipient,
        body=body,
        conversation_id="outgoing",
        idempotency_key=key,
        dispatch=False,
        request_reply=False,
        **kwargs,
    )


@pytest.mark.parametrize("sender", ["grok_app", "chatgpt"])
def test_only_voice_messages_wait_then_release_exactly_once(voices, sender):
    channel = voices.messages
    value = message()
    pending = channel.send(sender, value)
    assert pending["message_buffer"]["state"] == "waiting"
    assert pending["message_buffer"]["expires"] - pending["created"] == 60
    assert not channel.receive("codex")["messages"]
    assert voices.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0
    assert channel.send(sender, value)["id"] == pending["id"]
    for action in [
        lambda: channel.get("codex", pending["id"]),
        lambda: channel.voice_policy.release(
            "chatgpt" if sender == "grok_app" else "grok_app", pending["id"], "go-go-go"
        ),
        lambda: channel.voice_policy.release(sender, pending["id"], "wrong"),
        lambda: channel.send(sender, value.model_copy(update={"body": "changed"})),
    ]:
        with pytest.raises(BridgeError):
            action()
    released = channel.voice_policy.release(sender, pending["id"], "go-go-go")
    assert released["body"] == value.body
    assert released["seq"] > 0
    assert channel.voice_policy.release(sender, pending["id"], "go-go-go")["id"] == pending["id"]
    assert channel.send(sender, value)["id"] == pending["id"]
    assert len(channel.receive("codex")["messages"]) == 1


@pytest.mark.parametrize("sender", ["grok", "codex"])
def test_terminal_messages_are_immediate_and_literal(voices, sender):
    recipient = "codex" if sender == "grok" else "grok"
    for i, body in enumerate(["hello", "literal go-go-go"]):
        sent = voices.messages.send(sender, message(recipient, body, str(i)))
        assert sent["body"] == body
        assert "message_buffer" not in sent
    assert len(voices.messages.receive(recipient)["messages"]) == 2


def test_suffix_releases_stripped_dictation_and_retries(voices):
    value = message(body="Wörtliches Diktat.\ngo-go-go\n")
    sent = voices.messages.send("grok_app", value)
    assert sent["body"] == "Wörtliches Diktat."
    assert voices.messages.send("grok_app", value)["id"] == sent["id"]
    assert voices.messages.receive("codex")["messages"][0]["body"] == sent["body"]
    with pytest.raises(BridgeError, match="empty"):
        voices.messages.send("grok_app", message(body="go-go-go", key="empty"))


def test_timeout_survives_restart_and_does_not_append_or_dispatch(voices, config, monkeypatch):
    config.voice_messaging.timeout_seconds = 7
    pending = voices.messages.send("grok_app", message("chatgpt"))
    reopened = Bridge(config)
    try:
        assert (
            reopened.messages.get("grok_app", pending["id"])["message_buffer"]
            == pending["message_buffer"]
        )
        import kirabridge.voice_message_policy as module

        monkeypatch.setattr(
            module, "time", SimpleNamespace(time=lambda: pending["message_buffer"]["expires"] + 1)
        )
        with pytest.raises(BridgeError, match="expired"):
            reopened.messages.voice_policy.release("grok_app", pending["id"], "go-go-go")
        expired = reopened.messages.send("grok_app", message("chatgpt"))
        assert expired["message_buffer"]["state"] == "expired"
        assert not reopened.messages.conversation("local", "eve-kira-shared")["messages"]
        assert not reopened.messages.receive("chatgpt")["messages"]
    finally:
        reopened.store.close()


def test_pending_release_gets_fresh_sequence_after_newer_deliveries(voices):
    pending = voices.messages.send("grok_app", message("chatgpt"))
    newer = voices.messages.send("grok_app", message("chatgpt", "neu go-go-go", "new"))
    sent = voices.messages.voice_policy.release("grok_app", pending["id"], "go-go-go")
    assert sent["seq"] > newer["seq"]
    result = voices.messages.receive("chatgpt", after=newer["seq"])
    assert [m["id"] for m in result["messages"]] == [sent["id"]]


def test_shared_channel_has_three_members_and_permanent_paginated_log(voices, config):
    config.messaging.max_conversation_messages = 2
    channel = voices.messages
    for i in range(5):
        sender, recipient = ("grok_app", "chatgpt") if i % 2 == 0 else ("chatgpt", "grok_app")
        sent = channel.send(sender, message(recipient, f"Diktat {i} go-go-go", str(i)))
        assert sent["conversation_id"] == "eve-kira-shared"
        assert sent["position"] == i + 1
        assert sent["created"] <= time.time()
    first = channel.conversation("local", "eve-kira-shared", limit=2)
    assert set(first["participants"]) == {"local", "grok_app", "chatgpt"}
    assert first["append_only"]
    next_page = channel.conversation("local", "eve-kira-shared", first["next_cursor"])
    assert len(next_page["messages"]) == 3
    selected = first["messages"][0]
    for principal in ["codex", "grok"]:
        for action in [
            lambda principal=principal: channel.conversation(principal, "eve-kira-shared"),
            lambda principal=principal: channel.get(principal, selected["id"]),
            lambda principal=principal: channel.events(principal, selected["id"]),
            lambda principal=principal: channel.receive(
                principal, conversation_id="eve-kira-shared"
            ),
            lambda principal=principal: channel.send(
                principal,
                message("chatgpt").model_copy(update={"conversation_id": "eve-kira-shared"}),
            ),
        ]:
            with pytest.raises(BridgeError):
                action()
        assert not channel.receive(principal)["messages"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        voices.store.db.execute("DELETE FROM messages WHERE id=?", (selected["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        voices.store.db.execute("UPDATE messages SET body='changed' WHERE id=?", (selected["id"],))
    received = channel.receive("chatgpt")["messages"][0]
    channel.ack("chatgpt", received["id"], received["receipt"])
    assert len(channel.conversation("local", "eve-kira-shared")["messages"]) == 5


async def test_eve_session_input_standing_grant_bypasses_gate_and_manual_approval(
    voices,
    config,
    monkeypatch,
):
    config.session_input_policy.enabled = True
    policy = config.principals["grok_app"]
    policy.approval_mode = "manual"
    policy.permission_level = "ask"
    policy.automatic_operations = ["session.input"]
    calls = []

    async def selected(*args):
        return None

    async def command(*args, **kwargs):
        calls.append(args)
        return ""

    monkeypatch.setattr(voices.sessions, "selected", selected)
    monkeypatch.setattr(voices.sessions, "command", command)
    value = request("session.input", {"pane_id": "%1", "expected_pid": 1, "text": "Diktat"})
    queued = voices.prepare("grok_app", value)
    assert queued["state"] == State.QUEUED
    assert "input_buffer" not in queued
    await voices.tasks.start()
    try:
        assert (await voices.tasks.wait("grok_app", value.task_id, 5))["state"] == State.COMPLETED
        assert calls[0][5] == "Diktat"
        assert voices.prepare("grok_app", value)["state"] == State.COMPLETED
        assert len(calls) == 1
    finally:
        await voices.tasks.stop()
    other = voices.prepare(
        "grok_app", request("file.list", {"path": policy.roots[0]}, task_id="ask")
    )
    assert other["state"] == State.CREATED


def test_terminal_session_input_is_outside_voice_buffer_policy(voices, config):
    config.session_input_policy.enabled = True
    for sender in ["codex", "grok"]:
        queued = voices.prepare(
            sender,
            request(
                "session.input",
                {
                    "pane_id": "%1",
                    "expected_pid": 1,
                    "text": "hello",
                },
                task_id=sender,
            ),
        )
        assert queued["state"] == State.QUEUED
        assert "input_buffer" not in queued


def test_team_messages_cannot_bypass_voice_outbox_and_voice_pair_uses_private_log(voices, config):
    from kirabridge.bridge_core.config import TeamConfig, TeamWorkerConfig
    from kirabridge.team_manager.models import TeamCreate, TeamMessageSend

    names = ["grok_app", "chatgpt", "codex", "local"]
    config.team = TeamConfig(enabled=True, workers={name: TeamWorkerConfig() for name in names})
    for name in names:
        config.principals[name].capabilities += ["team.manage", "team.read", "team.write"]
    teams = voices.teams
    teams.create(
        "local",
        TeamCreate(
            team_id="voice-team",
            name="Voice team",
            coordinator="local",
            members={name: "worker" for name in names if name != "local"},
            idempotency_key="create",
        ),
    )
    value = TeamMessageSend(
        team_id="voice-team", recipient="codex", body="Diktat", idempotency_key="team-dictation"
    )
    held = teams.send("grok_app", value)
    assert held["message_buffer"]["state"] == "waiting"
    assert not teams.messages("codex", "voice-team")["messages"]
    sent = voices.messages.voice_policy.release("grok_app", held["id"], "go-go-go")
    assert sent["body"] == "Diktat"
    assert teams.send("grok_app", value)["id"] == sent["id"]
    assert voices.messages.get("grok_app", held["id"])["id"] == sent["id"]
    marked = value.model_copy(update={"body": "Noch eins go-go-go", "idempotency_key": "marked"})
    assert teams.send("grok_app", marked)["body"] == "Noch eins"
    assert teams.send("grok_app", marked)["body"] == "Noch eins"
    pair = value.model_copy(
        update={"recipient": "chatgpt", "body": "Privat go-go-go", "idempotency_key": "private"}
    )
    private = teams.send("grok_app", pair)
    assert private["conversation_id"] == "eve-kira-shared"
    assert len(teams.messages("codex", "voice-team")["messages"]) == 2
    with pytest.raises(BridgeError):
        voices.messages.get("codex", private["id"])


def test_failed_release_rolls_back_archive_and_keeps_original_waiting_buffer(voices, config):
    held = voices.messages.send("grok_app", message())
    config.principals["codex"].message_peers = []
    with pytest.raises(BridgeError):
        voices.messages.voice_policy.release("grok_app", held["id"], "go-go-go")
    assert voices.messages.get("grok_app", held["id"])["message_buffer"]["state"] == "waiting"
    assert voices.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    config.principals["codex"].message_peers = ["grok_app"]
    assert (
        voices.messages.voice_policy.release("grok_app", held["id"], "go-go-go")["body"]
        == "Daniels Diktat"
    )
