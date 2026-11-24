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
from kirabridge.cli_adapters import adapter_for
from kirabridge.message_manager import MessageSend
from kirabridge.visible_binding import load_refresh, overlay_path, save_refresh
from kirabridge.visible_handoff import VisibleReadinessError
from kirabridge.visible_readiness import assess

OLD = ("terminal:100:ttys001", 123, 456)
NEW_PANE = "terminal:2767:ttys000"
NEW_SHELL = 45159
NEW_AGENT = 45186
IDLE = "Alte Zeile Thinking… [stop]\nDie Antwort ist fertig.\n╭\n│ ❯ │\n╰"
LIVE_STATUS = "Die Antwort ist fertig.\n⠋ Running [stop]\n╭\n│ ❯ │\n╰"
BUSY = "╭\nThinking… [stop]\n│ ❯ │\n╰"
NONEMPTY = "╭\n│ ❯ schon getippt │\n╰"
REAL_EMPTY = (
    " ╭────────────────────────────────────────────────────────╮ \n"
    " │ ❯ Build anything                                       │ \n"
    " ╰─────────────────── Grok 4.7 (medium) · always-approve ─╯ \n"
    " \n Ctrl+x:shortcuts\n"
)
REAL_TYPED = REAL_EMPTY.replace("Build anything", "Bitte nicht überschreiben")
REAL_UNKNOWN = "╭\n│ kein Eingabefeld\n╰"


