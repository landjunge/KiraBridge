"""One coordinator-owned navigation step on the exact authenticated session.

Adapters propose a semantic action. This module owns its permission, target,
progress and postcondition checks; transport owns the native key. Never retry a key.
"""

import asyncio
import hashlib

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.cli_adapters import adapter_for
from kirabridge.session_manager import SessionInput


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


async def return_to_input(bridge, task, target, binding, before, observation, running, progress):
    principal = task["principal"]
    for capability in ("session.input", "session.inspect", "terminal.execute", "agent.execute"):
        policy = bridge.security.principal(principal, capability)
    if target not in policy.agents:
        raise BridgeError("agent_denied", "Program is not authorized")
    adapter = adapter_for(target)
    if "return_to_input" not in observation.get("allowed_actions", []):
        raise BridgeError("visible_navigation_unsupported", "No supported safe return action")
    if not adapter.capabilities.return_to_input:
        raise BridgeError("visible_navigation_unsupported", "Program has no navigation capability")
    # The caller has already released the exact original task intent. This fixed
    # subordinate Escape is not another buffer dispatch or an arbitrary key request.
    captured = bridge.sessions.audit.observe_terminal(
        principal, {**before, "pane_id": binding.pane_id, "expected_pid": binding.expected_pid}
    )
    key = SessionInput(
        pane_id=binding.pane_id,
        expected_pid=binding.expected_pid,
        expected_agent_pid=binding.agent_pid,
        key="escape",
        expected_cursor=captured["output_ref"]["sha256"],
    )
    if (
        bridge.outputs.captured_input_view(
            principal, binding.pane_id, binding.expected_pid, key.expected_cursor
        )
        != before["text"]
    ):
        raise BridgeError("visible_capture_unavailable", "Navigation capture changed")
    current = await bridge.visible_handoffs.check_target(principal, target, binding)
    if current["text"] != before["text"]:
        raise BridgeError("visible_input_changed", "View changed before navigation")
    fresh = await bridge.visible_handoffs.binding_readiness(principal, target, binding, current)
    if fresh.get("ui_state") != observation.get("ui_state") or "return_to_input" not in fresh.get(
        "allowed_actions", []
    ):
        raise BridgeError("visible_navigation_unsupported", "Program action changed")
    await bridge.visible_handoffs.reconcile_target_reservations(
        principal, target, binding, explicit_return_task_id=task["id"]
    )

    def evidence(sent):
        return {
            "evidence_type": "cli_navigation",
            "semantic_action": "return_to_input",
            "pane_id": binding.pane_id,
            "expected_pid": binding.expected_pid,
            "agent_pid": binding.agent_pid,
            "ui_state_before": observation["ui_state"],
            "before_sha256": fingerprint(before["text"]),
            "key": "escape",
            "navigation_key_sent": sent,
            "return_sent": False,
            "paste_event_sent": False,
            "terminal_input_attempted": True,
            "automatic_retry": False,
        }

    await bridge.sessions.return_key(
        principal,
        key,
        expected_screen=before["text"],
        before_transport=lambda: running(evidence(False)),
    )
    await progress(evidence(True))
    for _attempt in range(4):
        await asyncio.sleep(0.05)
        after = await bridge.visible_handoffs.check_target(principal, target, binding)
        state = await bridge.visible_handoffs.binding_readiness(principal, target, binding, after)
        ready = adapter.return_readiness(after["text"], binding, state.get("protocol"))
        if state.get("state") in {"target_changed", "working"}:
            raise UncertainExecution(
                "visible_navigation_unknown", "Target/work state changed after key"
            )
        retained_draft_ready = (
            observation.get("preserve_draft")
            and state.get("state") == "input_not_empty"
            and ready.get("ready")
        )
        if state.get("ready") or retained_draft_ready:
            # A transcript Escape must retain the exact current draft. Copy or
            # menu exits require an empty composer; never clear somebody's text.
            preserved = adapter.navigation_preserves(
                before["text"], after["text"], observation, state
            )
            if not preserved:
                raise UncertainExecution("visible_navigation_unknown", "Composer changed after key")
            await progress(
                {
                    **evidence(True),
                    "navigation_observed": True,
                    "after_sha256": fingerprint(after["text"]),
                }
            )
            return after, state
    raise UncertainExecution(
        "visible_navigation_unknown", "Safe input return not observed; no retry"
    )
