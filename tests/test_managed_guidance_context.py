"""Cross-turn context keeps originals and ownership, without provider calls."""

import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, ReceiverConfig
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.message_manager.guidance import consume, ready
from kirabridge.message_manager.guidance_context import MAX_PROMPT_BYTES, prepare, render_pinned


class Harness:
    def __init__(self, bridge):
        self.bridge = bridge
        self.turns = []
        bridge.agents.execute = self.execute

    async def call(self, server, tool, args):
        assert server == "daemon"
        m = self.bridge.messages
        if tool == "message_receive":
            result = m.receive("codex_channel", **args)
        elif tool == "message_ack":
            result = m.ack("codex_channel", args["message_id"], args["receipt"])
        elif tool == "message_send":
            result = m.send("codex_channel", MessageSend.model_validate(args["message"]))
        else:
            raise AssertionError(tool)
        return SimpleNamespace(isError=False, structuredContent=result)

    async def execute(self, task, args, policy, running, progress, **kw):
        assert kw["separate_managed"] and args.resume_session is None
        self.turns.append({"task": task, "args": args})
        await running({"session_id": "fixture-session-" + str(len(self.turns))})
        await progress({"fixture_progress": True})
        return {
            "success": True,
            "text": "MODEL SUMMARY IS NEVER ORIGINAL CONTEXT",
            "evidence": {"turn_completed": True},
        }


@pytest.fixture
def channel(bridge, config):
    config.messaging.separate_managed_after = time.time() - 60
    for name, peers in {
        "chatgpt": ["codex_channel"],
        "other_sender": ["codex_channel"],
        "codex_channel": ["chatgpt", "other_sender"],
    }.items():
        p = config.principals["local"].model_copy(deep=True)
        p.capabilities += ["message.send", "message.read", "message.ack", "agent.execute"]
        p.approval_mode = "automatic"
        p.message_peers = peers
        p.agents = ["codex_channel"]
        config.principals[name] = p
    config.agents["codex_channel"] = AgentConfig(kind="codex", executable="/usr/bin/true")
    config.messaging.receivers["codex_channel"] = ReceiverConfig(
        cwd=config.principals["local"].roots[0], timeout=5
    )
    return bridge, config, Harness(bridge)


def send(b, key, body, *, kind="note", conversation="guidance", sender="chatgpt"):
    return b.messages.send(
        sender,
        MessageSend(
            recipient="codex_channel",
            conversation_id=conversation,
            idempotency_key=key,
            body=body,
            kind=kind,
            dispatch=kind == "work",
            request_reply=kind == "work",
        ),
    )


async def processed_note(channel, key="note", body="  Original Priorität ä🙂\nKeep exact.  ", **kw):
    b, cfg, h = channel
    note = send(b, key, body, **kw)
    assert await consume(b.message_receiver, "codex_channel", h)
    return b.messages.get(kw.get("sender", "chatgpt"), note["id"])


async def run_work(b, h, key, body="Current task overrides prior preferences.", **kw):
    work = send(b, key, body, kind="work", **kw)
    message, run_id = b.message_receiver._claim(work["id"])
    initial = b.messages.get(kw.get("sender", "chatgpt"), work["id"])
    await b.message_receiver._process(h, message, run_id)
    return initial, b.messages.get(kw.get("sender", "chatgpt"), work["id"])


