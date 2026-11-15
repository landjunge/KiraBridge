"""Post-claim mutations use private fixture stores and a recording fake adapter."""

import asyncio
import json

import pytest
from test_managed_guidance_context import channel as context_channel
from test_managed_guidance_context import processed_note, send


@pytest.fixture
def channel(bridge, config):
    return context_channel.__wrapped__(bridge, config)


def job(bridge, message_id):
    return dict(
        bridge.store.db.execute(
            "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()
    )


def mutate(bridge, work, changed):
    if changed == "body":
        bridge.store.db.execute(
            "UPDATE messages SET body='Changed after claim' WHERE id=?", (work["id"],)
        )  # Deliberately leave the old request_hash untouched.
    elif changed == "request_reply":
        bridge.store.db.execute("UPDATE messages SET request_reply=0 WHERE id=?", (work["id"],))
    elif changed == "unknown":
        bridge.store.db.execute(
            "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (work["id"],)
        )
    elif changed == "run_id":
        bridge.store.db.execute(
            "UPDATE message_jobs SET run_id='other-owner' WHERE message_id=?", (work["id"],)
        )
    else:
        assert changed == "hold"
        bridge.queues._place_hold("chatgpt", "messages", work["id"], "Fresh current-work hold")
    return job(bridge, work["id"])


@pytest.mark.parametrize("changed", ["body", "request_reply", "unknown", "run_id", "hold"])
@pytest.mark.parametrize("phase", ["after_claim", "after_receipt", "after_adapter", "after_reply"])
async def test_current_work_changes_never_execute_or_ack_the_old_claim(channel, changed, phase):
    b, cfg, h = channel
    note = await processed_note(channel)
    original_note_job = job(b, note["id"])
    work = send(b, "current-" + changed + "-" + phase, "Original current work", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    proof = json.loads(job(b, work["id"])["evidence"])["managed_guidance_context"]
    calls, mutated_jobs = [], []
    original_call, original_execute = h.call, b.agents.execute

    def change():
        mutated_jobs.append(mutate(b, work, changed))

    async def call(server, tool, args):
        calls.append(tool)
        result = await original_call(server, tool, args)
        if (phase == "after_receipt" and tool == "message_receive") or (
            phase == "after_reply" and tool == "message_send"
        ):
            change()
        return result

    async def execute(*args, **kwargs):
        result = await original_execute(*args, **kwargs)
        if phase == "after_adapter":
            change()
        return result

    h.call, b.agents.execute = call, execute
    if phase == "after_claim":
        change()
    await b.message_receiver._process(h, message, run_id)
    actual = b.messages.get("chatgpt", work["id"])
    assert len(mutated_jobs) == 1
    assert len(h.turns) == (1 if phase in {"after_claim", "after_receipt"} else 2)
    assert "message_ack" not in calls and actual["acknowledged"] is None
    assert ("message_send" in calls) == (phase == "after_reply")
    assert actual["processing"]["state"] != "completed"
    if changed in {"unknown", "run_id"}:
        assert job(b, work["id"]) == mutated_jobs[0]  # Exact foreign/UNKNOWN job retained.
    else:
        assert actual["processing"]["state"] == (
            "failed" if phase in {"after_claim", "after_receipt"} else "unknown"
        )
        assert actual["processing"]["error"] == "guidance_context_changed"
        assert actual["processing"]["evidence"]["managed_guidance_context"] == proof
        if phase == "after_reply":
            reply = b.messages.get("chatgpt", actual["processing"]["reply_id"])
            assert reply["reply_to"] == work["id"]
    assert b.message_receiver._claim(work["id"]) is None  # No requeue or bare-work replay.
    assert b.messages.get("chatgpt", note["id"]) == note
    assert job(b, note["id"]) == original_note_job


@pytest.mark.parametrize("changed", ["unknown", "run_id"])
@pytest.mark.parametrize("callback", ["running", "progress", "cancel"])
async def test_lost_owner_progress_and_cancellation_preserve_the_exact_job(
    channel, changed, callback
):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "owner-" + changed + callback, "Current work", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    observations = []

    async def execute(task, args, policy, running, progress, **kwargs):
        if callback != "running":
            await running({"fixture_started": True})
        observations.append(mutate(b, work, changed))
        if callback == "cancel":
            raise asyncio.CancelledError()
        await (running if callback == "running" else progress)({"must_not_overwrite": True})
        pytest.fail("Lost claim callback was accepted")

    b.agents.execute = execute
    if callback == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await b.message_receiver._process(h, message, run_id)
    else:
        await b.message_receiver._process(h, message, run_id)
    assert job(b, work["id"]) == observations[0]
    assert b.messages.get("chatgpt", work["id"])["acknowledged"] is None


@pytest.mark.parametrize(
    "changed", ["proof_removed", "proof_changed", "proof_malformed", "receipt", "kind", "depth"]
)
async def test_current_binding_cannot_disappear_into_raw_fallback(channel, changed):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "binding-" + changed, "Exact work", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original_call = h.call

    async def call(server, tool, args):
        result = await original_call(server, tool, args)
        if tool == "message_receive":
            if changed.startswith("proof_"):
                proof = json.loads(job(b, work["id"])["evidence"])
                if changed == "proof_removed":
                    proof.pop("managed_guidance_context")
                else:
                    proof["managed_guidance_context"]["prompt_sha256"] = "0" * 64
                b.store.db.execute(
                    "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                    ("{" if changed == "proof_malformed" else json.dumps(proof), work["id"]),
                )
            elif changed == "receipt":
                b.store.db.execute(
                    "UPDATE messages SET receipt='other-receipt' WHERE id=?", (work["id"],)
                )
            elif changed == "kind":
                b.store.db.execute("UPDATE messages SET kind='question' WHERE id=?", (work["id"],))
            else:
                b.store.db.execute("UPDATE messages SET depth=depth+1 WHERE id=?", (work["id"],))
        return result

    h.call = call
    await b.message_receiver._process(h, message, run_id)
    result = b.messages.get("chatgpt", work["id"])
    assert len(h.turns) == 1
    assert result["processing"]["state"] == "failed"
    assert result["processing"]["error"] == "guidance_context_changed"
    assert result["acknowledged"] is None


async def test_an_unmodified_current_work_with_no_reply_still_completes(channel):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "no-reply", "Current work does not ask for a reply", kind="work")
    b.store.db.execute("UPDATE messages SET request_reply=0 WHERE id=?", (work["id"],))
    message, run_id = b.message_receiver._claim(work["id"])
    await b.message_receiver._process(h, message, run_id)
    result = b.messages.get("chatgpt", work["id"])
    assert len(h.turns) == 2 and not h.turns[-1]["args"].wait_for_reply
    assert result["acknowledged"] is not None and result["processing"]["state"] == "completed"
    assert result["processing"]["reply_id"] is None
