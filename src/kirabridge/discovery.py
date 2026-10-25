"""One principal-scoped truth about grants, execution routes and fresh observations."""

from __future__ import annotations

import time

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.permissions import decision, direct_terminal_required, permission_revision


def snapshot(bridge, principal):
    policy = bridge.security.principal(principal)
    observed = getattr(bridge, "discovery_observations", {}).get(principal)
    revision = digest(
        {
            "version": __version__,
            "instance": bridge.runtime["instance_id"],
            "permissions": permission_revision(bridge.config),
            "agents": {
                name: value.model_dump()
                for name, value in bridge.config.agents.items()
                if name in policy.agents
            },
            "sessions": observed.get("revision") if observed else None,
        }
    )
    return {
        "version": __version__,
        "instance_id": bridge.runtime["instance_id"],
        "principal": principal,
        "revision": revision,
        "permission_revision": permission_revision(bridge.config),
        "capabilities": sorted(policy.capabilities),
        "refresh": {
            "on": ["connection", "version", "instance", "permissions", "terminal_session"],
            "tools_list": "fresh per request; stdio proxy forwards list-change notifications",
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
        "direct_terminal": {
            "tool": "terminal_control",
            "operation": "terminal.visible",
            "legacy_terminal_execute_route": "visible_terminal"
            if direct_terminal_required(bridge.config, principal)
            else "managed_process",
            "rule_scope": (
                "ChatGPT direct KiraBridge terminal control; not internal Codex/Grok execution"
            ),
            "selection": "confirmed idle visible shell; otherwise a separate visible window",
            "hidden_fallback": False,
            "permission": decision(bridge.config, principal, "terminal.visible"),
            "new_window_permission": decision(bridge.config, principal, "session.open"),
            "window_authorization": (
                "approved exact task or existing automatic grant; no second local-only token"
            ),
            "threaddesk": "separate optional access path; never a direct-terminal substitute",
        },
        "terminal_observation": observed or {"status": "not_probed", "sessions": []},
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
    observation["revision"] = digest({k: v for k, v in observation.items() if k != "observed_at"})
    if not hasattr(bridge, "discovery_observations"):
        bridge.discovery_observations = {}
    bridge.discovery_observations[principal] = observation
    return snapshot(bridge, principal)


async def inventory(bridge, principal):
    policy = bridge.security.principal(principal, "agent.inspect")
    discovery = await live(bridge, principal)
    result = bridge.agents.inventory(policy.agents)
    rows = discovery["terminal_observation"].get("sessions", [])
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
    return {**result, "discovery": discovery}
