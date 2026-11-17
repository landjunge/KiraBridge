"""Seal integrity failures settle fail-closed on every path and are never promoted.

Covers DirectDelivery settlement without managed context, fresh failure evidence
inside the finish transaction, and the strict UNKNOWN -> completed fence.
"""

import asyncio
import contextlib
import json

import pytest

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend
from tests.test_managed_guidance_context import Harness, channel, send  # noqa: F401


def job(b, message_id):
    return b.store.db.execute(
        "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
    ).fetchone()


def stored_evidence(b, message_id):
    return json.loads(job(b, message_id)["evidence"])


def damage_seal(b, message_id, damage):
    evidence = stored_evidence(b, message_id)
    if damage == "remove":
        evidence.pop("claim_seal")
    else:
        evidence["claim_seal"] = {**evidence["claim_seal"], "fields_sha256": "0" * 64}
    raw = canonical(evidence)
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?", (raw, message_id)
        )
    return json.loads(raw)


def completed_ack_and_reply(b, message_id, run_id):
    """A genuinely completed visible handoff with authenticated ACK and reply."""
    row = b.store.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    b.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (run_id, row["sender"], row["recipient"], "immutable-hash", "{}", message_id,
         "completed", 1, 2, "{}"),
    )
    if row["acknowledged"] is None:
        b.messages.ack(row["recipient"], message_id, row["receipt"])
    b.messages.send(
        row["recipient"],
        MessageSend(
            recipient=row["sender"],
            conversation_id=row["conversation_id"],
            idempotency_key="late-" + message_id,
            body="Authenticated final answer",
            kind="result",
            reply_to=message_id,
            dispatch=False,
        ),
    )
    return b.message_receiver.reconcile_completed_handoff(row["sender"], run_id)


def direct_claim(b, message_id):
    message, run_id = b.message_receiver._claim(message_id, direct=True)
    b.message_receiver.direct._claimed[message_id] = run_id
    return message, run_id


@pytest.mark.parametrize("damage", ["remove", "replace"])
async def test_direct_delivery_seal_damage_without_context_settles_fail_closed(
    channel, damage
):
    b, cfg, h = channel
    work = send(b, "direct-seal-" + damage, "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    assert message.get("_managed_guidance_context") is None
    original = h.execute
    damaged = {}

    async def damaging(*args, **kw):
        result = await original(*args, **kw)  # every adapter callback passes
        damaged["evidence"] = damage_seal(b, work["id"], damage)
        return result

    h.execute = b.agents.execute = damaging
    event = asyncio.Event()
    await b.message_receiver._process(h, message, run_id, delivery_event=event)
    assert event.is_set() and len(h.turns) == 1
    row = job(b, work["id"])
    assert row["state"] == "unknown"
    assert row["error"] == "claim_seal_broken"
    evidence = json.loads(row["evidence"])
    # Damaged stored evidence kept verbatim, never replaced by settlement.
    assert evidence["last_observation"] == damaged["evidence"]
    assert evidence["claim_seal_mismatch"] is True
    assert evidence["seal_failure_reason"] in {"seal_broken", "seal_missing"}
    assert "claim_seal" not in evidence
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (work["id"],)
    ).fetchone()[0] is None
    # A valid completed ACK/reply later must not promote it.
    outcome = completed_ack_and_reply(b, work["id"], run_id)
    assert outcome["reconciled"] is False
    assert outcome["reason"] == "seal_failure_recorded"
    assert job(b, work["id"])["state"] == "unknown"
    assert len(h.turns) == 1  # no replay


