"""Strict legacy absence proof stays unchanged; kernel generation is equality-only.

Acceptance A1-A7 of docs/LIFECYCLE-ACCEPTANCE-20261123.md. The real
prove_original_target_gone runs; only OS observations and the catalog are faked,
except the marked real-OS generation checks (class L on the executing host).
"""

# Imported fixtures are used through pytest's dependency injection.
# ruff: noqa: F811
import json
import os
import sys
import time
from types import SimpleNamespace

import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.process_lifecycle import (
    boot_identity,
    fresh_generations,
    process_generation,
    same_generation,
)
from kirabridge.visible_handoff import PRESENCE_FRESH_SECONDS, peer_route_status

NATIVE_OS = sys.platform == "darwin" or sys.platform.startswith("linux")


BOOT_A = "6f1c2a9e-0000-4000-8000-00000000000a"
BOOT_B = "6f1c2a9e-0000-4000-8000-00000000000b"


def gen(pid, birth, boot=BOOT_A):
    return {"boot": boot, "pid": pid, "birth": birth, "ppid": 1, "pgid": pid, "uid": 501}


def gens(shell_birth="100.000001", agent_birth="200.000002", boot=BOOT_A):
    return {123: gen(123, shell_birth, boot), 456: gen(456, agent_birth, boot)}


# --- kernel generation (pure) -------------------------------------------------


def test_generation_equality_uses_only_immutable_kernel_facts():
    assert same_generation(gen(1, "5.000001"), {**gen(1, "5.000001"), "ppid": 9, "pgid": 3})
    assert not same_generation(gen(1, "5.000001"), gen(1, "5.000002"))
    assert not same_generation(gen(1, "5.000001"), gen(1, "5.000001", boot=BOOT_B))
    assert not same_generation(gen(1, "5.000001"), gen(2, "5.000001"))
    assert not same_generation(None, gen(1, "5"))
    assert not same_generation({"pid": 1, "birth": "5", "boot": None}, gen(1, "5"))
    assert same_generation(gen(1, "5"), gen(1, "5"))  # Linux: integer clock ticks


@pytest.mark.parametrize(
    "broken",
    [
        {"pid": True},
        {"pid": "1"},
        {"pid": 0},
        {"birth": 5},
        {"birth": "0"},
        {"birth": "0.000000"},
        {"birth": "5.1"},
        {"birth": "-5"},
        {"boot": "short"},
        {"boot": "x" * 65},
        {"boot": None},
    ],
)
def test_structurally_invalid_generation_never_compares_equal(broken):
    value = {**gen(1, "5.000001"), **broken}
    assert not same_generation(value, value)


@pytest.mark.skipif(not NATIVE_OS, reason="no trusted kernel adapter on this platform")
def test_real_kernel_generation_of_own_process_is_stable():
    """Class L: real libproc / procfs on the executing host."""
    boot = boot_identity()
    assert boot
    first = process_generation(os.getpid())
    assert first["pid"] == os.getpid() and first["ppid"] == os.getppid()
    assert first["boot"] == boot and first["uid"] == os.getuid()
    assert same_generation(first, process_generation(os.getpid()))
    assert process_generation(0) is None and process_generation(-1) is None
    assert fresh_generations([os.getpid(), 2**31 - 2]) is None  # one unverifiable -> none


@pytest.mark.skipif(not NATIVE_OS, reason="no trusted kernel adapter on this platform")
def test_wall_clock_step_does_not_change_generation(monkeypatch):
    """Reviewer reproduction: a 100 s wall-clock correction must not alter identity."""
    before = process_generation(os.getpid())
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 100)
    assert same_generation(before, process_generation(os.getpid()))


# --- effect-point verification ------------------------------------------------


