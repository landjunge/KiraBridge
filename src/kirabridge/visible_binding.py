"""Refresh a dead visible-agent binding without replaying an old handoff.

A configured pane/PID pair is stale once that pane and both PIDs are absent
from a fresh catalog and exactly one unambiguous live session runs the same
agent. The old handoff row stays untouched. A live or ambiguous process is
never replaced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kirabridge.bridge_core.config import VisibleTerminalBinding

OVERLAY_NAME = "visible-binding-refresh.json"


def overlay_path(config) -> Path:
    return Path(config.data_dir) / OVERLAY_NAME


def binding_still_present(binding, sessions) -> bool:
    """True when this pane or either saved PID is still in the fresh catalog."""
    pids = {binding.expected_pid, binding.agent_pid}
    for row in sessions:
        if row.get("pane_id") == binding.pane_id:
            return True
        observed = {row.get("expected_pid"), row.get("legacy_expected_pid")}
        observed.update(process.get("pid") for process in row.get("processes", []))
        if pids & observed:
            return True
    return False


def unique_live_agent(target, sessions):
    """The only unambiguous catalog row for this agent, or None."""
    rows = []
    for row in sessions:
        if row.get("agent_candidates_ambiguous") or row.get("identity_ambiguous"):
            continue
        if row.get("agent_candidate") != target:
            continue
        pane_id = row.get("pane_id")
        expected_pid = row.get("expected_pid")
        agent_pid = row.get("agent_pid")
        if (
            isinstance(pane_id, str)
            and pane_id.startswith("terminal:")
            and isinstance(expected_pid, int)
            and expected_pid > 0
            and isinstance(agent_pid, int)
            and agent_pid > 0
            and expected_pid != agent_pid
        ):
            rows.append(row)
    if len(rows) != 1:
        return None
    return rows[0]


def identities_disjoint(original, current) -> bool:
    """Different window and tty. A reused tty or the same window stays locked."""
    try:
        old, new = original.pane_id.split(":"), current.pane_id.split(":")
    except AttributeError:
        return False
    return (
        len(old) == len(new) == 3
        and old[0] == new[0] == "terminal"
        and old[1] != new[1]
        and old[2] != new[2]
        and original.expected_pid > 0
        and original.agent_pid > 0
        and {original.expected_pid, original.agent_pid}.isdisjoint(
            {current.expected_pid, current.agent_pid}
        )
    )


def overlay_replaced(config, target, original) -> bool:
    """True when this exact pane/PID pair was the one a proven refresh replaced."""
    path = overlay_path(config)
    if not path.is_file():
        return False
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    item = saved.get(target) if isinstance(saved, dict) else None
    return (
        isinstance(item, dict)
        and item.get("replaced_pane_id") == original.pane_id
        and item.get("replaced_expected_pid") == original.expected_pid
        and item.get("replaced_agent_pid") == original.agent_pid
    )


def catalog_can_replace(catalog) -> bool:
    """A partial tab list is not proof that every other agent window is absent."""
    if not isinstance(catalog, dict) or catalog.get("status") != "available":
        return False
    if catalog.get("truncated") or catalog.get("incomplete"):
        return False
    errors = catalog.get("transport_errors") or {}
    if not isinstance(errors, dict):
        return False
    return "terminal_app" not in errors


def foreign_dead_reservation(original, current, sessions) -> bool:
    """An old reservation on a proven-dead pane must not lock a different live one."""
    return identities_disjoint(original, current) and not binding_still_present(original, sessions)


def replacement_binding(target, configured, sessions):
    """Return an updated binding, or None when the configured one must stay."""
    if binding_still_present(configured, sessions):
        return None
    row = unique_live_agent(target, sessions)
    if row is None or row["pane_id"] == configured.pane_id:
        return None
    return configured.model_copy(
        update={
            "pane_id": row["pane_id"],
            "expected_pid": row["expected_pid"],
            "agent_pid": row["agent_pid"],
            "codex_thread_id": None,
            "codex_rollout_path": None,
        }
    )


def load_refresh(config) -> None:
    """Apply a previously proven refresh after restart. Ignore a newer manual binding."""
    path = overlay_path(config)
    if not path.is_file():
        return
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(saved, dict):
        return
    for target, item in saved.items():
        binding = config.visible_handoffs.bindings.get(target)
        if binding is None or not isinstance(item, dict):
            continue
        if (
            binding.pane_id != item.get("replaced_pane_id")
            or binding.expected_pid != item.get("replaced_expected_pid")
            or binding.agent_pid != item.get("replaced_agent_pid")
        ):
            continue
        try:
            config.visible_handoffs.bindings[target] = binding.model_copy(
                update={
                    "pane_id": item["pane_id"],
                    "expected_pid": item["expected_pid"],
                    "agent_pid": item["agent_pid"],
                    "codex_thread_id": None,
                    "codex_rollout_path": None,
                }
            )
        except (KeyError, ValueError, TypeError):
            continue


def save_refresh(config, target, previous: VisibleTerminalBinding, updated: VisibleTerminalBinding):
    path = overlay_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, ValueError):
            current = {}
    current[target] = {
        "replaced_pane_id": previous.pane_id,
        "replaced_expected_pid": previous.expected_pid,
        "replaced_agent_pid": previous.agent_pid,
        "pane_id": updated.pane_id,
        "expected_pid": updated.expected_pid,
        "agent_pid": updated.agent_pid,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
