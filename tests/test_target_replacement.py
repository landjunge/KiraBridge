"""Owner-only exact replacement, same-generation re-home and lifecycle reporting (M2, S).

The strict absence proof, reservations and UNKNOWN history stay unchanged. Only OS
observations (catalog, PID/window inventory, kernel generations) are simulated.
Reservation fixtures are linked to real messages (``remember``).
"""

# ruff: noqa: F811
import json
import sqlite3

import pytest
from test_process_lifecycle import catalog_only, gen, gens, native
from test_visible_binding_refresh import remember
from test_visible_handoff import callback, visible  # noqa: F401

import kirabridge.visible_handoff as visible_module
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.visible_binding import overlay_path
from kirabridge.visible_handoff import peer_route_status

NEW = ("terminal:2767:ttys000", 45159, 45186)
OWNER = "local"


def started_row(pane=NEW[0], shell=NEW[1], agent=NEW[2], tty="/dev/ttys000", **extra):
    return {
        "pane_id": pane,
        "expected_pid": shell,
        "agent_pid": agent,
        "agent_candidate": "grok",
        "tty": tty,
        "transport": "terminal_app",
        "identity_ambiguous": False,
        "processes": [
            {"pid": shell, "ppid": 1, "name": "zsh"},
            {"pid": agent, "ppid": shell, "name": "grok"},
        ],
        **extra,
    }


def kernel(bridge, births=None):
    births = births if births is not None else {}

    def observe(pids):
        return {pid: gen(pid, births.get(pid, f"{pid}.000001")) for pid in pids}

    bridge.visible_handoffs.generation_observer = observe


def grant(bridge, principal):
    caps = bridge.config.principals[principal].capabilities
    for capability in ("session.open", "terminal.execute", "session.inspect"):
        if capability not in caps:
            caps.append(capability)


def history(bridge):
    tables = ("visible_handoffs", "visible_handoff_events", "messages", "message_jobs")
    db = bridge.store.db
    return {
        table: [tuple(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in tables
    }


def refused_reasons(bridge):
    return [
        json.loads(row[0])["reason"]
        for row in bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='visible_binding_assignment_refused'"
        )
    ]


def triple(binding):
    return (binding.pane_id, binding.expected_pid, binding.agent_pid)


def setup(bridge, monkeypatch, sessions):
    grant(bridge, OWNER)
    catalog_only(monkeypatch, bridge, sessions)
    native(bridge, pids={1, 123, NEW[1], NEW[2]}, windows=[2767])  # old shell PID occupied
    kernel(bridge)


# --- owner-started assignment ---------------------------------------------------


async def test_owner_started_receiver_breaks_581_trap_with_byte_same_history(
    visible, config, monkeypatch
):
    bridge, transport = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    remember(bridge, previous, state="unknown")
    row = started_row()
    setup(bridge, monkeypatch, [row])
    before = history(bridge)

    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)

    assert result["state"] == "bound" and result["mode"] == "owner_started_assignment"
    current = config.visible_handoffs.bindings["grok"]
    assert triple(current) == NEW and current.codex_thread_id is None
    assert bridge.visible_handoffs.generation_source(current, "grok") == (
        "owner_started_assignment"
    )
    assert bridge.visible_handoffs.recorded_generations(previous, "grok") is None
    presence = bridge.visible_handoffs.presence("grok")
    assert presence["state"] == "replaced"
    assert presence["evidence"]["previous_identity"] == "unverified_legacy"
    assert history(bridge) == before and not transport["calls"]
    config.visible_handoffs.bindings["grok"] = previous
    reopened = Bridge(config)
    try:
        restored = reopened.config.visible_handoffs.bindings["grok"]
        assert triple(restored) == NEW
        assert reopened.visible_handoffs.recorded_generations(restored, "grok")  # anchored
    finally:
        reopened.store.close()


async def test_remote_start_with_open_capabilities_never_reassigns(visible, config, monkeypatch):
    """ChatGPT holds session.open/terminal.execute; that is not receiver ownership."""
    bridge, transport = visible
    grant(bridge, "chatgpt")
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    row = started_row()
    setup(bridge, monkeypatch, [row])
    before = history(bridge)
    result = await bridge.visible_handoffs.started_binding("chatgpt", "grok", row)
    assert result == {"state": "unresolved", "target": "grok"}
    assert config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(config).exists()
    updated = previous.model_copy(
        update={"pane_id": NEW[0], "expected_pid": NEW[1], "agent_pid": NEW[2]}
    )
    assert bridge.visible_handoffs.recorded_generations(updated, "grok") is None
    assert history(bridge) == before and not transport["calls"]