def test_first_fresh_match_records_then_requires_equality(visible):
    bridge, _ = visible
    handoffs = bridge.visible_handoffs
    binding = bridge.config.visible_handoffs.bindings["grok"]
    assert handoffs.verify_generation("grok", binding, gens(), gens()) == "verified"
    assert handoffs.recorded_generations(binding)[123]["birth"] == "100.000001"
    assert handoffs.verify_generation("grok", binding, gens(), gens()) == "verified"
    with pytest.raises(BridgeError) as error:
        handoffs.verify_generation(
            "grok", binding, gens(shell_birth="900.000000"), gens(shell_birth="900.000000")
        )
    assert error.value.code == "visible_target_changed"
    assert error.value.observation["reason"] == "process_generation_changed"
    with pytest.raises(BridgeError) as error:
        handoffs.verify_generation("grok", binding, None, gens())
    assert error.value.code == "visible_target_unknown"


def test_wall_clock_step_keeps_recorded_generation_verified(visible, monkeypatch):
    bridge, _ = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    bridge.visible_handoffs.verify_generation("grok", binding, gens(), gens())
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() - 100)
    assert bridge.visible_handoffs.verify_generation("grok", binding, gens(), gens()) == (
        "verified"
    )


@pytest.mark.parametrize("case", ["unobservable", "changed_during_match"])
def test_legacy_or_unfresh_observation_is_unverified_and_not_recorded(visible, case):
    bridge, _ = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    before, after = (None, None) if case == "unobservable" else (gens(), gens("101.000000"))
    assert bridge.visible_handoffs.verify_generation("grok", binding, before, after) == (
        "unverified"
    )
    assert bridge.visible_handoffs.recorded_generations(binding) is None


async def test_check_target_refuses_same_pid_with_new_generation(visible, monkeypatch):
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    native_row = {
        "pane_id": binding.pane_id,
        "expected_pid": binding.expected_pid,
        "transport": "terminal_app",
        "tty": "/dev/ttys001",
        "processes": [{"pid": binding.agent_pid, "name": "grok"}],
        "busy": True,
    }

    async def selected(principal, pane, pid):
        return dict(native_row)

    current = {"value": gens()}
    monkeypatch.setattr(bridge.sessions, "selected", selected)
    bridge.visible_handoffs.generation_observer = lambda pids: current["value"]
    await bridge.visible_handoffs.check_target("chatgpt", "grok", binding)
    assert bridge.visible_handoffs.recorded_generations(binding) is not None
    current["value"] = gens(agent_birth="777.000001")  # agent PID number reused
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.check_target("chatgpt", "grok", binding)
    assert error.value.code == "visible_target_changed"
    assert not transport["calls"]


async def test_non_native_rows_are_never_recorded(visible):
    """Fixture rows without a native transport are not an OS observation."""
    bridge, _ = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    bridge.visible_handoffs.generation_observer = lambda pids: gens()
    await bridge.visible_handoffs.check_target("chatgpt", "grok", binding)
    assert bridge.visible_handoffs.recorded_generations(binding) is None


# --- strict legacy proof unchanged; precise reporting --------------------------


def native(bridge, *, pids, windows=()):
    async def process_ids():
        return frozenset(pids)

    async def window_inventory():
        return {
            "running": True,
            "windows": [{"window_id": w, "ttys": ["/dev/ttys009"]} for w in windows],
        }

    bridge.sessions.terminal_app = SimpleNamespace(
        available=True, process_ids=process_ids, window_inventory=window_inventory
    )


def catalog_only(monkeypatch, bridge, sessions):
    async def selected(principal, pane, pid):
        for row in sessions:
            if row["pane_id"] == pane and row["expected_pid"] == pid:
                return dict(row)
        error = BridgeError("session_selection_changed", "pane missing")
        error.provider_error = {"reason": "pane_missing", "sessions": len(sessions)}
        raise error

    async def catalog(principal, *, transport=None):
        return {"status": "available", "sessions": [dict(row) for row in sessions]}

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)


