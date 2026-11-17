"""Claim seal: run_id/cwd/field binding, request_reply from seal, ABA fences."""

import json

import pytest

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from tests.test_managed_guidance_context import Harness, channel, processed_note, send  # noqa: F401


def job(b, message_id):
    return b.store.db.execute(
        "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
    ).fetchone()


@pytest.mark.parametrize("with_context", [True, False])
async def test_claim_stores_seal_bound_to_run_and_cwd(channel, with_context):
    b, cfg, h = channel
    if with_context:
        await processed_note(channel)
    work = send(b, "seal-store", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    stored = json.loads(job(b, work["id"])["evidence"])["claim_seal"]
    assert message["_claim_seal"] == stored
    assert stored["schema"] == "kirabridge.message-claim-seal.v1"
    assert stored["run_id"] == run_id
    assert stored["execution_cwd"] == job(b, work["id"])["execution_cwd"]
    assert (stored["context_sha256"] is not None) == with_context
    b.message_receiver.verify_seal(
        message, run_id, stored, message.get("_managed_guidance_context")
    )


@pytest.mark.parametrize(
    "drift",
    ["evidence_seal", "cwd", "foreign_run_seal", "sender"],
)
def test_verify_seal_rejects_drift(channel, drift):
    b, cfg, h = channel
    work = send(b, "seal-" + drift, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    seal = dict(message["_claim_seal"])
    db = b.store.db
    with b.store.transaction():
        if drift == "evidence_seal":
            evidence = json.loads(job(b, work["id"])["evidence"])
            evidence["claim_seal"]["fields_sha256"] = "0" * 64
            db.execute(
                "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                (json.dumps(evidence), work["id"]),
            )
        elif drift == "cwd":
            db.execute(
                "UPDATE message_jobs SET execution_cwd='/elsewhere' WHERE message_id=?",
                (work["id"],),
            )
        elif drift == "foreign_run_seal":
            seal["run_id"] = "other-run"
        elif drift == "sender":
            db.execute("UPDATE messages SET sender='mallory' WHERE id=?", (work["id"],))
    with pytest.raises(BridgeError) as exc:
        b.message_receiver.verify_seal(message, run_id, seal)
    assert exc.value.code == "guidance_context_changed"
    reasons = [
        json.loads(r["metadata"])["reason"]
        for r in db.execute(
            "SELECT metadata FROM audit WHERE kind='message.claim_revalidation_failed'"
        )
    ]
    assert reasons == [
        {
            "evidence_seal": "seal_broken",
            "cwd": "receiver_scope_changed",
            "foreign_run_seal": "seal_missing",
            "sender": "seal_broken",
        }[drift]
    ]


async def test_adapter_wait_for_reply_comes_from_seal(channel):
    b, cfg, h = channel
    work = send(b, "seal-rr", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    assert message["_claim_seal"]["request_reply"] is bool(message["request_reply"])
    await b.message_receiver._process(h, message, run_id)
    assert [t["args"].wait_for_reply for t in h.turns] == [
        message["_claim_seal"]["request_reply"]
    ]


async def test_in_memory_request_reply_drift_never_reaches_adapter(channel):
    b, cfg, h = channel
    work = send(b, "seal-rr-drift", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    message = {**message, "request_reply": 0 if message["request_reply"] else 1}
    await b.message_receiver._process(h, message, run_id)
    assert h.turns == []
    row = job(b, work["id"])
    assert row["state"] == "failed" and row["started"] is None
    acked = b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0]
    assert acked is None


def test_record_finish_is_compare_and_set_on_run_id(channel):
    b, cfg, h = channel
    work = send(b, "seal-cas", "Current task", kind="work")
    _, run_id = b.message_receiver._claim(work["id"])
    observed = job(b, work["id"])
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE message_jobs SET run_id='channel-new-owner' WHERE message_id=?",
            (work["id"],),
        )
    with pytest.raises(BridgeError) as exc, b.store.transaction():
        b.message_receiver._record_finish(observed, "completed", {})
    assert exc.value.code == "receiver_claim_changed"
    row = job(b, work["id"])
    assert (row["state"], row["run_id"], row["finished"]) == (
        "running",
        "channel-new-owner",
        None,
    )


def test_queue_unsent_never_requeues_other_or_started_claim(channel):
    b, cfg, h = channel
    work = send(b, "seal-aba", "Current task", kind="work")
    _, run_id = b.message_receiver._claim(work["id"])
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE message_jobs SET started=1 WHERE message_id=?", (work["id"],)
        )
    assert not b.message_receiver._queue_unsent(work["id"], "x", run_id, "running")
    assert job(b, work["id"])["state"] == "running"
    assert not b.message_receiver._queue_unsent(work["id"], "x", "other-run", "running")
    assert job(b, work["id"])["run_id"] == run_id


DURING_ADAPTER = {
    "body": "UPDATE messages SET body='changed' WHERE id=?",
    "request_reply": "UPDATE messages SET request_reply=0 WHERE id=?",
    "kind": "UPDATE messages SET kind='note' WHERE id=?",
    "hold": "INSERT INTO queue_holds(queue_id,item_id,actor,created,reason) "
    "VALUES('messages',?,'local',1,'test')",
    "job_state": "UPDATE message_jobs SET state='unknown' WHERE message_id=?",
    "run_id": "UPDATE message_jobs SET run_id='channel-other' WHERE message_id=?",
}


@pytest.mark.parametrize("with_context", [True, False])
@pytest.mark.parametrize("drift", sorted(DURING_ADAPTER))
async def test_drift_during_adapter_blocks_reply_and_ack_without_replay(
    channel, drift, with_context
):
    b, cfg, h = channel
    if with_context:
        await processed_note(channel)
    turns = len(h.turns)
    work = send(b, "seal-during-" + drift, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    original = h.execute

    async def drifting(*args, **kw):
        result = await original(*args, **kw)
        with b.store.transaction():
            b.store.db.execute(DURING_ADAPTER[drift], (work["id"],))
        return result

    h.execute = b.agents.execute = drifting
    await b.message_receiver._process(h, message, run_id)
    assert len(h.turns) == turns + 1  # adapter ran exactly once, never replayed
    row = job(b, work["id"])
    acked = b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0]
    replies = b.store.db.execute(
        "SELECT count(*) FROM messages WHERE reply_to=?", (work["id"],)
    ).fetchone()[0]
    assert acked is None and replies == 0
    if drift in {"job_state", "run_id"}:
        # Lost claim: the foreign/UNKNOWN state is preserved untouched.
        assert row["state"] == ("unknown" if drift == "job_state" else "running")
        assert row["finished"] is None
    else:
        assert row["state"] == "unknown"
        assert row["error"] in {"guidance_context_changed", "claim_changed", "claim_seal_broken"}
    assert not b.message_receiver._queue_unsent(work["id"], "x", run_id, "running")


@pytest.mark.parametrize("drift", ["body", "kind", "hold"])
async def test_drift_before_adapter_fails_closed_without_model_turn(channel, drift):
    b, cfg, h = channel
    work = send(b, "seal-before-" + drift, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    with b.store.transaction():
        b.store.db.execute(DURING_ADAPTER[drift], (work["id"],))
    await b.message_receiver._process(h, message, run_id)
    assert h.turns == []
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0] is None
    assert job(b, work["id"])["started"] is None


async def test_unchanged_round_and_unrelated_note_keep_seal_valid(channel):
    b, cfg, h = channel
    work = send(b, "seal-ok", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    send(b, "seal-unrelated", "Unrelated note", conversation="elsewhere")
    await b.message_receiver._process(h, message, run_id)
    assert len(h.turns) == 1
    row = job(b, work["id"])
    assert row["state"] == "completed" and row["reply_id"]
    evidence = json.loads(row["evidence"])
    assert evidence["claim_seal"] == message["_claim_seal"]
    assert b.messages.get("chatgpt", work["id"])["acknowledged"]


async def test_seal_survives_cold_store_reopen_and_is_not_replayed(channel):
    b, cfg, h = channel
    work = send(b, "seal-reopen", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    seal = message["_claim_seal"]
    b.store.close()
    reopened = Bridge(cfg)
    h2 = Harness(reopened)
    try:
        await reopened.message_receiver.start()
        await reopened.message_receiver.stop()
        actual = reopened.messages.get("chatgpt", work["id"])
        assert actual["processing"]["state"] == "unknown"
        assert actual["processing"]["evidence"]["claim_seal"] == seal
        assert actual["acknowledged"] is None
        assert reopened.message_receiver._claim(work["id"]) is None
        assert not h2.turns
    finally:
        reopened.store.close()


def test_position_is_sealed(channel):
    b, cfg, h = channel
    work = send(b, "seal-position", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    assert "position" in b.message_receiver.SEAL_FIELDS
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE messages SET position=COALESCE(position,0)+1000 WHERE id=?", (work["id"],)
        )
    with pytest.raises(BridgeError) as exc:
        b.message_receiver.verify_seal(message, run_id, message["_claim_seal"])
    assert exc.value.code == "guidance_context_changed"


@pytest.mark.parametrize("damage", ["remove", "replace"])
async def test_progress_never_repairs_drifted_stored_seal(channel, damage):
    b, cfg, h = channel
    work = send(b, "seal-progress-" + damage, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    calls = []

    async def damaging(task, args, policy, running, progress, **kw):
        h.turns.append({"task": task, "args": args})
        await running({"session_id": "s"})
        with b.store.transaction():
            evidence = json.loads(job(b, work["id"])["evidence"])
            if damage == "remove":
                evidence.pop("claim_seal")
            else:
                evidence["claim_seal"] = {**evidence["claim_seal"], "fields_sha256": "0" * 64}
            b.store.db.execute(
                "UPDATE message_jobs SET evidence=? WHERE message_id=?",
                (json.dumps(evidence), work["id"]),
            )
        try:
            await progress({"after_damage": True})
        except BridgeError as exc:
            calls.append(exc.code)
            raise
        calls.append("written")
        return {"success": True, "text": "x", "evidence": {}}

    h.execute = b.agents.execute = damaging
    await b.message_receiver._process(h, message, run_id)
    assert calls == ["guidance_context_changed"]
    row = job(b, work["id"])
    assert row["state"] == "unknown" and row["reply_id"] is None
    evidence = json.loads(row["evidence"])
    # The stored (damaged) value is never overwritten with the process snapshot.
    assert evidence.get("claim_seal_mismatch") is True
    stored = evidence["last_observation"].get("claim_seal")
    assert stored != message["_claim_seal"]
    assert "after_damage" not in json.dumps(evidence)
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0] is None


@pytest.mark.parametrize("drift", ["hold", "body"])
async def test_interim_style_fence_blocks_return_after_awaits(channel, drift):
    """Adapter order of interim_message.execute: running -> awaits -> insert ->
    awaits -> progress(submitting) -> Return. Drift during the awaits must stop
    the effect at the next callback, which re-reads everything freshly."""
    b, cfg, h = channel
    work = send(b, "seal-interim-" + drift, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    effects = []

    async def interim_like(task, args, policy, running, progress, **kw):
        h.turns.append({"task": task, "args": args})
        await running({"phase": "inserting", "return_sent": False})
        effects.append("insert")
        with b.store.transaction():
            b.store.db.execute(DURING_ADAPTER[drift], (work["id"],))
        await progress({"phase": "submitting", "return_sent": False})
        effects.append("return")
        return {"success": True, "scope": "visible_input_delivery", "evidence": {}}

    h.execute = b.agents.execute = interim_like
    await b.message_receiver._process(h, message, run_id)
    assert effects == ["insert"]
    assert job(b, work["id"])["reply_id"] is None
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0] is None


async def test_requeue_then_reclaim_fences_old_process(channel):
    b, cfg, h = channel
    work = send(b, "seal-requeue", "Current task", kind="work")
    old_message, old_run = b.message_receiver._claim(work["id"])
    assert b.message_receiver._queue_unsent(
        work["id"], "visible_target_busy", old_run, "running"
    )
    new_message, new_run = b.message_receiver._claim(work["id"])
    assert new_run != old_run
    # The old process resumes with its stale snapshot/seal: no turn, no write.
    await b.message_receiver._process(h, old_message, old_run)
    assert h.turns == []
    row = job(b, work["id"])
    assert (row["state"], row["run_id"], row["finished"]) == ("running", new_run, None)
    assert json.loads(row["evidence"])["claim_seal"] == new_message["_claim_seal"]
    # The current owner still runs normally on its own seal.
    await b.message_receiver._process(h, new_message, new_run)
    assert len(h.turns) == 1 and job(b, work["id"])["state"] == "completed"


@pytest.mark.parametrize("damage", ["missing", "broken", "body"])
def test_visible_recovery_requires_fresh_stored_seal(channel, damage):
    from kirabridge.bridge_core.models import canonical

    b, cfg, h = channel
    work = send(b, "seal-recover-" + damage, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    evidence = {"handoff_id": run_id, "claim_seal": dict(message["_claim_seal"])}
    if damage == "missing":
        evidence.pop("claim_seal")
    elif damage == "broken":
        evidence["claim_seal"]["fields_sha256"] = "0" * 64
    with b.store.transaction():
        if damage == "body":
            b.store.db.execute(DURING_ADAPTER["body"], (work["id"],))
        b.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?",
            (canonical(evidence), work["id"]),
        )
        b.store.db.execute(
            "INSERT INTO visible_handoffs VALUES(?,?,?,'hash','{}',?,'return_sent',1,1,?)",
            (run_id, "chatgpt", "codex_channel", work["id"],
             canonical({"automatic_retry": False})),
        )
    b.message_receiver.recovered_handoffs.add(work["id"])
    b.message_receiver._reconcile_recovered_handoffs()
    row = job(b, work["id"])
    assert (row["state"], row["error"]) == ("unknown", "claim_seal_broken")
    stored = json.loads(row["evidence"])
    assert stored["last_observation"] == evidence  # preserved verbatim, never repaired
    assert work["id"] not in b.message_receiver.recovered_handoffs


def _damage_context(b, message_id, damage):
    with b.store.transaction():
        evidence = json.loads(job(b, message_id)["evidence"])
        if damage == "missing":
            evidence.pop("managed_guidance_context")
        else:
            evidence["managed_guidance_context"] = {
                **evidence["managed_guidance_context"], "tampered": True
            }
        raw = json.dumps(evidence)
        b.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?", (raw, message_id)
        )
    return raw, evidence


@pytest.mark.parametrize("damage", ["missing", "changed"])
@pytest.mark.parametrize("callback", ["running", "progress"])
async def test_stored_context_drift_with_valid_seal_fails_closed_unrepaired(
    channel, damage, callback
):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "ctx-" + damage + callback, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    context = message["_managed_guidance_context"]
    assert context is not None
    seen = {}

    async def damaging(task, args, policy, running, progress, **kw):
        h.turns.append({"task": task, "args": args})
        if callback == "progress":
            await running({"session_id": "s"})
        seen["raw"], seen["evidence"] = _damage_context(b, work["id"], damage)
        # claim_seal itself is untouched and still valid.
        assert seen["evidence"]["claim_seal"] == message["_claim_seal"]
        with pytest.raises(BridgeError) as exc:
            await (running if callback == "running" else progress)({"after_damage": True})
        seen["code"] = exc.value.code
        # Evidence column byte-identical: no repair by retain_context/sealed_write.
        assert job(b, work["id"])["evidence"] == seen["raw"]
        raise exc.value

    h.execute = b.agents.execute = damaging
    await b.message_receiver._process(h, message, run_id)
    assert seen["code"] == "guidance_context_changed"
    reasons = [
        json.loads(r["metadata"])["reason"]
        for r in b.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='message.claim_revalidation_failed'"
        )
    ]
    assert "context_binding_changed" in reasons
    row = job(b, work["id"])
    assert row["state"] in {"unknown", "failed"} and row["reply_id"] is None
    evidence = json.loads(row["evidence"])
    assert evidence.get("claim_seal_mismatch") is True
    # Damaged stored binding kept verbatim in last_observation; process context
    # is never written back top-level.
    assert evidence["last_observation"] == seen["evidence"]
    assert "managed_guidance_context" not in evidence
    assert "claim_seal" not in evidence
    assert "after_damage" not in json.dumps(evidence)
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0] is None


async def test_intact_context_still_progresses_and_completes(channel):
    b, cfg, h = channel
    await processed_note(channel)
    work = send(b, "ctx-intact", "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    context = message["_managed_guidance_context"]
    written = []

    async def ok(task, args, policy, running, progress, **kw):
        h.turns.append({"task": task, "args": args})
        await running({"session_id": "s"})
        await progress({"step": 1})
        written.append(json.loads(job(b, work["id"])["evidence"]))
        return await original(task, args, policy, running, progress, **kw)

    original = h.execute
    h.execute = b.agents.execute = ok
    await b.message_receiver._process(h, message, run_id)
    assert written[0]["step"] == 1
    assert written[0]["managed_guidance_context"] == context
    assert written[0]["claim_seal"] == message["_claim_seal"]
    assert job(b, work["id"])["state"] == "completed"
