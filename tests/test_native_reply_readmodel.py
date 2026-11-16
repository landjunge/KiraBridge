"""Authenticated late replies enrich native delivery reads without replay or writes."""

# Imported fixtures use isolated stores and a fake native protocol, never a host/TTY.
# ruff: noqa: F811
import json

import pytest
from conftest import request as task_request
from test_direct_delivery import delivery, new_message, settled  # noqa: F401
from test_native_codex_delivery import Protocol, binding  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.message_manager import MessageSend


@pytest.fixture
async def native_job(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    protocol = Protocol(binding)
    direct.codex_host = protocol.host()
    bridge.config.visible_handoffs.native_codex = binding
    sent = new_message(bridge, key="native-reply", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "completed"
    return bridge, transport, protocol, sent


def answer(bridge, sent, *, kind="answer", key="native-answer"):
    request = MessageSend(
        recipient="chatgpt", conversation_id=sent["conversation_id"],
        reply_to=sent["id"], idempotency_key=key, kind=kind,
        body="An authenticated mailbox answer", request_reply=False, dispatch=False,
    )
    return bridge.messages.send("codex", request), request


def ack(bridge, sent):
    received = bridge.messages.receive("codex")["messages"][0]
    assert received["id"] == sent["id"]
    return bridge.messages.ack("codex", sent["id"], received["receipt"])


@pytest.mark.parametrize("kind", ["answer", "result"])
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_native_late_auth_reply_is_visible_without_claiming_turn_completion(
    native_job, kind, acknowledged,
):
    bridge, transport, protocol, sent = native_job
    if acknowledged:
        ack(bridge, sent)
    reply, request = answer(bridge, sent, kind=kind)
    # Idempotent sends keep the first reply; the getter must not create one.
    assert bridge.messages.send("codex", request)["id"] == reply["id"]
    changes = bridge.store.db.total_changes
    job_before = dict(bridge.store.db.execute(
        "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],),
    ).fetchone())
    for _ in range(2):
        current = bridge.messages.get("chatgpt", sent["id"])
        processing = current["processing"]
        assert processing["reply_id"] == reply["id"]
        assert processing["request_reply_satisfied"] is True
        assert processing["reply_source"] == "authenticated_bridge_mailbox"
        assert processing["evidence"]["reply_id"] == reply["id"]
        assert processing["evidence"]["request_reply_satisfied"] is True
        assert processing["completion_scope"] == "native_input_delivery"
        assert processing["state"] == "completed"
        assert processing["agent_confirmed"] is False
        assert processing["agent_work_completion_verified"] is False
        assert processing["evidence"]["agent_confirmed"] is False
        assert processing["evidence"]["agent_work_completion_verified"] is False
        assert bool(current["acknowledged"]) is acknowledged
        assert current["receipt"] is None or acknowledged
    assert bridge.store.db.total_changes == changes
    assert dict(bridge.store.db.execute(
        "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],),
    ).fetchone()) == job_before
    initial_notice = json.loads(bridge.store.db.execute(
        "SELECT payload FROM completion_notices WHERE source='message' AND source_id=?",
        (sent["id"],),
    ).fetchone()[0])
    assert initial_notice["completion_scope"] == "native_input_delivery"
    assert initial_notice["request_reply_satisfied"] is False
    assert len(protocol.inputs()) == 1 and not transport["calls"]


async def test_ack_alone_never_satisfies_a_native_reply_request(native_job):
    bridge, transport, protocol, sent = native_job
    ack(bridge, sent)
    current = bridge.messages.get("chatgpt", sent["id"])
    assert current["acknowledged"] is not None
    assert current["processing"]["reply_id"] is None
    assert current["processing"]["request_reply_satisfied"] is False
    assert not current["processing"]["agent_confirmed"]
    assert len(protocol.inputs()) == 1 and not transport["calls"]


@pytest.mark.parametrize("field,value", [
    ("sender", "grok"), ("recipient", "grok_app"), ("kind", "note"),
    ("kind", "question"), ("request_reply", 1), ("conversation_id", "unrelated"),
    ("reply_to", "unrelated"), ("depth", 9),
])
async def test_unrelated_or_malformed_stored_reply_does_not_satisfy_native_request(
    native_job, field, value,
):
    bridge, _, _, sent = native_job
    ack(bridge, sent)
    reply, _ = answer(bridge, sent)
    unrelated = bridge.messages.send("chatgpt", MessageSend(
        recipient="codex", conversation_id="unrelated", idempotency_key="other-note",
        kind="note", body="Unrelated note", request_reply=False, dispatch=False,
    ))
    if field == "reply_to":
        value = unrelated["id"]
    bridge.store.db.execute("UPDATE messages SET " + field + "=? WHERE id=?", (value, reply["id"]))
    changes = bridge.store.db.total_changes
    current = bridge.messages.get("chatgpt", sent["id"])
    assert current["processing"]["reply_id"] is None
    assert current["processing"]["request_reply_satisfied"] is False
    assert bridge.store.db.total_changes == changes


@pytest.mark.parametrize(
    "state", ["failed", "unknown", "blocked", "cancelled", "running", "queued"],
)
async def test_reply_never_relabels_noncompleted_native_history(native_job, state):
    bridge, _, _, sent = native_job
    answer(bridge, sent)
    bridge.store.db.execute(
        "UPDATE message_jobs SET state=? WHERE message_id=?", (state, sent["id"]),
    )
    changes = bridge.store.db.total_changes
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["state"] == state and current["reply_id"] is None
    assert current["request_reply_satisfied"] is False
    assert bridge.store.db.total_changes == changes


async def test_first_valid_final_reply_wins_over_notes_and_later_answers(native_job):
    bridge, _, _, sent = native_job
    answer(bridge, sent, kind="note", key="note-first")
    first, _ = answer(bridge, sent, kind="result", key="first-final")
    answer(bridge, sent, key="later-final")
    observed = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert observed["reply_id"] == first["id"]


async def test_a_reply_with_another_task_reference_is_not_correlated(native_job):
    bridge, _, _, sent = native_job
    reply, _ = answer(bridge, sent)
    task = task_request(task_id="unrelated-task", arguments={
        "path": bridge.config.principals["chatgpt"].roots[0],
    })
    bridge.prepare("chatgpt", task)  # Persist a task reference without executing it.
    bridge.store.db.execute("UPDATE messages SET task_id=? WHERE id=?", (task.task_id, reply["id"]))
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["reply_id"] is None and current["request_reply_satisfied"] is False


async def test_an_existing_error_never_becomes_a_satisfied_reply(native_job):
    bridge, _, _, sent = native_job
    answer(bridge, sent)
    bridge.store.db.execute(
        "UPDATE message_jobs SET error='original_error' WHERE message_id=?", (sent["id"],),
    )
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["error"] == "original_error"
    assert current["reply_id"] is None and current["request_reply_satisfied"] is False


async def test_an_unrequested_answer_is_visible_without_inventing_a_reply_request(native_job):
    bridge, _, _, sent = native_job
    reply, _ = answer(bridge, sent)
    bridge.store.db.execute("UPDATE messages SET request_reply=0 WHERE id=?", (sent["id"],))
    current = bridge.messages.get("chatgpt", sent["id"])
    assert current["request_reply"] is False
    assert current["processing"]["reply_id"] == reply["id"]
    assert current["processing"]["request_reply_satisfied"] is False


@pytest.mark.parametrize("scope", ["visible_input_delivery", "managed_agent_turn"])
async def test_other_reply_paths_keep_their_existing_readmodel(native_job, scope):
    bridge, _, _, sent = native_job
    answer(bridge, sent)
    row = bridge.store.db.execute(
        "SELECT evidence FROM message_jobs WHERE message_id=?", (sent["id"],),
    ).fetchone()
    evidence = json.loads(row["evidence"])
    evidence["completion_scope"] = scope
    bridge.store.db.execute(
        "UPDATE message_jobs SET evidence=? WHERE message_id=?", (json.dumps(evidence), sent["id"]),
    )
    current = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert current["reply_id"] is None
    assert not current.get("request_reply_satisfied")
    assert "reply_source" not in current