async def test_recorded_generation_does_not_relax_strict_absence_proof(visible):
    bridge, _ = visible
    binding = bridge.config.visible_handoffs.bindings["grok"]
    bridge.visible_handoffs.verify_generation("grok", binding, gens(), gens())
    native(bridge, pids={1, 123}, windows=[7])
    with pytest.raises(BridgeError) as error:
        await bridge.sessions.prove_original_target_gone("chatgpt", binding.model_dump())
    assert error.value.code == "visible_absence_unproven"
    assert getattr(error.value, "provider_error", None) is None  # old evidence shape


async def test_581_shape_is_reported_stale_and_requires_new_assignment(visible, monkeypatch):
    """Window gone, agent PID gone, shell PID number held by a tty-less foreign process."""
    bridge, transport = visible
    binding = bridge.config.visible_handoffs.bindings["grok"].model_copy()
    catalog_only(monkeypatch, bridge, [])
    native(bridge, pids={1, 123}, windows=[7])
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert error.value.code == "session_selection_changed"
    assert error.value.observation == {
        "state": "stale",
        "reason": "visible_absence_unproven",
        "target": "grok",
    }
    evidence = bridge.visible_handoffs.presence("grok")["evidence"]
    assert evidence["identity"] == "unverified_legacy"
    assert evidence["remedy"] == "new_exact_assignment_required"
    assert evidence["selection_reason"] == "pane_missing"
    assert bridge.config.visible_handoffs.bindings["grok"] == binding
    assert not transport["calls"]


async def test_proven_absent_without_replacement_is_reported_absent(visible, monkeypatch):
    bridge, transport = visible
    catalog_only(monkeypatch, bridge, [])
    native(bridge, pids={1}, windows=[7])
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert error.value.code == "session_selection_changed"
    assert error.value.observation["state"] == "absent"
    assert error.value.observation["reason"] == "original_target_gone_no_replacement"
    assert not transport["calls"]


async def test_sweeper_records_presence_without_changing_its_skip_rule(visible, monkeypatch):
    bridge, transport = visible
    grok = bridge.config.visible_handoffs.bindings["grok"]
    live_grok = {
        "pane_id": grok.pane_id,
        "expected_pid": grok.expected_pid,
        "processes": [{"pid": grok.agent_pid, "name": "grok"}],
    }
    catalog_only(monkeypatch, bridge, [live_grok])
    native(bridge, pids={1, 124, 123, 456}, windows=[100])  # codex shell PID occupied
    assert await bridge.refresh_agent_bindings_once("chatgpt") == []
    assert bridge.visible_handoffs.presence("grok")["state"] == "available"
    codex = bridge.visible_handoffs.presence("codex")
    assert codex["state"] == "stale" and codex["evidence"]["identity"] == "unverified_legacy"
    assert not transport["calls"]


# --- sender-facing sanitized status --------------------------------------------


def test_peer_route_status_is_sanitized_and_never_ready(visible):
    bridge, _ = visible
    config = bridge.config
    grok = config.visible_handoffs.bindings["grok"]
    assert peer_route_status(bridge, config, "grok")["state"] == "unknown"
    bridge.visible_handoffs.record_presence(
        "chatgpt", "grok", "available", grok, {"reason": "matched"}
    )
    fresh = peer_route_status(bridge, config, "grok")
    assert fresh["state"] == "available" and fresh["known_ready"] is False
    bridge.store.db.execute(
        "UPDATE receiver_presence SET observed_at=? WHERE target='grok'",
        (time.time() - PRESENCE_FRESH_SECONDS - 1,),
    )
    assert peer_route_status(bridge, config, "grok")["state"] == "observation_aged"
    bridge.visible_handoffs.record_presence(
        "chatgpt",
        "grok",
        "stale",
        grok,
        {"reason": "visible_absence_unproven", "remedy": "new_exact_assignment_required"},
    )
    stale = peer_route_status(bridge, config, "grok")
    assert stale["state"] == "stale" and stale["remedy"] == "new_exact_assignment_required"
    text = json.dumps(stale)
    assert grok.pane_id not in text and str(grok.agent_pid) not in text
    assert peer_route_status(bridge, config, "nobody")["state"] == "not_applicable"