async def test_direct_delivery_owner_change_stays_receiver_claim_changed(channel):
    b, cfg, h = channel
    work = send(b, "direct-owner", "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    codes = []

    async def handed_off(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        with b.store.transaction():
            b.store.db.execute(
                "UPDATE message_jobs SET run_id='foreign-run' WHERE message_id=?", (work["id"],)
            )
        try:
            await progress({"late": True})
        except BridgeError as exc:
            codes.append(exc.code)
            raise
        raise AssertionError("progress must fail after owner change")

    h.execute = b.agents.execute = handed_off
    await b.message_receiver._process(h, message, run_id, delivery_event=asyncio.Event())
    assert codes == ["receiver_claim_changed"]
    row = job(b, work["id"])
    assert row["state"] == "running" and row["run_id"] == "foreign-run"
    assert row["error"] is None and row["finished"] is None
    assert "claim_seal_mismatch" not in json.loads(row["evidence"])
    assert not b.store.db.execute(
        "SELECT 1 FROM audit WHERE kind='message.claim_revalidation_failed'"
    ).fetchone()


@pytest.mark.parametrize("direct", [False, True])
async def test_failure_evidence_reads_store_fresh_in_finish_transaction(
    channel, monkeypatch, direct
):
    b, cfg, h = channel
    work = send(b, "fresh-failure-" + str(direct), "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"]) if direct else b.message_receiver._claim(
        work["id"]
    )
    armed = {"on": False}
    raced = {}
    real_transaction = b.store.transaction

    @contextlib.contextmanager
    def racing_transaction():
        if armed["on"]:
            # Concurrent writer lands right before the failure transaction
            # begins (after any earlier read): same state/run_id, new evidence.
            armed["on"] = False
            evidence = stored_evidence(b, work["id"])
            evidence["claim_seal"] = {**evidence["claim_seal"], "seal_sha256": "f" * 64}
            evidence["concurrent_update"] = True
            raw = canonical(evidence)
            b.store.db.execute(
                "UPDATE message_jobs SET evidence=? WHERE message_id=? "
                "AND state='running' AND run_id=?",
                (raw, work["id"], run_id),
            )
            raced["evidence"] = json.loads(raw)
        with real_transaction() as db:
            yield db

    async def failing(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        await progress({"step": 1})
        armed["on"] = True
        raise RuntimeError("adapter crashed after input")

    monkeypatch.setattr(b.store, "transaction", racing_transaction)
    h.execute = b.agents.execute = failing
    event = asyncio.Event() if direct else None
    await b.message_receiver._process(h, message, run_id, delivery_event=event)
    assert "evidence" in raced, "race hook did not fire at the failure transaction"
    row = job(b, work["id"])
    assert row["state"] == "unknown"
    evidence = json.loads(row["evidence"])
    # Direct settlement must not erase the concurrently damaged stored seal.
    assert row["error"] == ("claim_seal_broken" if direct else "receiver_failed")
    # Fresh store value preserved verbatim, never the stale snapshot.
    assert evidence["last_observation"] == raced["evidence"]
    assert evidence["claim_seal_mismatch"] is True
    assert "claim_seal" not in evidence
    outcome = completed_ack_and_reply(b, work["id"], run_id)
    assert outcome["reconciled"] is False and outcome["reason"] == "seal_failure_recorded"


async def test_direct_failure_with_intact_seal_keeps_direct_settlement(channel):
    b, cfg, h = channel
    work = send(b, "direct-intact-failure", "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])

    async def failing(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        raise RuntimeError("adapter crashed after input")

    h.execute = b.agents.execute = failing
    await b.message_receiver._process(h, message, run_id, delivery_event=asyncio.Event())
    row = job(b, work["id"])
    assert row["state"] == "unknown" and row["error"] == "delivery_failed"
    assert json.loads(row["evidence"])["phase"] == "direct_admission"


def unknown_after_claim(b, key, evidence_for):
    work = send(b, key, "Current task", kind="work")
    message, run_id = b.message_receiver._claim(work["id"])
    stored = stored_evidence(b, work["id"])
    b.message_receiver._finish(
        work["id"], "unknown", evidence_for(stored, run_id), "visible_reply_unknown"
    )
    receipt = b.messages.receive("codex_channel", conversation_id="guidance")["messages"]
    assert receipt and receipt[0]["id"] == work["id"]
    return work["id"], run_id


def test_unknown_without_claim_seal_is_never_promotable(channel):
    b, cfg, h = channel
    message_id, run_id = unknown_after_claim(
        b, "unsealed-unknown", lambda stored, run_id: {"run_id": run_id, "reason": "x"}
    )
    outcome = completed_ack_and_reply(b, message_id, run_id)
    assert outcome == {
        "reconciled": False,
        "message_id": message_id,
        "state": "unknown",
        "reason": "seal_missing",
    }
    with pytest.raises(BridgeError) as exc, b.store.transaction():
        b.message_receiver._record_finish(job(b, message_id), "completed", {})
    assert exc.value.code == "receiver_claim_changed"
    assert job(b, message_id)["state"] == "unknown"


def test_unknown_with_intact_claim_seal_stays_promotable(channel):
    b, cfg, h = channel
    message_id, run_id = unknown_after_claim(
        b,
        "sealed-unknown",
        lambda stored, run_id: {"run_id": run_id, "claim_seal": stored["claim_seal"]},
    )
    outcome = completed_ack_and_reply(b, message_id, run_id)
    assert outcome["reconciled"] is True and outcome["state"] == "completed"
    assert job(b, message_id)["state"] == "completed"


# --- Direct reply timeout keeps the verified seal; malformed start evidence ---

from kirabridge.bridge_core.models import UncertainExecution  # noqa: E402
from kirabridge.mcp_gateway.client import MCPClientPool, Peer  # noqa: E402
from tests.test_mcp import http_bridge  # noqa: E402,F401


async def direct_reply_timeout(b, h, key):
    """Real DirectDelivery: input happened, no confirmed reply (normal timeout)."""
    work = send(b, key, "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    claimed = stored_evidence(b, work["id"])

    async def timed_out(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        raise UncertainExecution("visible_reply_unknown", "No confirmed final reply")

    h.execute = b.agents.execute = timed_out
    await b.message_receiver._process(h, message, run_id, delivery_event=asyncio.Event())
    return work["id"], run_id, claimed


def add_completed_handoff(b, message_id, run_id):
    row = b.store.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    b.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (run_id, row["sender"], row["recipient"], "immutable-hash", "{}", message_id,
         "completed", 1, 2, "{}"),
    )
    receipt = row["receipt"]
    if receipt is None:
        # The peer received it independently (not this receiver: no input here).
        received = b.messages.receive(row["recipient"], conversation_id=row["conversation_id"])
        receipt = next(m["receipt"] for m in received["messages"] if m["id"] == message_id)
    if row["acknowledged"] is None:
        b.messages.ack(row["recipient"], message_id, receipt)
    b.messages.send(
        row["recipient"],
        MessageSend(
            recipient=row["sender"], conversation_id=row["conversation_id"],
            idempotency_key="late-" + message_id, body="Authenticated final answer",
            kind="result", reply_to=message_id, dispatch=False,
        ),
    )


SENDER_TOKEN = "sender-test-" + "c" * 40


async def status_over_http(endpoint, run_id):
    async with MCPClientPool() as pool:
        await pool.connect(Peer("daemon", url=endpoint, token=SENDER_TOKEN))
        response = await pool.call("daemon", "visible_handoff_status", {"handoff_id": run_id})
    assert not response.isError
    return response.structuredContent


@pytest.fixture
def sender_token(channel, monkeypatch):
    # visible_handoff_status is called as the authenticated original sender.
    b, cfg, h = channel
    monkeypatch.setenv("SENDER_TEST_TOKEN", SENDER_TOKEN)
    for name, principal in cfg.principals.items():
        if name not in {"local", "other"}:
            principal.token_env = None
    cfg.principals["chatgpt"].token_env = "SENDER_TEST_TOKEN"
    return channel


async def test_direct_reply_timeout_with_intact_seal_reconciles_later(sender_token, http_bridge):
    b, cfg, h = sender_token
    _, endpoint = http_bridge
    message_id, run_id, claimed = await direct_reply_timeout(b, h, "direct-timeout-ok")
    row = job(b, message_id)
    assert row["state"] == "unknown" and row["error"] == "visible_reply_unknown"
    evidence = json.loads(row["evidence"])
    assert evidence["phase"] == "direct_admission" and evidence["automatic_retry"] is False
    # Freshly verified seal (and identity) kept by settlement, never a missing seal.
    assert evidence["claim_seal"] == claimed["claim_seal"]
    assert evidence["claim_seal"]["run_id"] == run_id
    assert "claim_seal_mismatch" not in evidence
    assert b.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (message_id,)
    ).fetchone()[0] is None  # no ACK from the failure path
    # Later genuine completed handoff with ACK + reply: real status tool reconciles.
    add_completed_handoff(b, message_id, run_id)
    value = await status_over_http(endpoint, run_id)
    assert value["state"] == "completed"
    assert value["receiver_reconciliation"]["reconciled"] is True
    assert job(b, message_id)["state"] == "completed"
    assert len(h.turns) == 1  # no replay
    again = await status_over_http(endpoint, run_id)
    assert again["receiver_reconciliation"]["reconciled"] is False
    assert len(h.turns) == 1


@pytest.mark.parametrize("damage", ["remove", "replace"])
async def test_direct_reply_timeout_with_damaged_seal_stays_unknown(channel, damage):
    b, cfg, h = channel
    work = send(b, "direct-timeout-" + damage, "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    damaged = {}

    async def timed_out(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        damaged["evidence"] = damage_seal(b, work["id"], damage)
        raise UncertainExecution("visible_reply_unknown", "No confirmed final reply")

    h.execute = b.agents.execute = timed_out
    await b.message_receiver._process(h, message, run_id, delivery_event=asyncio.Event())
    row = job(b, work["id"])
    assert row["state"] == "unknown" and row["error"] == "claim_seal_broken"
    evidence = json.loads(row["evidence"])
    assert evidence["last_observation"] == damaged["evidence"]
    assert evidence["claim_seal_mismatch"] is True and "claim_seal" not in evidence
    outcome = completed_ack_and_reply(b, work["id"], run_id)
    assert outcome["reconciled"] is False and outcome["reason"] == "seal_failure_recorded"
    assert len(h.turns) == 1


def corrupt_raw(b, message_id, raw):
    with b.store.transaction():
        b.store.db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?", (raw, message_id)
        )


async def deliver_like_direct(b, h, message, run_id, event):
    """Exactly DirectDelivery._deliver's handling around receiver._process."""
    direct = b.message_receiver.direct
    try:
        await b.message_receiver._process(h, message, run_id, delivery_event=event)
    except Exception as error:  # pragma: no cover - must not happen any more
        direct.fail(message["id"], error)
        raise
    finally:
        event.set()


MALFORMED = {"invalid_json": '{"claim_seal": {', "non_object": '["claim_seal", 1]'}


@pytest.mark.parametrize("case", sorted(MALFORMED))
async def test_malformed_evidence_at_process_start_settles_fail_closed(
    sender_token, http_bridge, case
):
    b, cfg, h = sender_token
    _, endpoint = http_bridge
    work = send(b, "malformed-" + case, "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    assert isinstance(message.get("_claim_seal"), dict)
    raw = MALFORMED[case]
    corrupt_raw(b, work["id"], raw)
    await deliver_like_direct(b, h, message, run_id, asyncio.Event())
    assert h.turns == []  # no input
    row = job(b, work["id"])
    assert row["state"] == "failed" and row["error"] == "claim_seal_broken"
    evidence = json.loads(row["evidence"])
    assert evidence["seal_failure_reason"] == "seal_broken"
    assert evidence["claim_seal_mismatch"] is True
    assert "claim_seal" not in evidence and "phase" not in evidence
    observation = evidence["last_observation"]
    if case == "invalid_json":
        assert observation["invalid_evidence"] == raw  # byte-identical
    else:
        assert observation == json.loads(raw)
    # Later ACK/reply/completed handoff: never completed, ACKed by us or replayed.
    add_completed_handoff(b, work["id"], run_id)
    before = job(b, work["id"])["evidence"]
    value = await status_over_http(endpoint, run_id)
    assert value["receiver_reconciliation"]["reconciled"] is False
    assert job(b, work["id"])["state"] == "failed"
    assert job(b, work["id"])["evidence"] == before
    assert h.turns == []


@pytest.mark.parametrize("case", sorted(MALFORMED))
async def test_malformed_evidence_after_adapter_attempt_stays_unknown(channel, case):
    b, cfg, h = channel
    work = send(b, "malformed-late-" + case, "Current task", kind="work")
    message, run_id = direct_claim(b, work["id"])
    raw = MALFORMED[case]

    async def corrupting(task, args, policy, running, progress, **kw):
        h.turns.append(task)
        await running({"session_id": "s"})
        corrupt_raw(b, work["id"], raw)
        raise UncertainExecution("visible_reply_unknown", "No confirmed final reply")

    h.execute = b.agents.execute = corrupting
    await deliver_like_direct(b, h, message, run_id, asyncio.Event())
    row = job(b, work["id"])
    assert row["state"] == "unknown" and row["error"] == "claim_seal_broken"
    evidence = json.loads(row["evidence"])
    assert evidence["claim_seal_mismatch"] is True and "claim_seal" not in evidence
    observation = evidence["last_observation"]
    if case == "invalid_json":
        assert observation["invalid_evidence"] == raw
    else:
        assert observation == json.loads(raw)
    outcome = completed_ack_and_reply(b, work["id"], run_id)
    assert outcome["reconciled"] is False and outcome["reason"] == "seal_failure_recorded"
    assert job(b, work["id"])["state"] == "unknown" and len(h.turns) == 1