async def test_two_new_work_turns_get_originals_with_pinned_provenance_and_current_task(channel):
    b, cfg, h = channel
    note = await processed_note(channel)
    originals = b.store.db.execute("SELECT count(*) FROM messages").fetchone()[0]
    scopes = []
    for n in range(2):
        body = f"Current task {n}, no extra task.\nExact ä🙂"
        initial, result = await run_work(b, h, f"work-{n}", body)
        prompt = h.turns[-1]["args"].prompt
        payload = json.loads(prompt)
        assert payload["current_work"] == {"message_id": result["id"], "body": body}
        assert [s["body"] for s in payload["prior_guidance"]] == [note["body"]]
        assert "MODEL SUMMARY" not in prompt
        assert "take precedence" in payload["instruction"]
        proof = initial["processing"]["evidence"]["managed_guidance_context"]
        assert proof == result["processing"]["evidence"]["managed_guidance_context"]
        assert proof["sources"][0]["message_id"] == note["id"]
        assert (
            proof["sources"][0]["body_sha256"] == hashlib.sha256(note["body"].encode()).hexdigest()
        )
        assert proof["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        assert result["body"] == body and result["processing"]["state"] == "completed"
        assert result["acknowledged"] and result["processing"]["reply_id"]
        scopes.append(h.turns[-1]["task"]["id"])
    assert scopes[0] != scopes[1]  # two fresh owned attempts, no provider-session reuse
    assert len(h.turns) == 3
    assert b.messages.get("chatgpt", note["id"])["body"] == note["body"]
    assert not await consume(b.message_receiver, "codex_channel", h)
    assert b.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == originals + 4


async def test_completed_original_context_survives_cold_store_reopen_for_new_work(channel):
    b, cfg, h = channel
    note = await processed_note(channel)
    old_instance = b.runtime["instance_id"]
    b.store.close()
    reopened = Bridge(cfg)
    h2 = Harness(reopened)
    try:
        assert reopened.runtime["instance_id"] != old_instance
        _, result = await run_work(reopened, h2, "after-restart")
        source = result["processing"]["evidence"]["managed_guidance_context"]["sources"][0]
        assert source["message_id"] == note["id"]
        assert json.loads(h2.turns[0]["args"].prompt)["prior_guidance"][0]["body"] == note["body"]
        assert len(h2.turns) == 1
    finally:
        reopened.store.close()


@pytest.mark.parametrize(
    "excluded", ["unknown", "hold", "cwd", "cutoff", "unacked", "plain_completion"]
)
async def test_untrusted_or_out_of_scope_completed_records_are_not_context(channel, excluded):
    b, cfg, h = channel
    note = await processed_note(channel)
    if excluded == "unknown":
        b.store.db.execute(
            "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (note["id"],)
        )
    elif excluded == "hold":
        b.queues._place_hold("chatgpt", "messages", note["id"], "test hold")
    elif excluded == "cwd":
        b.store.db.execute(
            "UPDATE message_jobs SET execution_cwd='/different-cwd' WHERE message_id=?",
            (note["id"],),
        )
    elif excluded == "cutoff":
        cfg.messaging.separate_managed_after = time.time()
    elif excluded == "unacked":
        b.store.db.execute("UPDATE messages SET acknowledged=NULL WHERE id=?", (note["id"],))
    else:
        b.store.db.execute(
            "UPDATE message_jobs SET evidence='{}' WHERE message_id=?", (note["id"],)
        )
    _, result = await run_work(b, h, "without-prior")
    assert h.turns[-1]["args"].prompt == result["body"]
    assert "managed_guidance_context" not in result["processing"]["evidence"]


@pytest.mark.parametrize("scope", ["sender", "conversation", "receiver"])
async def test_scope_does_not_cross_authenticated_sender_conversation_or_receiver(channel, scope):
    b, cfg, h = channel
    await processed_note(channel)
    if scope == "sender":
        with pytest.raises(BridgeError, match="Conversation not found"):
            send(b, "foreign-sender", "Other sender", kind="work", sender="other_sender")
        own_work = send(b, "own-work", "Current task", kind="work")
        assert prepare(b, {**own_work, "sender": "other_sender"}) is None
    elif scope == "receiver":
        work = send(b, "other-receiver", "Other receiver", kind="work")
        # A different configured recipient cannot reuse this recipient's context.
        other = {**work, "recipient": "other_sender"}
        cfg.messaging.receivers["other_sender"] = cfg.messaging.receivers["codex_channel"]
        assert prepare(b, other) is None
    else:
        _, result = await run_work(b, h, "other-scope", conversation="other")
        assert h.turns[-1]["args"].prompt == result["body"]


@pytest.mark.parametrize("changed", ["body", "hold", "state", "cwd", "peer", "authority"])
async def test_scope_change_after_claim_fails_before_model_without_refresh_or_false_ack(
    channel, changed
):
    b, cfg, h = channel
    note = await processed_note(channel)
    work = send(b, "pinned", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    proof = b.messages.get("chatgpt", work["id"])["processing"]["evidence"][
        "managed_guidance_context"
    ]
    if changed == "body":
        b.store.db.execute("UPDATE messages SET body='changed' WHERE id=?", (note["id"],))
    elif changed == "hold":
        b.queues._place_hold("chatgpt", "messages", note["id"], "hold after claim")
    elif changed == "state":
        b.store.db.execute(
            "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (note["id"],)
        )
    elif changed == "cwd":
        cfg.messaging.receivers["codex_channel"].cwd = "/different-cwd"
    elif changed == "peer":
        cfg.principals["codex_channel"].message_peers = []
    else:
        b.runtime["instance_id"] = "different-loaded-runtime"
    await b.message_receiver._process(h, message, run_id)
    result = b.messages.get("chatgpt", work["id"])
    assert len(h.turns) == 1
    assert result["acknowledged"] is None
    assert result["processing"]["state"] == "failed"
    assert result["processing"]["error"] == "guidance_context_changed"
    assert result["processing"]["evidence"]["managed_guidance_context"] == proof


async def test_late_completed_note_is_not_silently_added_to_an_existing_claim(channel):
    b, cfg, h = channel
    first = await processed_note(channel)
    work = send(b, "pinned-before-update", "Current work", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    later = send(b, "late", "Later context is not part of the existing claim")
    # Simulate a durable completed record appearing after the claim snapshot.
    delivered = b.messages.receive("codex_channel", after=later["seq"] - 1)["messages"][0]
    b.messages.ack("codex_channel", later["id"], delivered["receipt"])
    ev = {
        "guidance_batch": 1,
        "model_turn_completed": True,
        "scope": "managed_guidance_context_only",
        "run_id": "fixture-late",
        "message_ids": [later["id"]],
    }
    b.store.db.execute(
        "INSERT INTO message_jobs(message_id,state,run_id,execution_cwd,evidence) "
        "VALUES(?,'completed','fixture-late',?,?)",
        (later["id"], cfg.messaging.receivers["codex_channel"].cwd, canonical(ev)),
    )
    await b.message_receiver._process(h, message, run_id)
    actual = json.loads(h.turns[-1]["args"].prompt)["prior_guidance"]
    assert [source["message_id"] for source in actual] == [first["id"]]


async def test_envelope_bound_is_applied_before_claim_without_truncating_current_or_notes(channel):
    b, cfg, h = channel
    cfg.messaging.max_body_bytes = 65536
    notes = [send(b, f"large-{i}", str(i) + "x" * 65535) for i in range(8)]
    while ready(b.message_receiver, "codex_channel"):
        assert await consume(b.message_receiver, "codex_channel", h)
    body = "w" * 65536
    initial, result = await run_work(b, h, "large-current", body)
    proof = initial["processing"]["evidence"]["managed_guidance_context"]
    prompt = h.turns[-1]["args"].prompt
    payload = json.loads(prompt)
    assert proof["prompt_bytes"] == len(prompt.encode()) <= MAX_PROMPT_BYTES
    assert [source["message_id"] for source in payload["prior_guidance"]] == [
        n["id"] for n in notes[-2:]
    ]
    assert all(len(source["body"]) == 65536 for source in payload["prior_guidance"])
    assert proof["omitted_count"] == 6
    assert payload["current_work"]["body"] == result["body"] == body
    assert result["processing"]["state"] == "completed"


async def test_json_expansion_keeps_valid_current_body_and_records_context_omission(channel):
    b, cfg, h = channel
    cfg.messaging.max_body_bytes = 65536
    await processed_note(channel)
    body = "\x01" * 65536
    initial, result = await run_work(b, h, "escaped-current", body)
    proof = initial["processing"]["evidence"]["managed_guidance_context"]
    assert proof["prompt_format"] == "body_only_budget_omission"
    assert proof["sources"] == [] and proof["omitted_count"] == 1
    assert h.turns[-1]["args"].prompt == result["body"] == body
    assert result["processing"]["state"] == "completed"


async def test_pinned_context_cannot_be_reused_by_another_store(channel, tmp_path):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "same-key", "Same body", kind="work")
    message, _ = b.message_receiver._claim(work["id"])
    proof = b.messages.get("chatgpt", work["id"])["processing"]["evidence"][
        "managed_guidance_context"
    ]
    other_cfg = cfg.model_copy(deep=True)
    other_cfg.data_dir = str(tmp_path / "other-store")
    other = Bridge(other_cfg)
    try:
        with pytest.raises(BridgeError, match="Pinned managed guidance"):
            render_pinned(other, message, proof)
    finally:
        other.store.close()


async def test_claimed_work_restart_preserves_context_proof_and_never_replays(channel):
    b, cfg, h = channel
    note = await processed_note(channel)
    work = send(b, "interrupted-work", "Current work", kind="work")
    b.message_receiver._claim(work["id"])
    proof = b.messages.get("chatgpt", work["id"])["processing"]["evidence"][
        "managed_guidance_context"
    ]
    b.store.close()
    reopened = Bridge(cfg)
    h2 = Harness(reopened)
    try:
        await reopened.message_receiver.start()
        await reopened.message_receiver.stop()
        actual = reopened.messages.get("chatgpt", work["id"])
        assert actual["processing"]["state"] == "unknown"
        assert actual["processing"]["evidence"]["managed_guidance_context"] == proof
        assert actual["acknowledged"] is None
        assert reopened.message_receiver._claim(work["id"]) is None
        assert reopened.messages.get("chatgpt", note["id"])["acknowledged"]
        assert not h2.turns
    finally:
        reopened.store.close()


@pytest.mark.parametrize("disabled", ["no_cutoff", "before_cutoff", "question"])
async def test_unselected_receiver_routes_keep_their_existing_input_contract(channel, disabled):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "other-route", "Exact current body", kind="work")
    if disabled == "no_cutoff":
        cfg.messaging.separate_managed_after = None
    elif disabled == "before_cutoff":
        cfg.messaging.separate_managed_after = work["created"] + 1
    else:
        work["kind"] = "question"
    assert prepare(b, work) is None
