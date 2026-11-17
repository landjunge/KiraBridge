"""Review tw-a52c5608: pinned guidance source changes inside the async ACK call."""

import pytest

from tests.test_claim_owner_and_ack_window import job
from tests.test_managed_guidance_context import Harness, channel, processed_note, send  # noqa: F401


@pytest.mark.parametrize("change", ["hold", "source_body", "source_state"])
async def test_pinned_source_change_between_validation_and_ack_blocks_ack(channel, change):
    b, cfg, h = channel
    note = await processed_note(channel)
    work = send(b, "ack-src-" + change, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    pinned = job(b, work["id"])["evidence"]
    assert note["id"] in pinned  # the claim really pins this guidance source
    original_call = h.call

    async def call(server, tool, args):  # lands after validate_context, before ACK write
        if tool == "message_ack":
            if change == "hold":
                b.queues._place_hold("chatgpt", "messages", note["id"], "hold during ACK")
            elif change == "source_body":
                b.store.db.execute("UPDATE messages SET body='changed' WHERE id=?", (note["id"],))
            else:
                b.store.db.execute(
                    "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (note["id"],)
                )
        return await original_call(server, tool, args)

    h.call = call
    await b.message_receiver._process(h, message, run_id)
    row = job(b, work["id"])
    assert row["acknowledged"] is None  # ACK refused atomically
    assert row["state"] != "completed"


async def test_ack_with_pinned_context_requires_matching_context_digest(channel):
    from kirabridge.bridge_core.models import BridgeError

    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "ack-src-digest", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    got = b.messages.receive("codex_channel")["messages"]
    receipt = next(m["receipt"] for m in got if m["id"] == work["id"])
    bare = b.message_receiver._claim_contract(message, run_id)  # omits context_sha256
    with pytest.raises(BridgeError) as err:
        b.messages.ack("codex_channel", work["id"], receipt, bare)
    assert err.value.code == "claim_changed"
    assert b.messages.get("chatgpt", work["id"])["acknowledged"] is None
