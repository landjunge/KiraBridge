"""Visible delivery keeps user text exact and never fabricates agent completion."""
# Imported isolated fixtures are supplied by pytest.
# ruff: noqa: F811

import hashlib
import time
from pathlib import Path

import pytest
from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import canonical
from kirabridge.completion_manager import completion_payload
from kirabridge.message_manager import MessageSend
from kirabridge.visible_message_evidence import handoff_delivery_status


def local_result(bridge, message, run_id, text):
    """The real producer contract, with no authenticated mailbox identity."""
    binding = bridge.config.visible_handoffs.bindings["codex"].model_dump()
    return {
        "success": True,
        "scope": "local_agent_turn",
        "reply_source": "bound_local_codex_rollout",
        "text": text,
        "agent_confirmed": False,
        "request_reply_satisfied": True,
        "work_completion_verified": False,
        "project_completion_verified": False,
        "evidence": {
            "handoff_id": run_id,
            "message_id": message["id"],
            "completion_scope": "local_agent_turn",
            "reply_source": "bound_local_codex_rollout",
            "identity_scope": "OS_process_and_local_protocol_not_authenticated_mailbox",
            "agent_confirmed": False,
            "request_reply_satisfied": True,
            "process_writer_verified": True,
            "task_complete_observed": True,
            "turn_id": "01a192ba-0d60-7581-8d53-8fa4e45d702d",
            "user_item_id": "01a192ba-0d8d-72f0-9205-211872aadbdf",
            "final_item_id": "msg_034037684ed038c8016ae612f6a13081919abdb1ca5171c10d",
            "baseline_offset": 1234,
            "baseline_sha256": hashlib.sha256(b"pre-paste log prefix").hexdigest(),
            "appended_sha256": hashlib.sha256(
                b"exact user/turn/final/complete records"
            ).hexdigest(),
            "expected_payload_sha256": hashlib.sha256(message["body"].encode()).hexdigest(),
            "binding": binding,
            "protocol_binding": {
                "thread_id": "01a192b9-64f2-7d22-8429-cabd5faf13b6",
                "rollout_path": str(Path(bridge.config.data_dir) / "sessions" / "observed.jsonl"),
                "cwd": "/private/tmp",
                "origin": "process_writer_discovery",
            },
            "route": "existing_visible_terminal",
            "automatic_retry": False,
        },
    }


def recovered_local(bridge):
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="local-recovered",
            idempotency_key="local-recovered",
            body="Original requested text",
            kind="work",
            dispatch=True,
            request_reply=True,
        ),
    )
    _, run_id = bridge.message_receiver._claim(sent["id"], direct=True)
    result = local_result(bridge, sent, run_id, "Persisted genuine local final")
    now = time.time()
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,'completed',?,?,?)",
        (
            run_id,
            "chatgpt",
            "codex",
            "a" * 64,
            canonical(result["evidence"]["binding"]),
            sent["id"],
            now,
            now,
            canonical({"local_reply_result": result}),
        ),
    )
    bridge.store.db.execute(
        "UPDATE message_jobs SET evidence=? WHERE message_id=?",
        (canonical({"handoff_id": run_id, "state": "sent", "agent_confirmed": False}), sent["id"]),
    )
    bridge.message_receiver.recovered_handoffs.add(sent["id"])
    return sent, run_id, result


