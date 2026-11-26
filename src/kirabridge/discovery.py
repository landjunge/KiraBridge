"""One principal-scoped truth about grants, execution routes and fresh observations."""

from __future__ import annotations

import json
import time
from pathlib import Path

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.permissions import decision, direct_terminal_required, permission_revision
from kirabridge.platform_adapters import current_platform


def _snapshot_facts(bridge, principal, *, passive=False):
    policy = bridge.security.principal(principal)
    observed = getattr(bridge, "discovery_observations", {}).get(principal)
    current_permissions = permission_revision(bridge.config)
    platform = bridge.macos.passive_snapshot() if passive else bridge.macos.snapshot()
    access = decision(bridge.config, principal, "session.catalog")
    if observed and observed.get("permission_revision") != current_permissions:
        observed = None
    if not access["authorized"] or access["approval_required"]:
        observed = {
            "status": "not_authorized" if not access["authorized"] else "approval_required",
            "sessions": [],
            "permission_revision": current_permissions,
        }
    revision = digest(
        {
            "version": __version__,
            "instance": bridge.runtime["instance_id"],
            "permissions": current_permissions,
            "platform": platform["revision"],
            "agents": {
                name: value.model_dump()
                for name, value in bridge.config.agents.items()
                if name in policy.agents
            },
            "sessions": observed.get("revision") if observed else None,
        }
    )
    return policy, observed, current_permissions, platform, revision


def epoch(bridge, principal):
    """Fresh lightweight schema epoch, without the full presentation payload."""
    _, _, permissions, platform, revision = _snapshot_facts(bridge, principal, passive=True)
    return {
        "version": __version__,
        "instance_id": bridge.runtime["instance_id"],
        "principal": principal,
        "revision": revision,
        "permission_revision": permissions,
        "platform_revision": platform["revision"],
    }


def snapshot(bridge, principal):
    policy, observed, current_permissions, platform, revision = _snapshot_facts(bridge, principal)
    linux_direct = current_platform().name == "linux"
    return {
        "version": __version__,
        "instance_id": bridge.runtime["instance_id"],
        "principal": principal,
        "revision": revision,
        "permission_revision": current_permissions,
        "platform": platform,
        "capabilities": sorted(policy.capabilities),
        "refresh": {
            "on": [
                "connection",
                "version",
                "instance",
                "permissions",
                "terminal_session",
                "platform",
            ],
            "tools_list": (
                "explicit tools/list is fresh; stdio call schemas cached <=30s "
                "with epoch/notification invalidation"
            ),
            "client_action": (
                "Refresh tools/list and operation_catalog when revision changes; "
                "never replay writes"
            ),
        },
        "file_transfer": {
            "enabled": bridge.config.file_transfer.enabled,
            "source_access": (
                "explicit host-selected file params or authorized exports; "
                "no Library-wide enumeration"
            ),
            "prepare_permission": decision(bridge.config, principal, "files.prepare"),
            "transfer_permission": decision(bridge.config, principal, "files.transfer"),
            "inspect_permission": decision(bridge.config, principal, "files.inventory"),
            "receiver_protocol": "threaddesk.library.receive.v1",
            "receiver_availability": getattr(
                bridge.file_transfers.receiver, "availability", "not_probed"
            )
            if bridge.config.threaddesk.enabled
            else "disabled",
            "success_condition": (
                "stored plus validated durable receipt; "
                "transferred bytes alone are not import success"
            ),
        },
        "keyboard": {
            "tool": "keyboard_control",
            "operation": "keyboard.control",
            "profile_required": False,
            "event_subscription_required": False,
            "target_selection": "application name, exact PID/start pair, or fresh foreground app",
            "target_inspection": "automatic before native input",
            "permission": decision(bridge.config, principal, "keyboard.control"),
            "os_permission_requested_automatically": False,
            "success_scope": "native posting evidence; application processing is not confirmed",
        },
        "direct_terminal": {
            "tool": "terminal_control",
            "operation": "terminal.visible",
            "legacy_terminal_execute_route": (
                "linux_owned_pty" if linux_direct else "visible_terminal"
            )
            if direct_terminal_required(bridge.config, principal)
            else "managed_process",
            "rule_scope": (
                "ChatGPT direct KiraBridge terminal control; not internal Codex/Grok execution"
            ),
            "selection": "fresh short-lived owned PTY; exact argv; no existing session selected"
            if linux_direct
            else "confirmed idle visible shell; otherwise a separate visible window",
            "create_if_needed_scope": "macOS visible window only",
            "hidden_fallback": False,
            "permission": decision(bridge.config, principal, "terminal.visible"),
            "new_window_permission": decision(bridge.config, principal, "session.open"),
            "window_authorization": (
                "approved exact task or existing automatic grant; no second local-only token"
            ),
            "threaddesk": "separate optional access path; never a direct-terminal substitute",
        },
        "terminal_observation": {
            **(observed or {"status": "not_probed", "sessions": []}),
            "freshness": "cached" if observed and "observed_at" in observed else "not_probed",
            "usable_for_input": False,
        },
    }


