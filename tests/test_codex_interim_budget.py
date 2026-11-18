"""Delivery-only questions never consume later model-turn admission budgets."""
# ruff: noqa: F811

import json
import time

import pytest
from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.message_manager import MessageSend
from kirabridge.message_manager.receiver import MessageReceiver
from kirabridge.task_manager.store import Store


@pytest.mark.parametrize("budget", ["conversation", "hourly"])
@pytest.mark.parametrize("delivery_state", ["completed", "unknown"])
async def test_interim_delivery_does_not_charge_future_model_budget(
    delivery, budget, delivery_state
):
    bridge, _, _, _, _ = delivery
    limits = bridge.config.messaging
    limits.max_runs_per_conversation = 1 if budget == "conversation" else 10
    limits.max_runs_per_hour = 1 if budget == "hourly" else 10
    receiver = bridge.message_receiver
    for index in range(3):
        sent = bridge.messages.send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id="future-work" if budget == "conversation" else f"interim-{index}",
                idempotency_key=f"interim-{index}",
                body="Zwischenstand?",
                request_reply=False,
                interim_session={
                    "pane_id": "terminal:202:ttys006",
                    "expected_pid": 900,
                    "expected_agent_pid": 901,
                },
            ),
        )
        assert receiver._claim(sent["id"], direct=True, interim=True)
        receiver._finish(
            sent["id"],
            delivery_state,
            {
                "completion_scope": "visible_input_delivery",
                "new_agent_turn": False,
                "automatic_retry": False,
            },
        )

    def work(key):
        return bridge.messages.send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id="future-work",
                idempotency_key=key,
                body="A real new model task",
                kind="work",
            ),
        )

    actual = work("actual-model-turn")
    assert receiver._claim(actual["id"], direct=True), bridge.messages.get("chatgpt", actual["id"])
    assert (
        "limit_notes" not in bridge.messages.get("chatgpt", actual["id"])["processing"]["evidence"]
    )
    receiver._finish(actual["id"], "completed", {"new_agent_turn": True})
    over_budget = work("second-model-turn")
    assert receiver._claim(over_budget["id"], direct=True)
    job = bridge.messages.get("chatgpt", over_budget["id"])["processing"]
    assert job["state"] == "running"
    assert job["evidence"]["limit_notes"] == [budget + "_run_limit"]
    count_key = "conversation_runs" if budget == "conversation" else "hourly_runs"
    assert job["evidence"][count_key] >= 1


@pytest.mark.parametrize("budget", ["conversation", "hourly"])
@pytest.mark.parametrize("state", ["completed", "failed", "unknown"])
async def test_managed_dispatch_of_interim_target_counts_after_failure_and_reopen(
    delivery, budget, state, monkeypatch
):
    bridge, _, direct, _, Pool = delivery
    limits = bridge.config.messaging
    limits.max_runs_per_conversation = 1 if budget == "conversation" else 10
    limits.max_runs_per_hour = 1 if budget == "hourly" else 10
    limits.separate_managed_after = time.time() - 1
    receiver = bridge.message_receiver
    bridge.messages.delivery_hook = receiver._submit_new
    monkeypatch.setattr("kirabridge.message_manager.receiver.MCPClientPool", Pool)
    monkeypatch.setattr("kirabridge.message_manager.receiver.peer", lambda _cfg, who: who)
    calls = []

    async def model(task, args, policy, running, progress, **options):
        calls.append(options)
        await running({"new_agent_turn": True})
        if state == "unknown":
            raise UncertainExecution("fixture_unknown", "Synthetic ambiguous model result")
        if state == "failed":
            raise BridgeError("fixture_failed", "Synthetic model failure")
        return {"success": True, "text": "Mock result", "evidence": {}}

    monkeypatch.setattr(bridge.agents, "execute", model)
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="future-work" if budget == "conversation" else "first-work",
            idempotency_key="managed-original-target",
            body="Synthetic question",
            request_reply=False,
            interim_session={
                "pane_id": "terminal:202:ttys006",
                "expected_pid": 900,
                "expected_agent_pid": 901,
            },
        ),
    )
    assert not direct.active
    assert await receiver._dispatch_next("codex", include_visible=False)
    assert len(calls) == 1 and calls[0]["separate_managed"] is True
    assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == state

    # A later queued marker and mutable finish text cannot rewrite the route.
    bridge.messages._event(
        sent["id"], "message.queued", "codex", {"interim_session": {}, "interim_delivery": True}
    )
    original = tuple(bridge.store.db.execute("SELECT * FROM message_jobs").fetchone())
    events = [tuple(r) for r in bridge.store.db.execute("SELECT * FROM message_events")]
    bridge.store.close()
    bridge.store.db = Store(bridge.config.state_path / "bridge.sqlite3").db
    receiver = MessageReceiver(bridge)
    assert tuple(bridge.store.db.execute("SELECT * FROM message_jobs").fetchone()) == original
    assert [tuple(r) for r in bridge.store.db.execute("SELECT * FROM message_events")] == events
    later = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="future-work",
            idempotency_key="managed-followup",
            body="Next model work",
            kind="work",
            request_reply=False,
        ),
    )
    assert await receiver._dispatch_next("codex", include_visible=False)
    assert len(calls) == 2
    job = bridge.messages.get("chatgpt", later["id"])["processing"]
    assert job["state"] == state
    assert job["evidence"].get("reason") != budget + "_run_limit"
    noted = bridge.store.db.execute(
        "SELECT evidence FROM message_events WHERE message_id=? "
        "AND kind='message.processing_claimed'",
        (later["id"],),
    ).fetchone()
    assert budget + "_run_limit" in json.loads(noted[0])["limit_notes"]


@pytest.mark.parametrize("budget", ["conversation", "hourly"])
async def test_unknown_direct_steer_keeps_its_budget_exemption_after_reopen(delivery, budget):
    bridge, *_ = delivery
    limits = bridge.config.messaging
    limits.max_runs_per_conversation = 1 if budget == "conversation" else 10
    limits.max_runs_per_hour = 1 if budget == "hourly" else 10
    receiver = bridge.message_receiver
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="followup",
            idempotency_key="steer",
            body="Question",
            request_reply=False,
            interim_session={
                "pane_id": "terminal:202:ttys006",
                "expected_pid": 900,
                "expected_agent_pid": 901,
            },
        ),
    )
    assert receiver._claim(sent["id"], direct=True, interim=True)
    receiver._finish(sent["id"], "unknown", {"reason": "ambiguous_delivery"})
    bridge.store.close()
    bridge.store.db = Store(bridge.config.state_path / "bridge.sqlite3").db
    receiver = MessageReceiver(bridge)
    later = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="followup",
            idempotency_key="later",
            body="Real task",
            kind="work",
        ),
    )
    assert receiver._claim(later["id"], direct=True)
