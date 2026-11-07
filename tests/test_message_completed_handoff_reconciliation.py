"""Explicit authenticated late replies correct a receiver outcome without input."""
# Fixtures imported for pytest dependency injection.
# ruff: noqa: F811

import json

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.message_manager import MessageSend


@pytest.fixture
def completed_handoff(visible, monkeypatch):
    bridge, transport = visible
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    policy.capabilities += ["message.send", "message.read", "message.ack"]
    policy.message_peers += ["codex"]
    bridge.config.principals["codex"].message_peers += ["local"]
    original = bridge.messages._send(
        "local",
        MessageSend(
            recipient="codex",
            conversation_id="late-reply",
            idempotency_key="original",
            body="Existing independently accepted work",
            kind="work",
            request_reply=True,
            dispatch=False,
        ),
        visible_internal=True,
    )
    message_id, run_id = original["id"], "channel-exact-old-run"
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state,run_id) VALUES(?,'running',?)",
        (message_id, run_id),
    )
    prior_evidence = {"reason": "reply_unconfirmed", "original_observation": {"return_sent": True}}
    bridge.message_receiver._finish(message_id, "unknown", prior_evidence, "visible_reply_unknown")
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            "local",
            "codex",
            "immutable-hash",
            canonical(bridge.config.visible_handoffs.bindings["codex"].model_dump()),
            message_id,
            "completed",
            1,
            2,
            "{}",
        ),
    )
    incoming = bridge.messages.receive("codex")["messages"][0]
    bridge.messages.ack("codex", message_id, incoming["receipt"])
    reply = bridge.messages.send(
        "codex",
        MessageSend(
            recipient="local",
            conversation_id="late-reply",
            idempotency_key="late-answer",
            body="Authenticated final answer",
            kind="result",
            reply_to=message_id,
            dispatch=False,
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Explicit reconciliation must not send or receive new input")

    for name in ("read", "insert", "press_return", "selected", "catalog"):
        monkeypatch.setattr(bridge.sessions, name, forbidden)
    monkeypatch.setattr(bridge.agents, "execute", forbidden)
    monkeypatch.setattr(bridge.messages, "send", forbidden)
    return bridge, transport, message_id, run_id, reply["id"], prior_evidence


def snapshot(bridge):
    return {
        table: [tuple(r) for r in bridge.store.db.execute("SELECT * FROM " + table)]
        for table in (
            "messages",
            "message_jobs",
            "visible_handoffs",
            "message_events",
            "completion_notices",
        )
    }


def test_exact_completed_run_and_authenticated_reply_correct_unknown_once(completed_handoff):
    bridge, transport, message_id, run_id, reply_id, previous = completed_handoff
    before = snapshot(bridge)
    original_notice = before["completion_notices"][0]
    result = bridge.message_receiver.reconcile_completed_handoff("local", run_id)
    assert result == {
        "reconciled": True,
        "message_id": message_id,
        "state": "completed",
        "reply_id": reply_id,
        "reconciled_without_input": True,
    }
    job = bridge.messages.get("local", message_id)["processing"]
    evidence = job["evidence"]
    assert job["state"] == "completed" and job["error"] is None and job["reply_id"] == reply_id
    assert evidence["previous_state"] == "unknown"
    assert evidence["previous_evidence"] == previous
    assert evidence["previous_error"] == "visible_reply_unknown"
    assert evidence["supersedes_notice_id"] == original_notice[1]
    assert evidence["agent_confirmed"] and evidence["reconciled_without_input"]
    assert evidence["project_completion_verified"] is False
    notices = [tuple(r) for r in bridge.store.db.execute("SELECT * FROM completion_notices")]
    assert len(notices) == 2 and notices[0] == original_notice
    payload = json.loads(
        bridge.store.db.execute(
            "SELECT payload FROM completion_notices ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0]
    )
    assert payload["outcome"] == "success" and payload["reply_id"] == reply_id
    assert payload["supersedes"] == original_notice[1]
    after = snapshot(bridge)
    assert after["messages"] == before["messages"]
    assert after["visible_handoffs"] == before["visible_handoffs"]
    assert after["message_events"][: len(before["message_events"])] == before["message_events"]
    assert not bridge.message_receiver.reconcile_completed_handoff("local", run_id)["reconciled"]
    assert snapshot(bridge) == after
    assert transport["calls"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "no_ack",
        "no_reply",
        "reply_parent",
        "reply_sender",
        "reply_recipient",
        "reply_kind",
        "reply_conversation",
        "run_id",
        "handoff_message",
        "handoff_principal",
        "handoff_target",
        "handoff_incomplete",
        "invalid_evidence",
        "nonobject_evidence",
    ],
)
def test_incomplete_or_mismatched_receipts_never_correct_history(completed_handoff, fault):
    bridge, transport, message_id, run_id, reply_id, _ = completed_handoff
    db = bridge.store.db
    if fault == "no_ack":
        db.execute("UPDATE messages SET acknowledged=NULL WHERE id=?", (message_id,))
    elif fault == "no_reply":
        db.execute("UPDATE messages SET reply_to=NULL WHERE id=?", (reply_id,))
    elif fault.startswith("reply_"):
        field = {
            "reply_parent": "reply_to",
            "reply_sender": "sender",
            "reply_recipient": "recipient",
            "reply_kind": "kind",
            "reply_conversation": "conversation_id",
        }[fault]
        value = "note" if field == "kind" else "different"
        if field == "reply_to":
            value = reply_id
        elif field == "conversation_id":
            db.execute(
                "INSERT INTO conversations VALUES(?,?,?,?)",
                (
                    "different",
                    "codex",
                    "local",
                    1,
                ),
            )
        db.execute("UPDATE messages SET " + field + "=? WHERE id=?", (value, reply_id))
    elif fault == "run_id":
        db.execute("UPDATE message_jobs SET run_id='different' WHERE message_id=?", (message_id,))
    elif fault == "handoff_message":
        db.execute("UPDATE visible_handoffs SET message_id=? WHERE id=?", (reply_id, run_id))
    elif fault in {"handoff_principal", "handoff_target"}:
        field = "principal" if fault == "handoff_principal" else "target"
        db.execute("UPDATE visible_handoffs SET " + field + "='different' WHERE id=?", (run_id,))
    elif fault == "handoff_incomplete":
        db.execute("UPDATE visible_handoffs SET state='sent' WHERE id=?", (run_id,))
    else:
        db.execute(
            "UPDATE message_jobs SET evidence=? WHERE message_id=?",
            (
                "[1]" if fault == "nonobject_evidence" else "{invalid",
                message_id,
            ),
        )
    before = snapshot(bridge)
    try:
        result = bridge.message_receiver.reconcile_completed_handoff("local", run_id)
        assert result["reconciled"] is False
    except BridgeError as exc:
        assert exc.code == "not_found" and fault == "handoff_principal"
    assert snapshot(bridge) == before
    assert transport["calls"] == []


@pytest.mark.parametrize(
    "state", ["queued", "running", "failed", "blocked", "cancelled", "completed"]
)
def test_explicit_correction_only_changes_unknown_jobs(completed_handoff, state):
    bridge, _, message_id, run_id, _, _ = completed_handoff
    bridge.store.db.execute(
        "UPDATE message_jobs SET state=? WHERE message_id=?", (state, message_id)
    )
    before = snapshot(bridge)
    assert not bridge.message_receiver.reconcile_completed_handoff("local", run_id)["reconciled"]
    assert snapshot(bridge) == before


@pytest.mark.parametrize("principal", ["grok", "reader-revoked"])
def test_handoff_and_mailbox_authority_remain_required(completed_handoff, principal):
    bridge, _, _, run_id, _, _ = completed_handoff
    if principal == "reader-revoked":
        bridge.config.principals["local"].capabilities.remove("message.read")
        principal = "local"
    before = snapshot(bridge)
    with pytest.raises(BridgeError) as error:
        bridge.message_receiver.reconcile_completed_handoff(principal, run_id)
    assert error.value.code in {"not_found", "forbidden"}
    assert snapshot(bridge) == before


def test_normal_finish_and_startup_recovery_still_leave_unknown_untouched(completed_handoff):
    bridge, _, message_id, run_id, _, _ = completed_handoff
    before = snapshot(bridge)
    bridge.message_receiver._finish(message_id, "completed", {"not_independent_proof": True})
    bridge.message_receiver.recovered_handoffs.add(message_id)
    bridge.message_receiver._reconcile_recovered_handoffs()
    assert snapshot(bridge) == before


async def test_existing_authenticated_status_tool_performs_explicit_correction(
    completed_handoff, http_bridge
):
    bridge, transport, message_id, run_id, _, _ = completed_handoff
    http_owner, endpoint = http_bridge
    assert http_owner is bridge
    async with MCPClientPool() as pool:
        await pool.connect(Peer("daemon", url=endpoint, token="local-test-" + "a" * 40))
        for expected in (True, False):
            response = await pool.call("daemon", "visible_handoff_status", {"handoff_id": run_id})
            assert not response.isError
            value = response.structuredContent
            assert value["state"] == "completed"
            assert value["receiver_reconciliation"]["reconciled"] is expected
    assert bridge.messages.get("local", message_id)["processing"]["state"] == "completed"
    assert bridge.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 2
    assert transport["calls"] == []


def test_notice_failure_rolls_back_the_entire_explicit_correction(completed_handoff, monkeypatch):
    bridge, _, _, run_id, _, _ = completed_handoff
    before = snapshot(bridge)

    def broken_notice(*args, **kwargs):
        raise OSError("isolated outbox write failure")

    monkeypatch.setattr("kirabridge.completion_manager.record_notice", broken_notice)
    with pytest.raises(OSError):
        bridge.message_receiver.reconcile_completed_handoff("local", run_id)
    assert snapshot(bridge) == before


async def test_status_endpoint_keeps_existing_mailbox_permission_checks(
    completed_handoff, http_bridge
):
    bridge, _, _, run_id, _, _ = completed_handoff
    _, endpoint = http_bridge
    bridge.config.principals["local"].capabilities.remove("message.read")
    before = snapshot(bridge)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("daemon", url=endpoint, token="local-test-" + "a" * 40))
        response = await pool.call("daemon", "visible_handoff_status", {"handoff_id": run_id})
    assert not response.isError
    assert response.structuredContent["error"]["code"] == "forbidden"
    assert snapshot(bridge) == before
