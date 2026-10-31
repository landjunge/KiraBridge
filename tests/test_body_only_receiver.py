"""Visible delivery keeps user text exact and never fabricates agent completion."""
# Imported isolated fixtures are supplied by pytest.
# ruff: noqa: F811

import pytest
from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.completion_manager import completion_payload
from kirabridge.message_manager import MessageSend
from kirabridge.visible_message_evidence import handoff_delivery_status


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
