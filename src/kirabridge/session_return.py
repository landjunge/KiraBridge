"""Explicit Return on one observed native view, with no paste or agent-work message."""

from contextlib import AsyncExitStack

from kirabridge.bridge_core.models import BridgeError
from kirabridge.visible_handoff import VisibleReadinessError


def return_readiness(target, raw, binding, protocol=None):
    """Legacy entry point; program semantics belong to the selected adapter."""
    from kirabridge.cli_adapters import adapter_for

    return adapter_for(target).return_readiness(raw, binding, protocol)


async def execute(bridge, task, args, running, progress):
    principal = task["principal"]
    input_kind = "observed_return"
    for capability in ("session.input", "session.inspect", "terminal.execute"):
        bridge.security.principal(principal, capability)
    expected = bridge.outputs.captured_input_view(
        principal, args.pane_id, args.expected_pid, args.expected_cursor
    )
    selected = await bridge.sessions.selected(principal, args.pane_id, args.expected_pid)
    if selected.get("transport") != "terminal_app":
        raise BridgeError("visible_terminal_required", "Return requires a visible native tab")
    target, binding = bridge.sessions.explicit_agent_binding(selected)
    if (binding.agent_pid if binding is not None else None) != args.expected_agent_pid:
        raise BridgeError("visible_target_changed", "Observed agent identity changed")
    async with AsyncExitStack() as stack:
        if target:
            policy = bridge.security.principal(principal, "agent.execute")
            if target not in policy.agents:
                raise BridgeError("agent_denied", "Selected agent is not granted")
            await stack.enter_async_context(
                bridge.sessions.agent_selection(principal, target, binding)
            )
            view = await bridge.visible_handoffs.check_target(principal, target, binding)
        else:
            view = await bridge.sessions.read(principal, args.pane_id, args.expected_pid)
        if view["text"] != expected:
            raise BridgeError(
                "visible_input_changed", "The observed terminal view changed; read again"
            )
        if target:
            observed = await bridge.visible_handoffs.binding_readiness(
                principal, target, binding, view
            )
            if observed.get("state") == "target_changed":
                raise VisibleReadinessError(observed)
            readiness = return_readiness(target, expected, binding, observed.get("protocol"))
            if args.key == "escape":
                from kirabridge.cli_navigation import return_to_input

                bridge.tasks.input_policy.dispatch(principal, args, task["id"])
                await return_to_input(
                    bridge, task, target, binding, view, observed, running, progress
                )
                bridge.tasks.input_policy.sent(principal, task["id"])
                return {
                    "pane_id": args.pane_id,
                    "expected_pid": args.expected_pid,
                    "input_kind": "navigation",
                    "semantic_action": "return_to_input",
                    "navigation_key_sent": True,
                    "navigation_observed": True,
                    "return_sent": False,
                    "paste_event_sent": False,
                    "execution_confirmed": False,
                    "automatic_retry": False,
                }
            if readiness.get("return_requires_navigation"):
                from kirabridge.cli_navigation import return_to_input

                bridge.tasks.input_policy.dispatch(principal, args, task["id"])
                view, observed = await return_to_input(
                    bridge, task, target, binding, view, readiness, running, progress
                )
                expected = view["text"]
                readiness = return_readiness(target, expected, binding, observed.get("protocol"))
                navigation_dispatched = True
            else:
                navigation_dispatched = False
            if not readiness["ready"]:
                raise VisibleReadinessError(readiness)
            if readiness.get("semantic_action") == "menu_confirmation":
                input_kind = "menu_confirmation"
            await bridge.visible_handoffs.reconcile_target_reservations(
                principal, target, binding, explicit_return_task_id=task["id"]
            )
        if args.key == "escape":
            raise BridgeError(
                "visible_navigation_unsupported", "Navigation requires a program adapter"
            )
        approved = (
            args
            if target and navigation_dispatched
            else bridge.tasks.input_policy.dispatch(principal, args, task["id"])
        )

        def evidence(return_sent):
            return {
                "evidence_type": "visible_return_key",
                "terminal_input_attempted": True,
                "pane_id": args.pane_id,
                "expected_pid": args.expected_pid,
                "expected_cursor": args.expected_cursor,
                "agent_pid": args.expected_agent_pid,
                "key": "enter",
                "input_kind": input_kind,
                "paste_event_sent": False,
                "return_sent": return_sent,
                "agent_confirmed": False,
                "automatic_retry": False,
            }

        async def return_attempted():
            await (progress if target and navigation_dispatched else running)(evidence(False))

        result = await bridge.sessions.return_key(
            principal, approved, expected_screen=expected, before_transport=return_attempted
        )
        await progress(evidence(True))
    bridge.tasks.input_policy.sent(principal, task["id"])
    return {
        **result,
        "key": "enter",
        "input_kind": input_kind,
        "pane_id": args.pane_id,
        "expected_pid": args.expected_pid,
        "input_handed_to_transport": True,
        "submitted": True,
        "execution_confirmed": False,
        "scope": "one Return key to the observed terminal view; no paste or agent acknowledgement",
    }