async def test_launch_refresh_never_adopts_a_different_live_same_cli(visible, config, monkeypatch):
    """Compatibility path: a proven-dead refresh may adopt only the launched handle."""
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    launched = {**started_row(), "agent_candidate": None}  # not the unique candidate
    other = started_row(pane="terminal:3000:ttys004", shell=9, agent=10, tty="/dev/ttys004")
    catalog_only(monkeypatch, bridge, [launched, other])
    native(bridge, pids={1, NEW[1], NEW[2], 9, 10}, windows=[2767, 3000])  # old proven gone
    result = await bridge.visible_handoffs.started_binding("chatgpt", "grok", launched)
    assert result == {"state": "unresolved", "target": "grok"}
    assert config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(config).exists()


@pytest.mark.parametrize(
    "case",
    [
        "old_target_still_present",
        "active_reservation",
        "owner_authority_required",
        "generation_unverifiable",
        "catalog_incomplete",
        "candidate_not_in_catalog",
        "started_handle_not_exact",
        "handle_assigned_to_other_target",
    ],
)
async def test_owner_assignment_refuses_unless_exact_and_uncontested(
    visible, config, monkeypatch, case
):
    bridge, transport = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    row = started_row()
    sessions = [row]
    if case == "old_target_still_present":
        sessions.append(
            {
                "pane_id": "terminal:900:ttys009",
                "expected_pid": 9000,
                "tty": "/dev/ttys009",
                "processes": [{"pid": 456, "ppid": 9000, "name": "grok"}],
            }
        )
    elif case == "handle_assigned_to_other_target":
        row = started_row(agent=457)  # codex's configured agent PID
        sessions = [row]
    elif case == "started_handle_not_exact":
        row = {**row, "selection_ambiguous": True}
        sessions = [row]
    setup(bridge, monkeypatch, sessions)
    if case == "active_reservation":
        remember(bridge, previous, state="sent")
    elif case == "owner_authority_required":
        bridge.config.principals[OWNER].capabilities.remove("session.open")
    elif case == "generation_unverifiable":
        bridge.visible_handoffs.generation_observer = lambda pids: None
    elif case in {"catalog_incomplete", "candidate_not_in_catalog"}:

        async def catalog(principal, *, transport=None):
            if case == "catalog_incomplete":
                return {"status": "available", "truncated": True, "sessions": [row]}
            return {"status": "available", "sessions": []}

        monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    before = history(bridge)

    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)

    assert result == {"state": "unresolved", "target": "grok"}
    assert config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(config).exists()
    assert history(bridge) == before
    assert refused_reasons(bridge) == [case]
    assert not transport["calls"]


@pytest.mark.parametrize(
    "change",
    [
        "candidate_changed",
        "binding_changed",
        "generation_changed",
        "active_reservation",
        "owner_authority_required",
    ],
)
async def test_change_during_catalog_await_stops_before_persisting(
    visible, config, monkeypatch, change
):
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    row = started_row()
    setup(bridge, monkeypatch, [row])
    original_catalog = bridge.sessions.catalog
    original_selected = bridge.sessions.selected
    state = {"after": False}

    async def catalog(principal, *, transport=None):
        result = await original_catalog(principal, transport=transport)
        state["after"] = True
        if change == "binding_changed":
            bridge.config.visible_handoffs.bindings["grok"] = previous.model_copy(
                update={"pane_id": "terminal:4000:ttys007", "expected_pid": 70, "agent_pid": 71}
            )
        elif change == "generation_changed":
            kernel(bridge, {NEW[2]: "999.000001"})  # agent PID number reused meanwhile
        elif change == "active_reservation":
            remember(bridge, previous, state="planned")
        elif change == "owner_authority_required":
            bridge.config.principals[OWNER].capabilities.remove("terminal.execute")
        return result

    async def selected(principal, pane, pid):
        found = await original_selected(principal, pane, pid)
        if change == "candidate_changed" and state["after"]:
            found = {**found, "tty": "/dev/ttys099"}
        return found

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "selected", selected)
    expected_binding = (
        bridge.config.visible_handoffs.bindings["grok"] if change != "binding_changed" else None
    )
    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)
    assert result == {"state": "unresolved", "target": "grok"}
    assert refused_reasons(bridge) == [change]
    assert not overlay_path(config).exists()
    if expected_binding is not None:
        assert config.visible_handoffs.bindings["grok"] == expected_binding
    assert triple(config.visible_handoffs.bindings["grok"]) != NEW


async def test_parallel_same_cli_binds_only_the_launched_handle(visible, config, monkeypatch):
    bridge, _ = visible
    launched = started_row()
    other = started_row(pane="terminal:3000:ttys004", shell=9, agent=10, tty="/dev/ttys004")
    setup(bridge, monkeypatch, [launched, other])
    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", launched)
    assert result["state"] == "bound"
    current = config.visible_handoffs.bindings["grok"]
    assert triple(current) == NEW
    untouched = current.model_copy(
        update={"pane_id": other["pane_id"], "expected_pid": 9, "agent_pid": 10}
    )
    assert bridge.visible_handoffs.recorded_generations(untouched, "grok") is None


