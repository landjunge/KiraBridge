"""Only a positive bound local observer can finish without a mailbox ACK/reply."""

import asyncio

import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution


@pytest.fixture
def local_handoff(visible, monkeypatch):  # noqa: F811
    bridge, transport = visible
    transport.update(target="codex", text="› ", ack=False, reply=False)
    observer = bridge.visible_handoffs.codex_reply
    trace = []
    cursor = {"verified_sensor_stub": True}

    async def prepare(binding, *, process_identity, expected_identity, body, cwd):
        assert body == "Exact authorized body"
        assert cwd == "/tmp"
        assert not transport["calls"]
        trace.append("prepare_before_paste")
        return {"state": "ready", "cursor": cursor}

    async def before_submit(actual, binding, *, body):
        assert actual == cursor and body == "Exact authorized body"
        assert transport["calls"] == ["insert"]
        trace.append("check_before_return")
        return {"state": "ready", "cursor": cursor}

    async def observe(actual, binding, *, body, process_identity):
        assert actual == cursor and body == "Exact authorized body"
        assert transport["calls"] == ["insert", "return"]
        trace.append("observe_after_return")
        return {
            "state": "completed",
            "text": "Real local final text",
            "evidence": {
                "reply_source": "bound_local_codex_rollout",
                "turn_id": "exact-new-turn",
                "process_writer_verified": True,
            },
        }

    monkeypatch.setattr(observer, "prepare", prepare)
    monkeypatch.setattr(observer, "before_submit", before_submit)
    monkeypatch.setattr(observer, "observe", observe)
    return bridge, transport, trace


async def execute(bridge, *, wait_for_reply=True, timeout=1):
    return await bridge.visible_handoffs.execute(
        {"id": "local-observed-turn", "principal": "chatgpt"},
        AgentInput(
            agent="codex",
            prompt="Exact authorized body",
            cwd="/tmp",
            wait_for_reply=wait_for_reply,
            timeout=timeout,
        ),
        callback,
        callback,
    )


async def test_positive_local_observer_finishes_and_repeated_id_never_pastes_again(local_handoff):
    bridge, transport, trace = local_handoff
    result = await execute(bridge)
    assert result["scope"] == "local_agent_turn"
    assert result["text"] == "Real local final text"
    assert result["reply_source"] == "bound_local_codex_rollout"
    assert result["agent_confirmed"] is False
    assert result["request_reply_satisfied"] is True
    assert result["work_completion_verified"] is False
    assert result["project_completion_verified"] is False
    assert "reply_id" not in result["evidence"]
    assert trace == ["prepare_before_paste", "check_before_return", "observe_after_return"]
    status = bridge.visible_handoffs.status("chatgpt", "local-observed-turn")
    assert status["state"] == "completed"
    message = bridge.messages.get("chatgpt", status["message_id"])
    assert message["acknowledged"] is None
    assert not bridge.store.db.execute(
        "SELECT 1 FROM messages WHERE reply_to IS NOT NULL"
    ).fetchone()
    assert await execute(bridge) == result
    assert transport["calls"] == ["insert", "return"]
    assert trace.count("observe_after_return") == 1


async def test_real_authenticated_mailbox_reply_has_priority_over_local_observer(local_handoff):
    bridge, transport, trace = local_handoff
    transport.update(ack=True, reply=True)
    result = await execute(bridge)
    assert result["scope"] == "agent_turn" and result["text"] == "independent review"
    assert result["evidence"]["agent_confirmed"] is True
    assert trace == ["prepare_before_paste", "check_before_return"]


async def test_explicit_transport_only_mode_does_not_start_local_reply_observer(local_handoff):
    bridge, transport, trace = local_handoff
    result = await execute(bridge, wait_for_reply=False)
    assert result["scope"] == "visible_input_delivery"
    assert result["request_reply_satisfied"] is False
    assert trace == [] and transport["calls"] == ["insert", "return"]


async def test_lost_local_binding_keeps_cooperative_default_and_never_fakes_ack(
    local_handoff, monkeypatch
):
    bridge, transport, trace = local_handoff

    async def unavailable(*args, **kwargs):
        return {"state": "unavailable", "reason": "process_binding_changed"}

    monkeypatch.setattr(bridge.visible_handoffs.codex_reply, "observe", unavailable)
    with pytest.raises(UncertainExecution) as exc:
        await execute(bridge, timeout=0.02)
    assert exc.value.code == "visible_reply_unknown"
    status = bridge.visible_handoffs.status("chatgpt", "local-observed-turn")
    assert status["state"] == "unknown"
    assert status["evidence"]["local_reply_observer"]["reason"] == "process_binding_changed"
    assert bridge.messages.get("chatgpt", status["message_id"])["acknowledged"] is None
    assert transport["calls"] == ["insert", "return"]


async def test_original_default_without_independent_binding_stays_unconfirmed(visible):  # noqa: F811
    bridge, transport = visible
    transport.update(target="codex", text="› ", ack=False, reply=False)
    with pytest.raises(UncertainExecution):
        await execute(bridge, timeout=0.02)
    status = bridge.visible_handoffs.status("chatgpt", "local-observed-turn")
    assert status["state"] == "unknown"
    assert (
        status["evidence"]["local_reply_observer"]["reason"]
        == "independent_thread_binding_unavailable"
    )
    assert transport["calls"] == ["insert", "return"]


async def test_cancelling_local_reply_observation_preserves_delivery_without_replay(
    local_handoff, monkeypatch
):
    bridge, transport, _ = local_handoff
    entered = asyncio.Event()

    async def wait(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge.visible_handoffs.codex_reply, "observe", wait)
    task = asyncio.create_task(execute(bridge))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    status = bridge.visible_handoffs.status("chatgpt", "local-observed-turn")
    assert status["state"] == "sent"
    assert bridge.visible_handoffs.body_only_delivery(status)
    assert transport["calls"] == ["insert", "return"]


async def test_explicit_draft_continuation_rechecks_local_cursor_and_cannot_use_an_old_turn(
    local_handoff, monkeypatch
):
    bridge, transport, trace = local_handoff
    submit = bridge.visible_handoffs.submit_inserted

    async def failed_before_return(*args, **kwargs):
        raise BridgeError("visible_insert_unknown", "Interrupted after verified insertion")

    monkeypatch.setattr(bridge.visible_handoffs, "submit_inserted", failed_before_return)
    with pytest.raises(UncertainExecution):
        await execute(bridge, timeout=0.02)
    assert transport["calls"] == ["insert"]
    monkeypatch.setattr(bridge.visible_handoffs, "submit_inserted", submit)

    async def intervening_turn(*args, **kwargs):
        trace.append("continuation_recheck")
        return {"state": "unavailable", "reason": "turn_observed_before_our_return"}

    monkeypatch.setattr(bridge.visible_handoffs.codex_reply, "before_submit", intervening_turn)
    status = await bridge.visible_handoffs.continue_unsubmitted(
        "chatgpt", "local-observed-turn", callback
    )
    assert status["state"] == "sent" and transport["calls"] == ["insert", "return"]
    with pytest.raises(UncertainExecution):
        await execute(bridge, timeout=0.02)
    assert "continuation_recheck" in trace and "observe_after_return" not in trace
    assert transport["calls"] == ["insert", "return"]
