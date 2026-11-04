"""Explicit Return on one observed native view, with no paste or agent-work message."""

import re
from contextlib import AsyncExitStack

from kirabridge.bridge_core.models import BridgeError
from kirabridge.codex_menu import resume_readiness, resume_selector, unsupported_confirmation_frame
from kirabridge.visible_handoff import VisibleReadinessError
from kirabridge.visible_readiness import assess, codex_input_footer_group, display_text, input_view


def return_readiness(target, raw, binding, protocol=None):
    """Return intent differs from permission to paste into an empty composer."""
    text, controls = display_text(raw)

    def result(state, reason):
        return {"target": target, "ready": state == "ready", "state": state, "reason": reason}

    if controls or target != "codex":
        return result("unknown", "unsupported_return_frame")
    if protocol is not None and protocol.get("state") != "idle":
        return result(
            "working" if protocol.get("state") == "working" else "unknown",
            "bound_codex_turn_active_or_unknown",
        )
    if resume_selector(text):
        return resume_readiness(text)
    if unsupported_confirmation_frame(text):
        return result("unknown", "unsupported_confirmation_dialog")
    view = input_view(target, text)
    if not view:
        return result("unknown", "current_input_frame_not_found")
    lines = view.splitlines(keepends=True)
    first = lines[0].strip()
    if first.startswith("»"):
        return result("working", "current_queue_composer")
    if not first.startswith("›"):
        return result("unknown", "unsupported_return_frame")
    # Only the observed first input row (including Codex's collapsed paste) is
    # a supported draft. Keep all other rows: indented activity or a dialog is
    # not evidence of a draft continuation and must never be hidden.
    masked = "›" + ("\n" if lines[0].endswith("\n") else "") + "".join(lines[1:])
    # Explicit cursor-bound Return can confirm a visible wrapped draft too.
    # Require a separate blank delimiter and the known model footer. Never mask
    # an arbitrary indented dialog or a progress row outside the composer.
    for index in range(2, len(lines)):
        if lines[index].strip():
            continue
        continuation, footer = lines[1:index], lines[index:]
        nonempty_footer = [line for line in footer if line.strip()]
        if (
            continuation
            and first != "›"
            and all(
                (line.startswith("  ") and line.strip()) or line in {"\n", " \n", "  \n"}
                for line in continuation
            )
            and all(
                not unsupported_confirmation_frame(line + "\n› ")
                and "tab to queue message" not in line
                and assess(target, line + "\n›\n" + "".join(footer), binding, protocol)["ready"]
                for line in continuation
            )
            and nonempty_footer
            and re.match(r"^\s*GPT-\S+", nonempty_footer[0])
            and codex_input_footer_group(nonempty_footer)
        ):
            masked = "›\n" + "".join(footer)
            break
    observation = assess(target, text[: len(text) - len(view)] + masked, binding, protocol)
    return {**observation, "input_empty": bool(re.fullmatch(binding.ready_pattern, first))}


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
            if not readiness["ready"]:
                raise VisibleReadinessError(readiness)
            if readiness["reason"] == "observed_codex_resume_selector":
                input_kind = "menu_confirmation"
            await bridge.visible_handoffs.reconcile_target_reservations(
                principal, target, binding, explicit_return_task_id=task["id"]
            )
        approved = bridge.tasks.input_policy.dispatch(principal, args, task["id"])

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
            await running(evidence(False))

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
