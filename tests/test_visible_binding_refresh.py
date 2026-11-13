"""Dead Grok bindings and scrollback activity must not block a live idle window."""

# Imported fixtures are used through pytest's dependency injection.
# ruff: noqa: F811
import json

import pytest
from test_visible_dispatch_wait import enqueue, fake_receiver
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.visible_binding import overlay_path, save_refresh
from kirabridge.visible_readiness import assess

OLD = ("terminal:100:ttys001", 123, 456)
NEW_PANE = "terminal:2767:ttys000"
NEW_SHELL = 45159
NEW_AGENT = 45186
IDLE = "Alte Zeile Thinking… [stop]\nDie Antwort ist fertig.\n╭\n│ ❯ │\n╰"
LIVE_STATUS = "Die Antwort ist fertig.\n⠋ Running [stop]\n╭\n│ ❯ │\n╰"
BUSY = "╭\nThinking… [stop]\n│ ❯ │\n╰"
NONEMPTY = "╭\n│ ❯ schon getippt │\n╰"

# The Grok paste-proof (single_row_capacity / insertion_observed) requires the
# full boxed footer. These local full-box screens/transport are used only by the
# dispatch tests below; the shared simplified-box fixture stays untouched.
GROK_BOX_TOP = "╭──────╮"
GROK_BOX_BOTTOM = "╰────── Grok 1.0 ─╯"
GROK_EMPTY_FULL = GROK_BOX_TOP + "\n│ ❯      │\n" + GROK_BOX_BOTTOM
GROK_IDLE_FULL = (
    "Alte Zeile Thinking… [stop]\nDie Antwort ist fertig.\n" + GROK_EMPTY_FULL
)


def fullbox_grok_transport(bridge, transport):
    transport["text"] = GROK_IDLE_FULL

    async def insert(principal, args, *, before_transport=None):
        assert not args.submit
        if before_transport is not None:
            await before_transport()
        transport["calls"].append("insert")
        transport["inserted_body"] = args.text
        transport["text"] = GROK_BOX_TOP + "\n│ ❯ " + args.text + " │\n" + GROK_BOX_BOTTOM
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    bridge.sessions.insert = insert


def new_session():
    return {
        "pane_id": NEW_PANE,
        "expected_pid": NEW_SHELL,
        "agent_pid": NEW_AGENT,
        "agent_candidate": "grok",
        "identity_ambiguous": False,
        "processes": [
            {"pid": NEW_SHELL, "ppid": 1, "name": "-zsh"},
            {"pid": NEW_AGENT, "ppid": NEW_SHELL, "name": "grok"},
        ],
    }


def install_catalog(monkeypatch, bridge, sessions):
    async def selected(principal, pane, pid):
        for row in sessions:
            legacy = row.get("legacy_expected_pid")
            if row["pane_id"] == pane and pid in {row["expected_pid"], legacy}:
                return dict(row)
        raise BridgeError("session_selection_changed", "stale target")

    async def catalog(principal, *, transport=None):
        return {"status": "available", "sessions": [dict(row) for row in sessions]}

    async def prove(principal, original):
        return {"original_pids_gone": True, "native_window_absent": True}

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", prove)


def remember(bridge, binding, state="unknown"):
    sent = enqueue(bridge, key="old-reservation")
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (sent["id"],)
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('old-run','chatgpt','grok','hash',?,? ,?,1,1,?)",
        (
            canonical(binding.model_dump()),
            sent["id"],
            state,
            canonical({"terminal_input_attempted": True, "automatic_retry": False}),
        ),
    )
    return dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )


def grok_binding():
    return SimpleBinding()


class SimpleBinding:
    ready_pattern = r"│\s*❯\s*│"
    busy_pattern = r"\[stop\]|esc to interrupt|Thinking…"


def test_historical_grok_activity_is_not_current_work_and_composer_text_still_blocks():
    binding = SimpleBinding()
    assert assess("grok", IDLE, binding)["state"] == "ready"
    assert assess("grok", LIVE_STATUS, binding)["state"] == "working"
    assert assess("grok", BUSY, binding)["state"] == "working"
    assert assess("grok", NONEMPTY, binding)["state"] == "input_not_empty"
    assert assess("grok", "Back to bottom\nFertig.\n╭\n│ ❯ │\n╰", binding)["state"] == "ready"
    assert assess("grok", "Fertig.\nBack to bottom\n╭\n│ ❯ │\n╰", binding)["state"] == "scrolled"
    assert assess("grok", "╭\n│ ❯ │\nBack to bottom\n╰", binding)["state"] == "scrolled"