# --- persistence order and faults ---------------------------------------------------


async def test_overlay_failure_keeps_mapping_and_leaves_only_inert_lineage(
    visible, config, monkeypatch
):
    bridge, transport = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    remember(bridge, previous, state="unknown")
    row = started_row()
    setup(bridge, monkeypatch, [row])
    before = history(bridge)
    real_save = visible_module.save_refresh

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(visible_module, "save_refresh", fail)
    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)
    assert result == {"state": "unresolved", "target": "grok"}
    assert refused_reasons(bridge) == ["overlay_write_failed"]
    assert config.visible_handoffs.bindings["grok"] == previous  # RAM not published
    assert not overlay_path(config).exists()
    assert bridge.visible_handoffs.presence("grok")["state"] != "replaced"
    assert history(bridge) == before
    # Crash-recovery: the inert ledger row is reused identically on the next owner try.
    monkeypatch.setattr(visible_module, "save_refresh", real_save)
    again = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)
    assert again["state"] == "bound" and triple(config.visible_handoffs.bindings["grok"]) == NEW
    assert history(bridge) == before and not transport["calls"]


async def test_ledger_failure_writes_no_overlay_and_no_mapping(visible, config, monkeypatch):
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    row = started_row()
    setup(bridge, monkeypatch, [row])

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bridge.visible_handoffs, "_store_generation", fail)
    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)
    assert result == {"state": "unresolved", "target": "grok"}
    assert refused_reasons(bridge) == ["lineage_write_failed"]
    assert config.visible_handoffs.bindings["grok"] == previous
    assert not overlay_path(config).exists()


async def test_existing_different_lineage_is_never_overwritten(visible, config, monkeypatch):
    bridge, _ = visible
    previous = config.visible_handoffs.bindings["grok"].model_copy()
    row = started_row()
    setup(bridge, monkeypatch, [row])
    new = previous.model_copy(
        update={"pane_id": NEW[0], "expected_pid": NEW[1], "agent_pid": NEW[2]}
    )
    stale = {NEW[1]: gen(NEW[1], "1.000001"), NEW[2]: gen(NEW[2], "2.000002")}
    bridge.visible_handoffs._store_generation("grok", new, stale, "exact_match_bootstrap")
    saved = bridge.store.db.execute("SELECT * FROM binding_generations").fetchall()
    result = await bridge.visible_handoffs.started_binding(OWNER, "grok", row)
    assert result == {"state": "unresolved", "target": "grok"}
    assert refused_reasons(bridge) == ["lineage_conflict"]
    assert [tuple(r) for r in bridge.store.db.execute("SELECT * FROM binding_generations")] == [
        tuple(r) for r in saved
    ]
    assert config.visible_handoffs.bindings["grok"] == previous


# --- same-generation re-home (tab move / window merge) ----------------------------


def moved_row(pane="terminal:555:ttys001", **extra):
    return {
        "pane_id": pane,
        "expected_pid": 123,
        "tty": "/dev/ttys001",
        "transport": "terminal_app",
        "identity_ambiguous": False,
        "processes": [
            {"pid": 123, "ppid": 1, "name": "zsh"},
            {"pid": 456, "ppid": 123, "name": "grok"},
        ],
        **extra,
    }


def record_old(bridge):
    binding = bridge.config.visible_handoffs.bindings["grok"]
    bridge.visible_handoffs._store_generation("grok", binding, gens(), "exact_match_bootstrap")
    return binding.model_copy()


async def test_moved_tab_with_equal_generation_is_rehomed_and_reservation_stays_locked(
    visible, monkeypatch
):
    bridge, transport = visible
    previous = record_old(bridge)
    remember(bridge, previous, state="sent")
    before = history(bridge)
    catalog_only(monkeypatch, bridge, [moved_row()])
    bridge.visible_handoffs.generation_observer = lambda pids: gens()
    updated, snapshot = await bridge.visible_handoffs.refreshed_binding("chatgpt", "grok", previous)
    assert updated.pane_id == "terminal:555:ttys001"
    assert (updated.expected_pid, updated.agent_pid) == (123, 456)
    assert snapshot is None
    assert bridge.visible_handoffs.presence("grok")["state"] == "rehomed"
    assert peer_route_status(bridge, bridge.config, "grok")["known_ready"] is False
    assert bridge.visible_handoffs.generation_source(updated, "grok") == "exact_match_bootstrap"
    assert history(bridge) == before and not transport["calls"]
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.reconcile_target_reservations(
            "chatgpt", "grok", updated, observed_sessions=None
        )
    assert error.value.code == "visible_target_busy"
    assert history(bridge) == before