async def live(bridge, principal):
    access = decision(bridge.config, principal, "session.catalog")
    observation = {"status": "not_authorized", "sessions": []}
    if access["authorized"] and access["approval_required"]:
        observation["status"] = "approval_required"
    elif access["authorized"]:
        try:
            catalog = await bridge.terminal_queries.execute(principal, "session.catalog", {})
            observation = {**catalog, "observed_at": time.time()}
        except BridgeError as exc:
            observation = {
                "status": exc.code,
                "error": {"code": exc.code, "message": str(exc)},
                "sessions": [],
            }
        except Exception:
            observation = {"status": "observation_unavailable", "sessions": []}
    # Fingerprints exclude timestamps and raw terminal text. A changed PID/TTY or
    # transport status invalidates discovery even if the saved policy is identical.
    observation["permission_revision"] = permission_revision(bridge.config)
    observation["revision"] = digest({k: v for k, v in observation.items() if k != "observed_at"})
    if not hasattr(bridge, "discovery_observations"):
        bridge.discovery_observations = {}
    bridge.discovery_observations[principal] = observation
    result = snapshot(bridge, principal)
    result["terminal_observation"]["freshness"] = "fresh"
    return result


async def inventory(bridge, principal):
    policy = bridge.security.principal(principal, "agent.inspect")
    discovery = await live(bridge, principal)
    result = bridge.agents.inventory(policy.agents)
    rows = discovery["terminal_observation"].get("sessions", [])
    from kirabridge.agent_manager.cli_versions import inventory as cli_inventory

    process_names = {
        Path(str(process.get("name", ""))).name.lower()
        for row in rows
        for process in row.get("processes", [])
        if isinstance(process, dict) and process.get("name")
    }
    cli_rows = await cli_inventory(bridge.config.agents, policy.agents, process_names)
    changes = _record_cli_versions(bridge, cli_rows)
    _notify_cli_version_changes(bridge, changes, principal)
    for agent in result["agents"]:
        binding = bridge.config.visible_handoffs.bindings.get(agent["id"])
        matches = [
            row
            for row in rows
            if binding
            and row["pane_id"] == binding.pane_id
            and row["expected_pid"] == binding.expected_pid
            and any(
                p["pid"] == binding.agent_pid and p["name"] == agent["id"]
                for p in row.get("processes", [])
            )
        ]
        agent["visible_handoff"] = {
            "binding_configured": binding is not None,
            "state": "not_probed"
            if discovery["terminal_observation"]["status"] != "available"
            else "unbound"
            if binding is None
            else "identity_confirmed"
            if len(matches) == 1
            else "visible_target_changed",
            "input_readiness": "not_probed; read the exact current session before input",
            "permission": decision(bridge.config, principal, "agent.execute"),
            "next_step": "Use terminal_control for direct shell work. Agent handoffs require "
            "the current operator-assigned agent window; grants alone do not confirm identity.",
        }
    return {**result, "cli_inventory": cli_rows, "discovery": discovery}