async def test_dead_binding_refreshes_to_the_only_live_grok_and_survives_reopen(
    visible, config, monkeypatch
):
    bridge, transport = visible
    transport["text"] = IDLE
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    install_catalog(monkeypatch, bridge, [new_session()])
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    current = config.visible_handoffs.bindings["grok"]
    assert (current.pane_id, current.expected_pid, current.agent_pid) == (
        NEW_PANE,
        NEW_SHELL,
        NEW_AGENT,
    )
    assert current.ready_pattern == previous.ready_pattern
    saved = json.loads(overlay_path(config).read_text())["grok"]
    assert saved["replaced_pane_id"] == previous.pane_id
    assert not transport["calls"]
    config.visible_handoffs.bindings["grok"] = previous
    reopened = Bridge(config)
    try:
        restored = reopened.config.visible_handoffs.bindings["grok"]
        assert (restored.pane_id, restored.expected_pid, restored.agent_pid) == (
            NEW_PANE,
            NEW_SHELL,
            NEW_AGENT,
        )
    finally:
        reopened.store.close()


async def test_ambiguous_replacement_is_refused(visible, monkeypatch):
    bridge, transport = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    live = new_session()
    other = {
        **live,
        "pane_id": "terminal:3000:ttys004",
        "expected_pid": 9,
        "agent_pid": 10,
        "processes": [
            {"pid": 9, "name": "-zsh"},
            {"pid": 10, "name": "grok"},
        ],
    }
    install_catalog(monkeypatch, bridge, [live, other])
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code == "session_selection_changed"
    assert bridge.config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(bridge.config).exists()
    assert not transport["calls"]


async def test_still_live_configured_window_is_kept(visible, monkeypatch):
    bridge, transport = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    old = {
        "pane_id": previous.pane_id,
        "expected_pid": previous.expected_pid,
        "agent_pid": previous.agent_pid,
        "agent_candidate": "grok",
        "processes": [{"pid": previous.agent_pid, "name": "grok"}],
    }
    install_catalog(monkeypatch, bridge, [new_session(), old])
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert bridge.config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(bridge.config).exists()
    assert not transport["calls"]


async def test_dead_reservation_does_not_busy_lock_the_replacement_or_replay(visible, monkeypatch):
    bridge, transport = visible
    fullbox_grok_transport(bridge, transport)
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    before = remember(bridge, previous)
    install_catalog(monkeypatch, bridge, [new_session()])
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    after = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert after == before
    assert not transport["calls"]

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = GROK_EMPTY_FULL
        message = bridge.messages.receive("grok")["messages"][-1]
        bridge.messages.ack("grok", message["id"], message["receipt"])
        bridge.messages.send(
            "grok",
            MessageSend(
                recipient=principal,
                conversation_id=message["conversation_id"],
                idempotency_key="reply-" + message["id"],
                reply_to=message["id"],
                body="independent review",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )

    bridge.sessions.press_return = submit
    result = await bridge.visible_handoffs.execute(
        {"id": "fresh-after-dead-reservation", "principal": "chatgpt"},
        AgentInput(agent="grok", prompt="Ein neuer Auftrag", cwd="/tmp"),
        callback,
        callback,
    )
    assert result["text"] == "independent review"
    assert transport["calls"] == ["insert", "return"]
    unchanged = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert unchanged == before
    assert bridge.visible_handoffs.status("chatgpt", "fresh-after-dead-reservation")["state"] == (
        "completed"
    )


async def test_session_input_releases_only_a_proven_dead_other_pane(visible, monkeypatch):
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    live = binding.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    before = remember(bridge, binding, state="confirmed")

    async def absent(principal, original):
        return {"original_pids_gone": True}

    async def present(principal, original):
        raise BridgeError("visible_absence_unproven", "Original PID exists")

    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", present)
    with pytest.raises(BridgeError) as blocked:
        await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "grok", live)
    assert blocked.value.code == "visible_target_busy"
    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", absent)
    await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "grok", live)
    after = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert after == before and not transport["calls"]