@pytest.mark.parametrize("request_reply", [True, False])
async def test_visible_receiver_preserves_body_and_reports_delivery_only(
    delivery, monkeypatch, request_reply
):
    bridge, transport, _, _, Pool = delivery
    conversation = "body-only-visible"
    parent = bridge.messages.send(
        "codex",
        MessageSend(
            recipient="chatgpt",
            conversation_id=conversation,
            idempotency_key="prior-context",
            body="PRIVATE PRIOR CONTEXT MUST NOT BE APPENDED",
            kind="note",
            dispatch=False,
        ),
    )
    body = '  Nur dieser Text.\n\n"ä🙂"\nKB-END-is-user-content  '
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id=conversation,
            idempotency_key="exact-body",
            reply_to=parent["id"],
            body=body,
            kind="work",
            dispatch=True,
            request_reply=request_reply,
        ),
    )
    received = []

    async def execute(task, args, policy, running, progress, **kwargs):
        assert args.wait_for_reply is request_reply
        received.append(args.prompt)
        await running({"return_sent": True})
        return {
            "success": True,
            "scope": "visible_input_delivery",
            "evidence": {"agent_confirmed": False, "return_sent": True},
        }

    monkeypatch.setattr(bridge.agents, "execute", execute)
    message, run_id = bridge.message_receiver._claim(sent["id"], direct=True)
    pool = Pool()
    await pool.connect("codex")
    await bridge.message_receiver._process(pool, message, run_id)
    assert received == [body]
    original = bridge.messages.get("chatgpt", sent["id"])
    assert original["acknowledged"] is None
    assert original["processing"]["state"] == "completed"
    evidence = original["processing"]["evidence"]
    assert evidence["completion_scope"] == "visible_input_delivery"
    assert evidence["agent_confirmed"] is False
    assert evidence["request_reply_satisfied"] is False
    assert original["processing"]["reply_id"] is None
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    notices = bridge.completions.receive("chatgpt")["notices"]
    assert len(notices) == 1
    payload = notices[0]["payload"]
    assert payload["completion_scope"] == "visible_input_delivery"
    assert payload["agent_confirmed"] is False
    assert payload["request_reply_satisfied"] is False
    assert "acknowledgement and reply unconfirmed" in payload["summary"]
    first = bridge.messages.receive("codex", conversation_id=conversation)["messages"][0]
    repeated = bridge.messages.receive("codex", conversation_id=conversation)["messages"][0]
    assert first["id"] == repeated["id"] == sent["id"]
    assert first["receipt"] == repeated["receipt"]
    assert repeated["processing"]["completion_scope"] == "visible_input_delivery"
    assert received == [body]
    assert not transport["calls"]


def test_direct_agent_completion_reports_only_confirmed_delivery():
    task = {
        "id": "body-only-task",
        "operation": "agent.execute",
        "state": "completed",
        "updated": 1.0,
        "result": {"scope": "visible_input_delivery", "agent_confirmed": False},
    }
    payload = completion_payload(task, 1)
    assert payload["completion_scope"] == "visible_input_delivery"
    assert payload["agent_confirmed"] is False
    assert payload["agent_work_completion_verified"] is False
    assert "reply unconfirmed" in payload["summary"]
    task["result"] = {"scope": "agent_turn", "text": "Actual authenticated result"}
    observed = completion_payload(task, 2)
    assert "completion_scope" not in observed
    assert observed["summary"].endswith("Actual authenticated result")


def test_only_versioned_verified_delivery_releases_its_stored_input_reservation(bridge):
    args = {
        "prompt_format": "body_only_v1",
        "reason": "body_only_target_ready",
        "input_reservation_released": True,
        "return_sent": True,
        "target_readiness": "verified_ready_before_new_input",
    }
    # Supplying parsed evidence is the same bounded read path as message_get.
    observed = handoff_delivery_status(bridge.store.db, "historical", "unknown", evidence=args)
    assert observed["input_reservation_released"]
    assert not observed["execution_reservation_active"]
    for field in args:
        legacy = {key: value for key, value in args.items() if key != field}
        held = handoff_delivery_status(bridge.store.db, "historical", "unknown", evidence=legacy)
        assert held["execution_reservation_active"]


async def test_bound_local_reply_returns_full_result_without_fabricated_mailbox_ack(
    delivery, monkeypatch
):
    bridge, transport, _, _, Pool = delivery
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="local-observed-return",
            idempotency_key="local-observed-return",
            body="Only this authorized body",
            kind="work",
            dispatch=True,
            request_reply=True,
        ),
    )
    text = "Actual bounded local final reply. ä🙂 " * 40

    async def execute(task, args, policy, running, progress, **kwargs):
        assert args.prompt == sent["body"]
        await running({"handoff_id": task["id"], "return_sent": True})
        return local_result(bridge, sent, task["id"], text)

    monkeypatch.setattr(bridge.agents, "execute", execute)
    message, run_id = bridge.message_receiver._claim(sent["id"], direct=True)
    pool = Pool()
    await pool.connect("codex")
    await bridge.message_receiver._process(pool, message, run_id)
    result = bridge.messages.get("chatgpt", sent["id"])
    assert result["acknowledged"] is None
    assert result["processing"]["state"] == "completed"
    assert result["processing"]["reply_id"] is None
    assert result["processing"]["result"]["text"] == text
    assert "local_reply_result" not in result["processing"]["evidence"]
    assert result["processing"]["request_reply_satisfied"] is True
    assert result["processing"]["agent_confirmed"] is False
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    notices = bridge.completions.receive("chatgpt")["notices"]
    assert len(notices) == 1
    assert notices[0]["payload"]["completion_scope"] == "local_agent_turn"
    assert notices[0]["payload"]["reply_source"] == "bound_local_codex_rollout"
    assert notices[0]["payload"]["agent_confirmed"] is False
    assert notices[0]["payload"]["agent_work_completion_verified"] is False
    assert not transport["calls"]


