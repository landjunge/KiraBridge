"""Review tw-247423d5: owner handoff during adapter + atomic ACK contract."""

import asyncio
import json

import pytest

from kirabridge.bridge_core.models import BridgeError
from tests.test_claim_revalidation_contract import FIELDS, mutate
from tests.test_managed_guidance_context import Harness, channel, send  # noqa: F401

OTHER = "channel-other-owner"


def job(b, mid):
    return b.store.db.execute(
        "SELECT m.acknowledged,j.state,j.run_id,j.error,j.evidence,j.started "
        "FROM messages m JOIN message_jobs j ON j.message_id=m.id WHERE m.id=?",
        (mid,),
    ).fetchone()


def handoff(b, mid):
    """New owner takes the running job with its own evidence."""
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE message_jobs SET run_id=?,evidence=? WHERE message_id=?",
            (OTHER, json.dumps({"owner": "new"}), mid),
        )


@pytest.mark.parametrize("ending", ["agent_timeout", "cancelled"])
async def test_old_run_failure_after_handoff_keeps_foreign_job(channel, ending):
    b, cfg, h = channel
    work = send(b, "own-" + ending, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])

    async def execute(task, args, policy, running, progress, **kw):
        await running({"session_id": "old"})
        handoff(b, work["id"])
        # Existing contract: a lost claim's callback is rejected, never written.
        with pytest.raises(BridgeError) as lost:
            await progress({"late_progress_from_old_owner": True})
        assert lost.value.code == "receiver_claim_changed"
        if ending == "cancelled":
            raise asyncio.CancelledError
        raise BridgeError("agent_timeout", "old run timed out")

    b.agents.execute = execute
    if ending == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await b.message_receiver._process(h, message, run_id)
    else:
        await b.message_receiver._process(h, message, run_id)
    row = job(b, work["id"])
    assert (row["state"], row["run_id"], row["error"]) == ("running", OTHER, None)
    assert json.loads(row["evidence"]) == {"owner": "new"}
    assert row["acknowledged"] is None


async def test_running_marker_skipped_after_handoff(channel):
    b, cfg, h = channel
    work = send(b, "own-running", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])

    async def execute(task, args, policy, running, progress, **kw):
        handoff(b, work["id"])
        await running({"session_id": "old"})
        raise BridgeError("agent_timeout", "old run timed out")

    b.agents.execute = execute
    await b.message_receiver._process(h, message, run_id)
    row = job(b, work["id"])
    assert row["started"] is None and row["run_id"] == OTHER
    assert json.loads(row["evidence"]) == {"owner": "new"}


@pytest.mark.parametrize("field", FIELDS)
async def test_change_between_revalidation_and_ack_write_blocks_ack(channel, field):
    b, cfg, h = channel
    work = send(b, "ackwin-" + field, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original_call = h.call

    async def call(server, tool, args):  # change lands inside the async ACK call
        if tool == "message_ack":
            mutate(b, work["id"], field)
        return await original_call(server, tool, args)

    h.call = call
    await b.message_receiver._process(h, message, run_id)
    row = job(b, work["id"])
    assert row["acknowledged"] is None  # ACK write refused atomically
    if field == "status_unknown":
        assert row["state"] == "unknown" and row["error"] is None
    elif field == "run_id":
        assert (row["state"], row["run_id"]) == ("running", OTHER)
    else:
        assert (row["state"], row["error"]) == ("unknown", "claim_changed")


def test_ack_without_claim_unchanged_and_bad_claim_rejected(channel):
    b, cfg, h = channel
    work = send(b, "plain", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    got = b.messages.receive("codex_channel")["messages"]
    receipt = next(m["receipt"] for m in got if m["id"] == work["id"])
    with pytest.raises(BridgeError) as err:
        b.messages.ack("codex_channel", work["id"], receipt, {"run_id": run_id})
    assert err.value.code == "invalid_claim"
    good = b.message_receiver._claim_contract(message, run_id)
    assert b.messages.ack("codex_channel", work["id"], receipt, good)["acknowledged"]