@pytest.mark.parametrize(
    "case",
    [
        "changed_generation",
        "legacy_unrecorded",
        "two_tty_rows",
        "corrupted_processes",
        "reselect_ambiguous",
        "generation_changes_on_reselect",
        "overlay_failure",
    ],
)
async def test_move_without_exact_equal_lineage_is_not_rehomed(visible, monkeypatch, case):
    bridge, _ = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    if case != "legacy_unrecorded":
        record_old(bridge)
    sessions = [moved_row()]
    if case == "two_tty_rows":
        sessions.append({**moved_row("terminal:556:ttys001"), "expected_pid": 777})
    elif case == "corrupted_processes":
        sessions.append({"pane_id": "terminal:557:ttys005", "processes": "garbage"})
    catalog_only(monkeypatch, bridge, sessions)
    native(bridge, pids={1, 123, 456}, windows=[555, 556])
    calls = {"n": 0}

    def observe(pids):
        calls["n"] += 1
        if case == "changed_generation" or (
            case == "generation_changes_on_reselect" and calls["n"] > 2
        ):
            return gens(agent_birth="999.000001")
        return gens()

    bridge.visible_handoffs.generation_observer = observe
    if case == "reselect_ambiguous":

        async def selected(principal, pane, pid):
            if pane == "terminal:555:ttys001":
                return moved_row(identity_ambiguous=True)
            raise BridgeError("session_selection_changed", "pane missing")

        monkeypatch.setattr(bridge.sessions, "selected", selected)
    if case == "overlay_failure":

        def fail(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(visible_module, "save_refresh", fail)
    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "grok", previous)
    assert updated == previous
    assert bridge.config.visible_handoffs.bindings["grok"] == previous
    assert bridge.visible_handoffs.presence("grok")["state"] == "stale"


# --- lifecycle reporting -------------------------------------------------------------


@pytest.mark.parametrize(
    ("processes", "lifecycle"),
    [
        ([{"pid": 999, "name": "grok"}], "agent_restarted_new_process"),
        ([], "agent_exited"),
        ([{"pid": 998, "name": "codex"}], "agent_switched"),
        ([{"pid": 456, "name": "vim"}], "agent_pid_now_other_program"),
    ],
)
async def test_same_tab_change_is_named_and_never_rebound(
    visible, monkeypatch, processes, lifecycle
):
    bridge, transport = visible
    previous = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    same_tab = {
        "pane_id": previous.pane_id,
        "expected_pid": previous.expected_pid,
        "tty": "/dev/ttys001",
        "processes": [{"pid": 123, "name": "zsh"}, *processes],
    }
    catalog_only(monkeypatch, bridge, [same_tab])
    native(bridge, pids={1, 123}, windows=[100])
    updated, _ = await bridge.visible_handoffs.refreshed_binding("chatgpt", "grok", previous)
    assert updated == previous
    assert bridge.visible_handoffs.presence("grok")["evidence"]["lifecycle"] == lifecycle
    assert not transport["calls"]


# --- effect point ------------------------------------------------------------------------


def test_effect_guard_refuses_changed_or_unverifiable_recorded_lineage(visible):
    bridge, _ = visible
    handoffs = bridge.visible_handoffs
    binding = bridge.config.visible_handoffs.bindings["grok"]
    assert handoffs.effect_generation_guard("grok", binding) == "unverified"  # legacy route
    record_old(bridge)
    handoffs.generation_observer = lambda pids: gens()
    assert handoffs.effect_generation_guard("grok", binding) == "verified"
    handoffs.generation_observer = lambda pids: gens(agent_birth="999.000001")
    with pytest.raises(BridgeError) as error:
        handoffs.effect_generation_guard("grok", binding)
    assert error.value.observation["reason"] == "process_generation_changed"

    def broken(pids):
        raise OSError("libproc unavailable")

    handoffs.generation_observer = broken
    with pytest.raises(BridgeError) as error:
        handoffs.effect_generation_guard("grok", binding)
    assert error.value.observation["reason"] == "process_generation_unverifiable"
    assert handoffs.recorded_generations(binding, "codex") is None


def test_clock_stepping_back_never_keeps_an_observation_fresh(visible):
    import time

    bridge, _ = visible
    grok = bridge.config.visible_handoffs.bindings["grok"]
    bridge.visible_handoffs.record_presence(
        "chatgpt", "grok", "available", grok, {"reason": "matched"}
    )
    bridge.store.db.execute(
        "UPDATE receiver_presence SET observed_at=? WHERE target='grok'", (time.time() + 3600,)
    )
    assert peer_route_status(bridge, bridge.config, "grok")["state"] == "observation_aged"