async def test_completed_local_reply_recovers_job_without_input_or_mailbox_identity(delivery):
    bridge, transport, _, _, _ = delivery
    sent, _, result = recovered_local(bridge)
    bridge.message_receiver._reconcile_recovered_handoffs()
    bridge.message_receiver._reconcile_recovered_handoffs()
    observed = bridge.messages.get("chatgpt", sent["id"])
    assert observed["processing"]["state"] == "completed"
    assert observed["processing"]["result"]["text"] == result["text"]
    assert observed["processing"]["evidence"]["reconciled_without_input"] is True
    assert observed["acknowledged"] is None and observed["processing"]["reply_id"] is None
    assert len(bridge.completions.receive("chatgpt")["notices"]) == 1
    assert not transport["calls"]


@pytest.mark.parametrize(
    "damage",
    [
        "invalid_json",
        "non_object",
        "null_container",
        "explicit_null",
        "missing_local_result",
        "cache_scalar",
        "wrong_message",
        "wrong_run",
        "missing_writer",
        "wrong_body_hash",
        "missing_complete",
        "missing_baseline_hash",
        "invalid_offset",
        "missing_protocol",
        "invalid_origin",
        "missing_native_binding",
        "changed_native_binding",
        "bad_saved_binding",
        "missing_final_id",
        "authenticated_claim",
        "protocol_authenticated_claim",
        "mailbox_reply_id",
        "claims_work_completed",
    ],
)
async def test_malformed_local_recovery_becomes_unknown_once_without_input_or_identity(
    delivery, damage
):
    bridge, transport, _, _, _ = delivery
    sent, run_id, result = recovered_local(bridge)
    proof = result["evidence"]
    container = {"local_reply_result": result}
    raw = None
    if damage == "invalid_json":
        raw = "{"
    elif damage == "non_object":
        raw = "[]"
    elif damage == "null_container":
        raw = "null"
    elif damage == "explicit_null":
        container["local_reply_result"] = None
    elif damage == "missing_local_result":
        container = {"completion_scope": "local_agent_turn"}
    elif damage == "cache_scalar":
        container["local_reply_result"] = "not a result"
    elif damage == "wrong_message":
        proof["message_id"] = "foreign-message"
    elif damage == "wrong_run":
        proof["handoff_id"] = "foreign-run"
    elif damage == "missing_writer":
        proof.pop("process_writer_verified")
    elif damage == "wrong_body_hash":
        proof["expected_payload_sha256"] = "0" * 64
    elif damage == "missing_complete":
        proof.pop("task_complete_observed")
    elif damage == "missing_baseline_hash":
        proof.pop("baseline_sha256")
    elif damage == "invalid_offset":
        proof["baseline_offset"] = True
    elif damage == "missing_protocol":
        proof.pop("protocol_binding")
    elif damage == "invalid_origin":
        proof["protocol_binding"]["origin"] = "guessed_latest_rollout"
    elif damage == "missing_native_binding":
        proof.pop("binding")
    elif damage == "changed_native_binding":
        proof["binding"]["agent_pid"] += 1
    elif damage == "bad_saved_binding":
        bridge.store.db.execute("UPDATE visible_handoffs SET binding='[]' WHERE id=?", (run_id,))
    elif damage == "missing_final_id":
        proof.pop("final_item_id")
    elif damage == "authenticated_claim":
        proof["authenticated_principal"] = "codex"
    elif damage == "protocol_authenticated_claim":
        proof["protocol_binding"]["authenticated_principal"] = "codex"
    elif damage == "mailbox_reply_id":
        proof["reply_id"] = "invented-mailbox-reply"
    elif damage == "claims_work_completed":
        result["work_completion_verified"] = True
    bridge.store.db.execute(
        "UPDATE visible_handoffs SET evidence=? WHERE id=?",
        (raw if raw is not None else canonical(container), run_id),
    )
    before = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id=?", (run_id,)).fetchone()
    )
    bridge.message_receiver._reconcile_recovered_handoffs()
    bridge.message_receiver._reconcile_recovered_handoffs()
    observed = bridge.messages.get("chatgpt", sent["id"])
    job = observed["processing"]
    assert job["state"] == "unknown" and job["error"] == "local_reply_conflict"
    assert observed["acknowledged"] is None and job["reply_id"] is None
    assert job["evidence"] == {"reason": "local_reply_conflict", "automatic_retry": False}
    assert len(bridge.completions.receive("chatgpt")["notices"]) == 1
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    assert (
        dict(
            bridge.store.db.execute(
                "SELECT * FROM visible_handoffs WHERE id=?", (run_id,)
            ).fetchone()
        )
        == before
    )
    assert not transport["calls"]