async def test_pre_paste_screen_mismatch_releases_the_lock_without_resending(visible):
    bridge, transport = visible
    transport["text"] = IDLE
    binding = bridge.config.visible_handoffs.bindings["grok"]
    sent = enqueue(bridge, key="refused-before-paste")
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='unknown' WHERE message_id=?", (sent["id"],)
    )
    evidence = canonical(
        {"reason": "visible_input_changed", "automatic_retry": False, "return_sent": False}
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('refused-run','chatgpt','grok','hash',?,?,"
        "'unknown',1,1,?)",
        (canonical(binding.model_dump()), sent["id"], evidence),
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoff_events (id,at,state,evidence) "
        "VALUES('refused-run',1,'inserting',?)",
        (canonical({"terminal_input_attempted": True}),),
    )
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    status = bridge.visible_handoffs.status("chatgpt", "refused-run")
    assert status["state"] == "unknown"
    assert status["evidence"]["reason"] == "pre_paste_refusal_lock_released"
    assert status["evidence"]["previous_reason"] == "visible_input_changed"
    assert status["evidence"]["automatic_retry"] is False
    assert status["evidence"]["terminal_input_attempted"] is False
    assert not transport["calls"]
    job = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert job["state"] == "unknown"


async def test_paste_that_may_have_landed_stays_locked(visible):
    bridge, transport = visible
    transport["text"] = IDLE
    binding = bridge.config.visible_handoffs.bindings["grok"]
    sent = enqueue(bridge, key="maybe-pasted")
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('pasted-run','chatgpt','grok','hash',?,?,"
        "'unknown',1,1,?)",
        (
            canonical(binding.model_dump()),
            sent["id"],
            canonical({"reason": "visible_paste_unconfirmed", "automatic_retry": False}),
        ),
    )
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code == "visible_target_busy" and not transport["calls"]


async def test_same_live_reservation_stays_busy_and_is_not_sent_twice(visible):
    bridge, transport = visible
    transport["text"] = IDLE
    binding = bridge.config.visible_handoffs.bindings["grok"]
    before = remember(bridge, binding)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code == "visible_target_busy"
    after = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert after == before and not transport["calls"]
    with pytest.raises(BridgeError) as again:
        await bridge.visible_handoffs.execute(
            {"id": "must-not-pass-the-lock", "principal": "chatgpt"},
            AgentInput(agent="grok", prompt="nicht senden", cwd="/tmp"),
            callback,
            callback,
        )
    assert again.value.code == "visible_target_busy" and not transport["calls"]


async def test_historical_activity_delivers_once_and_current_activity_or_text_waits(
    visible, monkeypatch
):
    bridge, transport = visible
    transport["text"] = IDLE
    sent = enqueue(bridge, key="historical-idle")
    processed = []
    fake_receiver(monkeypatch, bridge, processed)
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"]]
    assert not transport["calls"]
    waiting = enqueue(bridge, key="current-busy")
    transport["text"] = BUSY
    assert not await bridge.message_receiver._dispatch_next()
    waiting_job = bridge.messages.get("chatgpt", waiting["id"])["processing"]
    assert waiting_job["state"] == "queued" and waiting_job["claimed"] is None
    assert waiting_job["evidence"]["reason"] == "visible_target_working"
    assert waiting_job["evidence"]["terminal_input_attempted"] is False
    transport["text"] = IDLE
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"], waiting["id"]]
    typed = enqueue(bridge, key="typed")
    transport["text"] = NONEMPTY
    assert not await bridge.message_receiver._dispatch_next()
    typed_job = bridge.messages.get("chatgpt", typed["id"])["processing"]
    assert typed_job["state"] == "queued" and typed_job["claimed"] is None
    assert typed_job["evidence"]["reason"] == "visible_input_not_empty"
    assert typed_job["evidence"]["terminal_input_attempted"] is False
    transport["text"] = IDLE
    assert await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"], waiting["id"], typed["id"]]
    assert not await bridge.message_receiver._dispatch_next()
    assert processed == [sent["id"], waiting["id"], typed["id"]]


async def test_two_consecutive_replies_each_return_once_then_reopen_keeps_results(visible, config):
    bridge, transport = visible
    fullbox_grok_transport(bridge, transport)
    bodies = []

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = GROK_EMPTY_FULL
        message = bridge.messages.receive("grok")["messages"][-1]
        bridge.messages.ack("grok", message["id"], message["receipt"])
        sent = bridge.messages.send(
            "grok",
            MessageSend(
                recipient=principal,
                conversation_id=message["conversation_id"],
                idempotency_key="reply-" + message["id"],
                reply_to=message["id"],
                body="Antwort " + message["id"],
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )
        bodies.append(sent["body"])

    bridge.sessions.press_return = submit
    for index in (1, 2):
        result = await bridge.visible_handoffs.execute(
            {"id": f"run-{index}", "principal": "chatgpt"},
            AgentInput(agent="grok", prompt=f"Auftrag {index}", cwd="/tmp"),
            callback,
            callback,
        )
        assert result["text"] in bodies and result["text"].startswith("Antwort ")
    assert transport["calls"] == ["insert", "return", "insert", "return"]
    assert len(set(bodies)) == 2
    reopened = Bridge(config)
    try:
        rows = list(reopened.store.db.execute("SELECT id,state FROM visible_handoffs ORDER BY id"))
        assert [tuple(row) for row in rows] == [("run-1", "completed"), ("run-2", "completed")]
        assert reopened.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
    finally:
        reopened.store.close()


async def test_sent_dead_reservation_leaves_the_index_without_a_second_delivery(
    visible, monkeypatch
):
    bridge, transport = visible
    fullbox_grok_transport(bridge, transport)
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    remember(bridge, previous, state="sent")
    install_catalog(monkeypatch, bridge, [new_session()])

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = GROK_EMPTY_FULL
        message = bridge.messages.receive("grok")["messages"][-1]
        bridge.messages.ack("grok", message["id"], message["receipt"])
        bridge.messages.send(
            "grok",
            MessageSend(
                recipient=principal,
                conversation_id=message["conversation_id"],
                idempotency_key="reply-" + message["id"],
                reply_to=message["id"],
                body="independent review",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )

    bridge.sessions.press_return = submit
    result = await bridge.visible_handoffs.execute(
        {"id": "after-sent-dead", "principal": "chatgpt"},
        AgentInput(agent="grok", prompt="Nur der neue Auftrag", cwd="/tmp"),
        callback,
        callback,
    )
    parked = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    evidence = json.loads(parked["evidence"])
    assert parked["state"] == "unknown"
    assert evidence["reason"] == "binding_proven_dead"
    assert evidence["previous_state"] == "sent"
    assert evidence["automatic_retry"] is False
    assert result["text"] == "independent review"
    assert transport["calls"] == ["insert", "return"]
    assert bridge.visible_handoffs.status("chatgpt", "after-sent-dead")["state"] == "completed"
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 2


async def test_incomplete_catalog_does_not_replace_or_release(visible, monkeypatch):
    bridge, transport = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    before = remember(bridge, previous, state="sent")

    async def selected(principal, pane, pid):
        raise BridgeError("session_selection_changed", "stale target")

    async def catalog(principal, *, transport=None):
        return {"status": "available", "incomplete": True, "sessions": [new_session()]}

    async def prove(principal, original):
        raise AssertionError("An incomplete catalog must not prove absence")

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", prove)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code == "visible_target_busy"
    assert bridge.config.visible_handoffs.bindings["grok"] == previous
    after = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert after == before and not transport["calls"]


async def test_missing_snapshot_row_stays_locked_when_its_pid_still_exists(visible, monkeypatch):
    bridge, transport = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    before = remember(bridge, previous, state="sent")
    current = previous.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    bridge.config.visible_handoffs.bindings["grok"] = current
    save_refresh(bridge.config, "grok", previous, current)
    install_catalog(monkeypatch, bridge, [new_session()])

    async def prove(principal, original):
        raise BridgeError("visible_absence_unproven", "Original PID exists")

    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", prove)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code == "visible_target_busy"
    after = dict(
        bridge.store.db.execute("SELECT * FROM visible_handoffs WHERE id='old-run'").fetchone()
    )
    assert after == before and not transport["calls"]


def test_manual_config_change_is_not_overwritten_by_an_older_overlay(config):
    config.visible_handoffs.enabled = True
    config.visible_handoffs.bindings["grok"] = VisibleTerminalBinding(
        pane_id="terminal:100:ttys001",
        expected_pid=123,
        agent_pid=456,
        ready_pattern=r"│\s*❯\s*│",
    )
    path = overlay_path(config)
    path.parent.mkdir(parents=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_text(
        json.dumps(
            {
                "grok": {
                    "replaced_pane_id": "terminal:100:ttys001",
                    "replaced_expected_pid": 123,
                    "replaced_agent_pid": 456,
                    "pane_id": NEW_PANE,
                    "expected_pid": NEW_SHELL,
                    "agent_pid": NEW_AGENT,
                }
            }
        )
    )
    config.visible_handoffs.bindings["grok"] = VisibleTerminalBinding(
        pane_id="terminal:9:ttys009",
        expected_pid=9,
        agent_pid=10,
        ready_pattern=r"│\s*❯\s*│",
    )
    Bridge(config).store.close()
    assert config.visible_handoffs.bindings["grok"].pane_id == "terminal:9:ttys009"
