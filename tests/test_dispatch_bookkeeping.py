"""Expired scheduling hints are disposable; persistent execution receipts are not."""

# ruff: noqa: F811
import sqlite3

import pytest
from test_direct_delivery import delivery, job, new_message, settled  # noqa: F401
from test_team_dispatcher import configure_team
from test_visible_handoff import visible  # noqa: F401

from kirabridge.message_manager import MessageSend
from kirabridge.message_manager.direct import DirectDelivery
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate


@pytest.mark.parametrize("state", ["completed", "failed", "blocked", "unknown"])
async def test_finished_direct_attempt_forgets_only_its_durably_recorded_id(
    delivery, monkeypatch, state
):
    bridge, transport, direct, connected, _ = delivery

    async def recorded(principal, message_id, event):
        bridge.message_receiver._finish(message_id, state, {"automatic_retry": False})
        event.set()

    monkeypatch.setattr(direct, "_deliver", recorded)
    sent = new_message(bridge, "recorded-" + state)
    assert direct.submit("chatgpt", sent["id"])
    assert not direct.submit("chatgpt", sent["id"])
    await settled(direct)

    assert not direct._submitted
    assert job(bridge, sent)["state"] == state
    assert not direct.submit("chatgpt", sent["id"])
    restarted = DirectDelivery(bridge.message_receiver)
    assert not restarted.submit("chatgpt", sent["id"])
    assert not transport["calls"] and not connected


async def test_unrecorded_finished_attempt_keeps_its_no_replay_tombstone(delivery, monkeypatch):
    bridge, _, direct, _, _ = delivery

    async def not_recorded(principal, message_id, event):
        event.set()  # Simulate a coroutine that could not persist its outcome.

    monkeypatch.setattr(direct, "_deliver", not_recorded)
    sent = new_message(bridge, "unrecorded")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)

    assert job(bridge, sent)["state"] == "queued"
    assert direct._submitted == {sent["id"]}
    assert not direct.submit("chatgpt", sent["id"])


async def test_storage_observation_failure_cannot_evict_no_replay_guard(delivery, monkeypatch):
    bridge, _, direct, _, _ = delivery

    async def not_recorded(principal, message_id, event):
        event.set()

    real_db = bridge.store.db

    class UnavailableDB:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("private storage observation failure")

        def __getattr__(self, key):
            return getattr(real_db, key)

    monkeypatch.setattr(direct, "_deliver", not_recorded)
    sent = new_message(bridge, "storage-observation")
    assert direct.submit("chatgpt", sent["id"])
    monkeypatch.setattr(bridge.store, "db", UnavailableDB())
    await settled(direct)
    assert direct._submitted == {sent["id"]}


def test_team_expired_backoffs_do_not_accumulate_history(bridge, monkeypatch):
    dispatcher = bridge.team_dispatcher
    dispatcher._defer = {f"finished-{index}": 99.0 for index in range(2000)}
    monkeypatch.setattr("kirabridge.team_manager.dispatcher.time.monotonic", lambda: 100.0)
    assert dispatcher._next() is None
    assert not dispatcher._defer


def test_team_live_backoff_preserves_persisted_original_work(bridge, config, tmp_path, monkeypatch):
    configure_team(bridge, config, tmp_path, monkeypatch)
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="bookkeeping",
            name="Bookkeeping",
            coordinator="local",
            members={"local": "coordinator", "codex": "worker"},
            idempotency_key="bookkeeping",
        ),
    )
    work = bridge.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="bookkeeping",
            assignee="codex",
            title="Original",
            body="One original work item",
            idempotency_key="original",
        ),
    )
    dispatcher = bridge.team_dispatcher
    dispatcher._defer[work["id"]] = 105.0
    now = [100.0]
    monkeypatch.setattr("kirabridge.team_manager.dispatcher.time.monotonic", lambda: now[0])
    assert dispatcher._next() is None
    assert dispatcher._defer == {work["id"]: 105.0}
    now[0] = 105.0
    selected, existing = dispatcher._next()
    assert selected["id"] == work["id"] and not existing
    assert selected["core_task_id"] is None
    assert not dispatcher._defer
    assert bridge.teams._work(work["id"])["state"] == "queued"


async def test_real_direct_geometry_refusal_is_failed_before_any_paste(delivery, monkeypatch):
    bridge, transport, direct, _, _ = delivery
    transport["target"], transport["text"] = "codex", "› "
    binding = bridge.config.visible_handoffs.bindings["codex"]
    monkeypatch.setattr(
        bridge.sessions,
        "current_selection",
        lambda: ("codex", binding, {binding.agent_pid: "owned-test-codex"}),
    )

    async def columns(*args, **kwargs):
        return 131

    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    receiver = bridge.message_receiver
    await receiver.start()
    try:
        result = await receiver.send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id="geometry",
                idempotency_key="geometry",
                kind="work",
                dispatch=True,
                body="Reply with MARKER.\n" + "abc " * 95 + "abcd",
            ),
        )
        await settled(direct)
        current = job(bridge, result)
        assert current["claimed"] is not None
        assert current["state"] == "failed"
        assert current["error"] == "visible_input_geometry_ambiguous"
        assert current["evidence"]["terminal_input_attempted"] is False
        assert current["evidence"]["automatic_retry"] is False
        assert not transport["calls"]
        assert not direct.submit("chatgpt", result["id"])
    finally:
        await receiver.stop()