@pytest.mark.parametrize("cached", ["{", "[]", '{"local_reply_result":null}'])
async def test_genuine_mailbox_reply_has_priority_even_over_malformed_local_cache(delivery, cached):
    bridge, transport, _, _, _ = delivery
    sent, run_id, _ = recovered_local(bridge)
    bridge.store.db.execute("UPDATE visible_handoffs SET evidence=? WHERE id=?", (cached, run_id))
    delivered = bridge.messages.receive("codex")["messages"][0]
    bridge.messages.ack("codex", sent["id"], delivered["receipt"])
    reply = bridge.messages.send(
        "codex",
        MessageSend(
            recipient="chatgpt",
            conversation_id=sent["conversation_id"],
            idempotency_key="genuine-existing-reply",
            reply_to=sent["id"],
            body="Genuine authenticated mailbox answer",
            kind="result",
            request_reply=False,
            dispatch=False,
        ),
    )
    bridge.message_receiver._reconcile_recovered_handoffs()
    observed = bridge.messages.get("chatgpt", sent["id"])
    assert observed["processing"]["state"] == "completed"
    assert observed["processing"]["reply_id"] == reply["id"]
    assert observed["processing"]["evidence"]["reply_source"] == "authenticated_bridge_mailbox"
    assert observed["acknowledged"] is not None
    notice = bridge.completions.receive("chatgpt")["notices"][0]["payload"]
    assert notice.get("completion_scope") != "local_agent_turn"
    assert not transport["calls"]


async def test_completed_legacy_handoff_without_local_key_keeps_old_waiting_contract(delivery):
    bridge, transport, _, _, _ = delivery
    sent, run_id, _ = recovered_local(bridge)
    bridge.store.db.execute("UPDATE visible_handoffs SET evidence='{}' WHERE id=?", (run_id,))
    before = dict(
        bridge.store.db.execute(
            "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],)
        ).fetchone()
    )
    bridge.message_receiver._reconcile_recovered_handoffs()
    assert (
        dict(
            bridge.store.db.execute(
                "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],)
            ).fetchone()
        )
        == before
    )
    assert sent["id"] in bridge.message_receiver.recovered_handoffs
    assert not bridge.completions.receive("chatgpt")["notices"]
    assert not transport["calls"]


async def test_historical_unknown_job_is_never_reconciled_from_a_local_cache(delivery):
    bridge, transport, _, _, _ = delivery
    sent, run_id, _ = recovered_local(bridge)
    bridge.store.db.execute("UPDATE visible_handoffs SET evidence='[' WHERE id=?", (run_id,))
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='unknown',error='original_unknown' WHERE message_id=?",
        (sent["id"],),
    )
    before = dict(
        bridge.store.db.execute(
            "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],)
        ).fetchone()
    )
    bridge.message_receiver._reconcile_recovered_handoffs()
    assert (
        dict(
            bridge.store.db.execute(
                "SELECT * FROM message_jobs WHERE message_id=?", (sent["id"],)
            ).fetchone()
        )
        == before
    )
    assert not bridge.completions.receive("chatgpt")["notices"]
    assert not transport["calls"]