def _record_cli_versions(bridge, rows):
    """Record one stable installation-set observation per CLI."""
    store = bridge.store
    changed = []
    grouped = {}
    for row in rows:
        if row.get("version"):
            grouped.setdefault(row["cli"], []).append(row)
    with store.transaction():
        for cli, candidates in grouped.items():
            previous = store.db.execute(
                "SELECT metadata FROM audit WHERE kind IN "
                "('cli.version_observed','cli.version_changed','cli.compatibility_changed') "
                "ORDER BY seq DESC LIMIT 512"
            ).fetchall()
            prior = None
            for event in previous:
                try:
                    metadata = json.loads(event["metadata"])
                except (TypeError, ValueError):
                    continue
                if metadata.get("cli") == cli:
                    prior = metadata
                    break
            primary = min(
                candidates,
                key=lambda row: (row.get("search_order", 0), row["executable"]),
            )
            installations = sorted(
                (
                    {
                        "executable": row["executable"],
                        "version": row["version"],
                        "compatibility": row["compatibility"]["status"],
                    }
                    for row in candidates
                ),
                key=lambda row: (row["executable"], row["version"], row["compatibility"]),
            )
            current = {
                "cli": cli,
                "version": primary["version"],
                "executable": primary["executable"],
                "probe_status": primary["probe_status"],
                "compatibility": primary["compatibility"]["status"],
                "installations": installations,
            }
            has_unsupported = any(item["compatibility"] == "unsupported" for item in installations)

            # Upgrade old single-installation audit records silently. The new
            # complete inventory becomes the baseline, preventing a one-time
            # schema migration from looking like a CLI installation change.
            legacy_prior = prior is not None and not isinstance(prior.get("installations"), list)
            if legacy_prior:
                store.audit("cli.version_observed", "service", None, current)
                continue

            previous_installations = prior.get("installations", []) if prior else []
            previous_identity = {
                (item.get("executable"), item.get("version"))
                for item in previous_installations
                if isinstance(item, dict)
            }
            current_identity = {(item["executable"], item["version"]) for item in installations}
            previous_compatibility = {
                (item.get("executable"), item.get("compatibility"))
                for item in previous_installations
                if isinstance(item, dict)
            }
            current_compatibility = {
                (item["executable"], item["compatibility"]) for item in installations
            }
            if prior and previous_identity == current_identity:
                if previous_compatibility == current_compatibility:
                    continue
                kind = "cli.compatibility_changed"
            elif prior:
                kind = "cli.version_changed"
            else:
                kind = "cli.version_observed"
            store.audit(kind, "service", None, current)
            if prior or has_unsupported:
                changed.append(
                    {
                        "event": kind if prior else "cli.compatibility",
                        "previous": prior,
                        "current": current,
                    }
                )
    return changed


def _notify_cli_version_changes(bridge, changes, principal):
    """Send one deduplicated result to current coordinator(s), without model execution here."""
    if not hasattr(bridge, "teams"):
        return
    from kirabridge.team_manager.models import TeamMessageSend

    teams = bridge.store.db.execute(
        "SELECT t.id FROM teams t JOIN team_members m ON m.team_id=t.id "
        "WHERE m.principal=? AND m.active=1 AND t.coordinator<>'' ORDER BY t.id",
        (principal,),
    ).fetchall()
    for change in changes:
        current = change["current"]
        for team in teams:
            previous_version = (change.get("previous") or {}).get("version")
            installations = ", ".join(
                f"{item['version']} ({item['compatibility']}) at {item['executable']}"
                for item in current.get("installations", [])
            )
            body = (
                f"{change['event']}: {current['cli']} "
                f"{previous_version + ' → ' if previous_version else ''}{current['version']} "
                f"({current['compatibility']}); primary {current['executable']}"
                + (f"; installations: {installations}" if installations else "")
            )
            request = TeamMessageSend(
                team_id=team["id"],
                recipient="coordinator",
                kind="result",
                body=body,
                idempotency_key=(
                    "cli-version-"
                    + digest(
                        {
                            "team": team["id"],
                            "event": change["event"],
                            "previous": change.get("previous"),
                            "current": current,
                        }
                    )[:48]
                ),
            )
            try:
                bridge.teams.send(principal, request)
            except BridgeError:
                # Audit remains authoritative when a team has no writable local route.
                continue
