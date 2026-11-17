"""Context contract: body/request_reply/status/run_id/hold changes block adapter and ACK."""

import pytest

from tests.test_managed_guidance_context import Harness, channel, processed_note, send  # noqa: F401


def mutate(b, message_id, what):
    db = b.store.db
    with b.store.transaction():
        if what == "body":
            db.execute("UPDATE messages SET body=body||' changed' WHERE id=?", (message_id,))
        elif what == "request_reply":
            db.execute("UPDATE messages SET request_reply=0 WHERE id=?", (message_id,))
        elif what == "status_unknown":
            db.execute("UPDATE message_jobs SET state='unknown' WHERE message_id=?", (message_id,))
        elif what == "run_id":
            db.execute(
                "UPDATE message_jobs SET run_id='channel-other-owner' WHERE message_id=?",
                (message_id,),
            )
        elif what == "hold":
            b.queues._place_hold("chatgpt", "messages", message_id, "operator_hold")
        else:
            raise AssertionError(what)


FIELDS = ["body", "request_reply", "status_unknown", "run_id", "hold"]


def assert_blocked(b, message_id, initial_state=None):
    row = b.store.db.execute(
        "SELECT m.acknowledged,m.body,j.state,j.error,j.run_id FROM messages m "
        "JOIN message_jobs j ON j.message_id=m.id WHERE m.id=?",
        (message_id,),
    ).fetchone()
    assert row["acknowledged"] is None  # never ACKed
    replies = b.store.db.execute(
        "SELECT count(*) FROM messages WHERE reply_to=?", (message_id,)
    ).fetchone()[0]
    assert replies == 0
    audit = b.store.db.execute(
        "SELECT count(*) FROM audit WHERE kind='message.claim_revalidation_failed'"
    ).fetchone()[0]
    assert audit == 1
    return row


@pytest.mark.parametrize("with_context", [True, False])
@pytest.mark.parametrize("field", FIELDS)
async def test_change_before_adapter_blocks_model_and_ack(channel, field, with_context):
    b, cfg, h = channel
    if with_context:
        await processed_note(channel)
    turns = len(h.turns)
    work = send(b, "w-" + field, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original_receive = h.call

    async def call(server, tool, args):  # change lands after delivery, before the adapter
        result = await original_receive(server, tool, args)
        if tool == "message_receive":
            mutate(b, work["id"], field)
        return result

    h.call = call
    await b.message_receiver._process(h, message, run_id)
    assert len(h.turns) == turns  # adapter never started
    row = assert_blocked(b, work["id"])
    if field in {"status_unknown", "run_id"}:
        assert row["error"] is None  # foreign owner/state history untouched
    else:
        # Managed scope keeps its existing error code (guidance_context_changed).
        expected = "guidance_context_changed" if with_context else "claim_changed"
        assert (row["state"], row["error"]) == ("failed", expected)


@pytest.mark.parametrize("field", FIELDS)
async def test_change_during_adapter_blocks_reply_and_ack(channel, field):
    b, cfg, h = channel
    work = send(b, "d-" + field, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original = h.execute

    async def execute(task, args, policy, running, progress, **kw):
        result = await original(task, args, policy, running, progress, **kw)
        mutate(b, work["id"], field)
        return result

    b.agents.execute = execute
    await b.message_receiver._process(h, message, run_id)
    assert len(h.turns) == 1
    row = assert_blocked(b, work["id"])
    if field == "status_unknown":
        assert row["state"] == "unknown" and row["error"] is None
    elif field == "run_id":
        assert row["state"] == "running" and row["run_id"] == "channel-other-owner"
    else:
        # The turn may have run: UNKNOWN, never failed/completed, no replay.
        assert (row["state"], row["error"]) == ("unknown", "claim_changed")
    assert not b.message_receiver._queue_unsent(work["id"], "claim_changed", run_id, "running")


async def test_change_after_ack_cannot_be_completed_by_previous_owner(channel):
    b, cfg, h = channel
    work = send(b, "handoff", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original_call = h.call

    async def call(server, tool, args):
        result = await original_call(server, tool, args)
        if tool == "message_ack":
            mutate(b, work["id"], "run_id")  # owner handed off concurrently with ACK
        return result

    h.call = call
    await b.message_receiver._process(h, message, run_id)
    row = b.store.db.execute(
        "SELECT state,run_id FROM message_jobs WHERE message_id=?", (work["id"],)
    ).fetchone()
    assert (row["state"], row["run_id"]) == ("running", "channel-other-owner")


async def test_unchanged_claim_still_completes(channel):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "ok", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    await b.message_receiver._process(h, message, run_id)
    result = b.messages.get("chatgpt", work["id"])
    assert result["processing"]["state"] == "completed" and result["acknowledged"]
