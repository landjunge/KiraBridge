"""Refresh a dead visible-agent binding without replaying an old handoff.

A configured pane/PID pair is stale once that pane and both PIDs are absent
from a fresh catalog and exactly one unambiguous live session runs the same
agent. The old handoff row stays untouched. A live or ambiguous process is
never replaced.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import digest

OVERLAY_NAME = "visible-binding-refresh.json"
IDENTITY_FIELDS = ("pane_id", "expected_pid", "agent_pid")
PROTOCOL_FIELDS = ("codex_thread_id", "codex_rollout_path")


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


def distinct_window_processes(original, current) -> bool:
    """Only a candidate for native absence proof; a tty name may have been reused.

    Unlike identities_disjoint, this never permits bypassing an old reservation
    on its own. The original window and both original PIDs must also be proved
    absent with fresh native observations before the replacement can proceed.
    """
    try:
        old, new = original.pane_id.split(":"), current.pane_id.split(":")
        old_pids = {original.expected_pid, original.agent_pid}
        new_pids = {current.expected_pid, current.agent_pid}
        return (
            len(old) == len(new) == 3
            and old[0] == new[0] == "terminal"
            and old[1].isdecimal()
            and new[1].isdecimal()
            and int(old[1]) > 0
            and int(new[1]) > 0
            and int(old[1]) != int(new[1])
            and all(re.fullmatch(r"ttys[0-9]+", tty) for tty in (old[2], new[2]))
            and len(old_pids) == len(new_pids) == 2
            and all(type(pid) is int and pid > 0 for pid in old_pids | new_pids)
            and old_pids.isdisjoint(new_pids)
        )
    except (AttributeError, TypeError, ValueError):
        return False


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
    if not isinstance(sessions, list) or not all(
        isinstance(row, dict)
        and isinstance(row.get("processes", []), list)
        and all(isinstance(process, dict) for process in row.get("processes", []))
        for row in sessions
    ):
        return None
    if binding_still_present(configured, sessions):
        return None
    row = unique_live_agent(target, sessions)
    if row is None or row["pane_id"] == configured.pane_id:
        return None
    try:
        return _with_saved_identity(configured, row)
    except ValueError:
        return None


def _protocol_digest(binding) -> str:
    return digest([getattr(binding, key) for key in PROTOCOL_FIELDS])


def _same_process_handle(previous, updated) -> bool:
    return (
        previous.expected_pid == updated.expected_pid
        and previous.agent_pid == updated.agent_pid
        and previous.pane_id.rsplit(":", 1)[-1] == updated.pane_id.rsplit(":", 1)[-1]
    )


def _with_saved_identity(binding, item, *, keep_protocol=False):
    if any(type(item.get(key)) is not int for key in IDENTITY_FIELDS[1:]):
        raise ValueError("Saved binding PIDs must be integers")
    return VisibleTerminalBinding.model_validate(
        {
            **binding.model_dump(),
            **{key: item[key] for key in IDENTITY_FIELDS},
            **({} if keep_protocol else dict.fromkeys(PROTOCOL_FIELDS)),
        }
    )


def refresh_state(value):
    return value.get("state") if isinstance(value, dict) else value


def refresh_destination(value):
    if not isinstance(value, dict):
        return None
    destination = value.get("destination")
    if not isinstance(destination, dict) or set(destination) != set(IDENTITY_FIELDS):
        return None
    return destination


def load_refresh(config, *, same_live_generation=None) -> dict[str, str]:
    """Apply a proven refresh; return matching rows that need live reconciliation."""
    path = overlay_path(config)
    if not path.is_file():
        return {}
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    unresolved = {}
    for target, item in saved.items():
        binding = config.visible_handoffs.bindings.get(target)
        if binding is None or not isinstance(item, dict):
            continue
        if any(getattr(binding, key) != item.get("replaced_" + key) for key in IDENTITY_FIELDS):
            continue
        anchor_protocol = item.get("replaced_protocol_sha256")
        if not isinstance(anchor_protocol, str) or not re.fullmatch(
            r"[0-9a-f]{64}", anchor_protocol
        ):
            try:
                destination = _with_saved_identity(binding, item)
            except (KeyError, ValueError, TypeError):
                unresolved[target] = {"state": "legacy_overlay_unverified"}
            else:
                unresolved[target] = {
                    "state": "legacy_overlay_unverified",
                    "destination": {key: getattr(destination, key) for key in IDENTITY_FIELDS},
                }
            continue
        if anchor_protocol != _protocol_digest(binding):
            try:
                destination = _with_saved_identity(binding, item)
            except (KeyError, ValueError, TypeError):
                unresolved[target] = {"state": "manual_protocol_binding_precedence"}
            else:
                unresolved[target] = {
                    "state": "manual_protocol_binding_precedence",
                    "destination": {key: getattr(destination, key) for key in IDENTITY_FIELDS},
                }
            continue
        try:
            keep_protocol = item.get("preserve_codex_protocol", False)
            if type(keep_protocol) is not bool:
                continue
            updated = _with_saved_identity(binding, item, keep_protocol=keep_protocol)
            if keep_protocol and (
                target != "codex"
                or binding.codex_thread_id is None
                or not _same_process_handle(binding, updated)
                or same_live_generation is None
                or not same_live_generation(target, binding, updated)
            ):
                continue
            config.visible_handoffs.bindings[target] = updated
        except (KeyError, ValueError, TypeError):
            continue
    return unresolved


def save_refresh(
    config,
    target,
    previous: VisibleTerminalBinding,
    updated: VisibleTerminalBinding,
    *,
    preserve_codex_protocol=False,
):
    if updated.codex_thread_id is not None and (
        not preserve_codex_protocol
        or target != "codex"
        or not _same_process_handle(previous, updated)
        or _protocol_digest(previous) != _protocol_digest(updated)
    ):
        raise ValueError("Only a verified same-process rehome can carry the Codex protocol")
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
    # Keep the on-disk configuration as the anchor across A -> B -> C refreshes.
    # Otherwise a restart with the original configured A would not restore C.
    # A manual binding that does not match the saved B starts its own chain.
    anchor_identity = {key: getattr(previous, key) for key in IDENTITY_FIELDS}
    anchor_protocol = _protocol_digest(previous)
    saved = current.get(target)
    if isinstance(saved, dict) and all(
        saved.get(key) == getattr(previous, key) for key in IDENTITY_FIELDS
    ):
        try:
            saved_anchor = _with_saved_identity(
                previous, {key: saved["replaced_" + key] for key in IDENTITY_FIELDS}
            )
            saved_protocol = saved.get("replaced_protocol_sha256", digest([None, None]))
            saved_preserve = saved.get("preserve_codex_protocol", False)
            previous_protocol_matches = (
                saved_protocol == anchor_protocol
                if saved_preserve
                else previous.codex_thread_id is None
            )
            if (
                isinstance(saved_protocol, str)
                and re.fullmatch(r"[0-9a-f]{64}", saved_protocol)
                and type(saved_preserve) is bool
                and previous_protocol_matches
            ):
                anchor_identity = {key: getattr(saved_anchor, key) for key in IDENTITY_FIELDS}
                anchor_protocol = saved_protocol
        except (KeyError, TypeError, ValueError):
            pass
    current[target] = {
        **{"replaced_" + key: value for key, value in anchor_identity.items()},
        "replaced_protocol_sha256": anchor_protocol,
        "preserve_codex_protocol": updated.codex_thread_id is not None,
        **{key: getattr(updated, key) for key in IDENTITY_FIELDS},
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def clear_refresh(config, target):
    """Remove one disproved legacy overlay while preserving other targets."""
    path = overlay_path(config)
    if not path.is_file():
        return True
    try:
        current = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(current, dict):
        return False
    if target not in current:
        return True
    current.pop(target)
    if not current:
        try:
            path.unlink()
        except OSError:
            return False
        return True
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(current, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False
    return True