def new_session():
    return {
        "pane_id": NEW_PANE,
        "expected_pid": NEW_SHELL,
        "agent_pid": NEW_AGENT,
        "agent_candidate": "grok",
        "identity_ambiguous": False,
        "transport": "terminal_app",
        "tty": "/dev/ttys000",
        "processes": [
            {"pid": NEW_SHELL, "ppid": 1, "name": "-zsh", "image": "/bin/zsh"},
            {"pid": NEW_AGENT, "ppid": NEW_SHELL, "name": "grok", "image": "/bin/grok"},
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

    async def identity(pid, **kwargs):
        row = next(row for row in sessions if any(p["pid"] == pid for p in row["processes"]))
        process = next(p for p in row["processes"] if p["pid"] == pid)
        tty = row["pane_id"].rsplit(":", 1)[1]
        return f"501 {tty} Fri Oct 30 20:26:00 2026 {process['ppid']} {process['image']}"

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "prove_original_target_gone", prove)
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    bridge.visible_handoffs.generation_observer = lambda pids: {
        pid: {"boot": "test-boot", "pid": pid, "birth": str(pid)} for pid in pids
    }


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


def test_real_grok_placeholder_is_an_empty_composer_but_typed_text_blocks():
    binding = SimpleBinding()
    empty = assess("grok", REAL_EMPTY, binding)
    assert empty["state"] == "ready" and empty["input_empty"]
    typed = assess("grok", REAL_TYPED, binding)
    assert typed["state"] == "input_not_empty" and not typed["input_empty"]
    assert typed["reason"] == "existing_input_must_not_be_overwritten"


def test_unrecognized_grok_box_is_unknown_not_existing_input():
    result = assess("grok", REAL_UNKNOWN, SimpleBinding())
    assert result["state"] == "unknown" and not result["input_empty"]
    assert result["reason"] == "unrecognized_grok_composer"


def test_observed_grok_return_is_allowed_only_for_a_current_draft():
    adapter = adapter_for("grok")
    empty = adapter.return_readiness(REAL_EMPTY, SimpleBinding())
    assert not empty["ready"] and empty["reason"] == "empty_grok_composer"
    typed = adapter.return_readiness(REAL_TYPED, SimpleBinding())
    assert typed["ready"] and typed["reason"] == "current_nonempty_composer"
    assert not adapter.return_readiness(REAL_UNKNOWN, SimpleBinding())["ready"]
    busy = adapter.return_readiness(
        "Thinking… esc to interrupt\n" + REAL_TYPED,
        SimpleBinding(),
    )
    assert busy["state"] == "working"


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


async def test_interactive_start_binds_only_a_proven_replacement(visible, config, monkeypatch):
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    install_catalog(monkeypatch, bridge, [new_session()])

    result = await bridge.visible_handoffs.started_binding("chatgpt", "grok", new_session())

    assert result == {
        "state": "bound",
        "target": "grok",
        "pane_id": NEW_PANE,
        "expected_pid": NEW_SHELL,
        "agent_pid": NEW_AGENT,
    }
    assert config.visible_handoffs.bindings["grok"].pane_id == NEW_PANE
    assert json.loads(overlay_path(config).read_text())["grok"]["replaced_pane_id"] == (
        previous.pane_id
    )


async def test_interactive_start_does_not_replace_a_still_live_binding(
    visible, config, monkeypatch
):
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    old = {
        "pane_id": previous.pane_id,
        "expected_pid": previous.expected_pid,
        "agent_pid": previous.agent_pid,
        "agent_candidate": "grok",
        "processes": [{"pid": previous.agent_pid, "name": "grok"}],
    }
    install_catalog(monkeypatch, bridge, [new_session(), old])

    result = await bridge.visible_handoffs.started_binding("chatgpt", "grok", new_session())

    assert result == {"state": "unresolved", "target": "grok"}
    assert config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(config).exists()


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
    transport["text"] = IDLE
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
        transport["text"] = "╭\n│ ❯ │\n╰"
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


@pytest.mark.parametrize("screen,released", [(NONEMPTY, False), (IDLE, True)])
async def test_paste_that_may_have_landed_stays_locked_until_the_input_is_empty(
    visible, screen, released
):
    bridge, transport = visible
    transport["text"] = screen
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
    if released:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
        status = bridge.visible_handoffs.status("chatgpt", "pasted-run")
        assert status["state"] == "unknown" and not transport["calls"]
        assert status["evidence"]["reason"] == "unconfirmed_input_lock_released"
        return
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert exc.value.code in {"visible_target_busy", "visible_input_not_empty"}
    assert not transport["calls"]


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
    transport["text"] = IDLE
    bodies = []

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = "╭\n│ ❯ │\n╰"
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
    transport["text"] = IDLE
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    remember(bridge, previous, state="sent")
    install_catalog(monkeypatch, bridge, [new_session()])

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = "╭\n│ ❯ │\n╰"
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


def _write_rc59_overlay(config, target, original, replacement):
    overlay_path(config).parent.mkdir(parents=True, exist_ok=True)
    overlay_path(config).write_text(
        json.dumps(
            {
                target: {
                    "replaced_pane_id": original.pane_id,
                    "replaced_expected_pid": original.expected_pid,
                    "replaced_agent_pid": original.agent_pid,
                    "pane_id": replacement.pane_id,
                    "expected_pid": replacement.expected_pid,
                    "agent_pid": replacement.agent_pid,
                }
            }
        )
    )


async def test_rc59_generic_overlay_is_reconciled_against_live_original_and_destination(
    visible, monkeypatch
):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["grok"].model_copy(deep=True)
    replacement = original.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    _write_rc59_overlay(bridge.config, "grok", original, replacement)
    unresolved = load_refresh(bridge.config)
    assert unresolved["grok"]["state"] == "legacy_overlay_unverified"
    assert unresolved["grok"]["destination"] == {
        "pane_id": NEW_PANE,
        "expected_pid": NEW_SHELL,
        "agent_pid": NEW_AGENT,
    }
    assert bridge.config.visible_handoffs.bindings["grok"] == original
    bridge.visible_handoffs.refresh_ambiguities = unresolved
    install_catalog(monkeypatch, bridge, [new_session()])

    updated, snapshot = await bridge.visible_handoffs.refreshed_binding("chatgpt", "grok", original)

    assert (updated.pane_id, updated.expected_pid, updated.agent_pid) == (
        NEW_PANE,
        NEW_SHELL,
        NEW_AGENT,
    )
    assert updated.codex_thread_id is None
    assert snapshot == [new_session()]
    assert bridge.visible_handoffs.refresh_ambiguities == {}
    saved = json.loads(overlay_path(bridge.config).read_text())["grok"]
    assert len(saved["replaced_protocol_sha256"]) == 64


async def test_rc59_owner_started_destination_requires_matching_live_lineage(visible, monkeypatch):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["grok"].model_copy(deep=True)
    replacement = original.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    _write_rc59_overlay(bridge.config, "grok", original, replacement)
    install_catalog(monkeypatch, bridge, [new_session()])
    observed = bridge.visible_handoffs.fresh_pair(replacement)
    bridge.visible_handoffs._store_generation(
        "grok", replacement, observed, "owner_started_assignment"
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "grok", original)

    assert (updated.pane_id, updated.expected_pid, updated.agent_pid) == (
        NEW_PANE,
        NEW_SHELL,
        NEW_AGENT,
    )
    assert bridge.visible_handoffs.generation_source(updated, "grok") == (
        "owner_started_assignment"
    )
    assert updated.codex_thread_id is None


async def test_rc59_codex_owner_destination_migrates_only_with_exact_live_lineage(
    visible, monkeypatch
):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/original-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    replacement = original.model_copy(
        update={
            "pane_id": NEW_PANE,
            "expected_pid": NEW_SHELL,
            "agent_pid": NEW_AGENT,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    _write_rc59_overlay(bridge.config, "codex", original, replacement)
    destination = new_session()
    destination["agent_candidate"] = "codex"
    destination["processes"][1]["name"] = "codex"
    destination["processes"][1]["image"] = "/bin/codex"
    install_catalog(monkeypatch, bridge, [destination])

    async def old_target_absent(*_args, **_kwargs):
        raise BridgeError("session_selection_changed", "old Codex target absent")

    monkeypatch.setattr(bridge.sessions, "selected", old_target_absent)
    observed = bridge.visible_handoffs.fresh_pair(replacement)
    bridge.visible_handoffs._store_generation(
        "codex", replacement, observed, "owner_started_assignment"
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", original)

    assert (updated.pane_id, updated.expected_pid, updated.agent_pid) == (
        NEW_PANE,
        NEW_SHELL,
        NEW_AGENT,
    )
    assert updated.codex_thread_id is None and updated.codex_rollout_path is None
    assert bridge.visible_handoffs.generation_source(updated, "codex") == (
        "owner_started_assignment"
    )
    saved = json.loads(overlay_path(bridge.config).read_text())["codex"]
    assert saved["preserve_codex_protocol"] is False


async def test_rc59_codex_protocol_pair_is_ambiguous_and_never_restored_from_overlay(
    visible, monkeypatch
):
    bridge, transport = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    manual = original.model_copy(
        update={
            "codex_thread_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "codex_rollout_path": "/tmp/manual-codex-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = manual
    replacement = manual.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    _write_rc59_overlay(bridge.config, "codex", manual, replacement)
    destination = new_session()
    destination["agent_candidate"] = "codex"
    destination["processes"][1]["name"] = "codex"
    destination["processes"][1]["image"] = "/bin/codex"
    install_catalog(monkeypatch, bridge, [destination])

    async def old_target_absent(*_args, **_kwargs):
        raise BridgeError("session_selection_changed", "old Codex target absent")

    monkeypatch.setattr(bridge.sessions, "selected", old_target_absent)
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", manual)

    assert exc.value.code == "session_selection_changed"
    assert bridge.config.visible_handoffs.bindings["codex"] == manual
    assert bridge.visible_handoffs.presence("codex")["state"] == "ambiguous"
    assert not transport["calls"]


def test_manual_protocol_only_edit_takes_precedence_over_a_fingerprinted_overlay(visible):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/original-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={
            "pane_id": NEW_PANE,
            "expected_pid": NEW_SHELL,
            "agent_pid": NEW_AGENT,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    save_refresh(bridge.config, "codex", original, destination)
    manual = original.model_copy(
        update={
            "codex_thread_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "codex_rollout_path": "/tmp/manual-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = manual

    unresolved = load_refresh(bridge.config)

    assert unresolved["codex"]["state"] == "manual_protocol_binding_precedence"
    assert bridge.config.visible_handoffs.bindings["codex"] == manual


def _codex_session(binding):
    tty = binding.pane_id.rsplit(":", 1)[-1]
    return {
        "pane_id": binding.pane_id,
        "expected_pid": binding.expected_pid,
        "agent_pid": binding.agent_pid,
        "agent_candidate": "codex",
        "identity_ambiguous": False,
        "transport": "terminal_app",
        "tty": "/dev/" + tty,
        "processes": [
            {"pid": binding.expected_pid, "ppid": 1, "name": "-zsh", "image": "/bin/zsh"},
            {
                "pid": binding.agent_pid,
                "ppid": binding.expected_pid,
                "name": "codex",
                "image": "/bin/codex",
            },
        ],
    }


async def test_rc59_codex_overlay_never_adopts_unrelated_owner_session(visible, monkeypatch):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/original-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={
            "pane_id": NEW_PANE,
            "expected_pid": NEW_SHELL,
            "agent_pid": NEW_AGENT,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    _write_rc59_overlay(bridge.config, "codex", original, destination)
    unrelated = original.model_copy(
        update={
            "pane_id": "terminal:303:ttys303",
            "expected_pid": 30300,
            "agent_pid": 30301,
        }
    )
    install_catalog(monkeypatch, bridge, [_codex_session(unrelated)])
    bridge.visible_handoffs._store_generation(
        "codex",
        unrelated,
        bridge.visible_handoffs.fresh_pair(unrelated),
        "owner_started_assignment",
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", original)

    assert exc.value.code == "session_selection_changed"
    assert bridge.config.visible_handoffs.bindings["codex"] == original


async def test_codex_142_to_83_rehome_persists_across_reopen_without_stale_input(
    visible, monkeypatch
):
    bridge, transport = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "pane_id": "terminal:142:ttys000",
            "expected_pid": 973,
            "agent_pid": 1270,
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/stale-codex-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={
            "pane_id": "terminal:83:ttys000",
            "expected_pid": 783,
            "agent_pid": 1073,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    _write_rc59_overlay(bridge.config, "codex", original, destination)
    live = _codex_session(destination)
    install_catalog(monkeypatch, bridge, [live])
    bridge.visible_handoffs._store_generation(
        "codex",
        destination,
        bridge.visible_handoffs.fresh_pair(destination),
        "owner_started_assignment",
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", original)
    assert (updated.pane_id, updated.expected_pid, updated.agent_pid) == (
        "terminal:83:ttys000",
        783,
        1073,
    )
    assert updated.codex_thread_id is None and updated.codex_rollout_path is None

    # Dispatch revalidates the newly bound live generation. There is no pending work,
    # and the previous pane/PID pair is never used as an input destination.
    with pytest.raises(VisibleReadinessError):
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")
    assert not transport["calls"]

    bridge.config.visible_handoffs.bindings["codex"] = original
    reopened = Bridge(bridge.config)
    try:
        restored = reopened.config.visible_handoffs.bindings["codex"]
        assert (restored.pane_id, restored.expected_pid, restored.agent_pid) == (
            "terminal:83:ttys000",
            783,
            1073,
        )
        assert restored.codex_thread_id is None and restored.codex_rollout_path is None
    finally:
        reopened.store.close()


async def test_rc59_codex_exact_owner_destination_allows_parallel_codex(visible, monkeypatch):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/original-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={
            "pane_id": NEW_PANE,
            "expected_pid": NEW_SHELL,
            "agent_pid": NEW_AGENT,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    _write_rc59_overlay(bridge.config, "codex", original, destination)
    parallel = original.model_copy(
        update={
            "pane_id": "terminal:303:ttys303",
            "expected_pid": 30300,
            "agent_pid": 30301,
        }
    )
    install_catalog(monkeypatch, bridge, [_codex_session(destination), _codex_session(parallel)])
    bridge.visible_handoffs._store_generation(
        "codex",
        destination,
        bridge.visible_handoffs.fresh_pair(destination),
        "owner_started_assignment",
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", original)

    assert (updated.pane_id, updated.expected_pid, updated.agent_pid) == (
        NEW_PANE,
        NEW_SHELL,
        NEW_AGENT,
    )
    assert updated.codex_thread_id is None and updated.codex_rollout_path is None
    assert bridge.visible_handoffs.generation_source(updated, "codex") == (
        "owner_started_assignment"
    )


async def test_rc59_overlay_preserves_exact_live_manual_original(visible, monkeypatch):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "codex_rollout_path": "/tmp/manual-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    _write_rc59_overlay(bridge.config, "codex", original, destination)
    install_catalog(monkeypatch, bridge, [_codex_session(original)])
    bridge.visible_handoffs._store_generation(
        "codex", original, bridge.visible_handoffs.fresh_pair(original), "exact_match_bootstrap"
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)

    updated, snapshot = await bridge.visible_handoffs.refreshed_binding(
        "chatgpt", "codex", original
    )

    assert updated == original
    assert snapshot is None
    assert not overlay_path(bridge.config).exists()
    assert bridge.visible_handoffs.refresh_ambiguities == {}


async def test_rc59_live_original_retention_does_not_clear_concurrent_assignment(
    visible, monkeypatch
):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "codex_rollout_path": "/tmp/manual-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    old_destination = original.model_copy(
        update={"pane_id": NEW_PANE, "expected_pid": NEW_SHELL, "agent_pid": NEW_AGENT}
    )
    _write_rc59_overlay(bridge.config, "codex", original, old_destination)
    install_catalog(monkeypatch, bridge, [_codex_session(original)])
    bridge.visible_handoffs._store_generation(
        "codex", original, bridge.visible_handoffs.fresh_pair(original), "exact_match_bootstrap"
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)
    newer = original.model_copy(
        update={
            "pane_id": "terminal:404:ttys404",
            "expected_pid": 40400,
            "agent_pid": 40401,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )

    async def catalog_with_concurrent_assignment(principal):
        bridge.config.visible_handoffs.bindings["codex"] = newer
        save_refresh(bridge.config, "codex", original, newer)
        return {"status": "available", "sessions": [_codex_session(original)]}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog_with_concurrent_assignment)

    updated, snapshot = await bridge.visible_handoffs.refreshed_binding(
        "chatgpt", "codex", original
    )

    assert updated == newer
    assert snapshot is None
    saved = json.loads(overlay_path(bridge.config).read_text())["codex"]
    assert saved["pane_id"] == newer.pane_id
    assert bridge.visible_handoffs.refresh_ambiguities["codex"]["state"] == (
        "legacy_overlay_unverified"
    )


async def test_rc59_destination_is_not_committed_if_original_reappears_finally(
    visible, monkeypatch
):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(
        update={
            "codex_thread_id": "01234567-0123-4567-89ab-0123456789ab",
            "codex_rollout_path": "/tmp/original-rollout.jsonl",
        }
    )
    bridge.config.visible_handoffs.bindings["codex"] = original
    destination = original.model_copy(
        update={
            "pane_id": NEW_PANE,
            "expected_pid": NEW_SHELL,
            "agent_pid": NEW_AGENT,
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )
    _write_rc59_overlay(bridge.config, "codex", original, destination)
    destination_session = _codex_session(destination)
    original_session = _codex_session(original)
    install_catalog(monkeypatch, bridge, [destination_session])
    bridge.visible_handoffs._store_generation(
        "codex",
        destination,
        bridge.visible_handoffs.fresh_pair(destination),
        "owner_started_assignment",
    )
    bridge.visible_handoffs.refresh_ambiguities = load_refresh(bridge.config)
    calls = 0

    async def original_reappears_in_final_catalog(principal):
        nonlocal calls
        calls += 1
        rows = [destination_session]
        if calls == 2:
            rows.append(original_session)
        return {"status": "available", "sessions": rows}

    monkeypatch.setattr(bridge.sessions, "catalog", original_reappears_in_final_catalog)

    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.refreshed_binding("chatgpt", "codex", original)

    assert exc.value.code == "session_selection_changed"
    assert bridge.config.visible_handoffs.bindings["codex"] == original
    assert bridge.visible_handoffs.presence("codex")["state"] == "ambiguous"
