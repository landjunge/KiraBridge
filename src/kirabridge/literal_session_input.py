"""Shared literal-input coordinator; legacy renderer exports delegate to adapters."""

import hashlib

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.cli_adapters import adapter_for
from kirabridge.cli_adapters.rendering import (  # legacy imports, not dispatch policy
    _codex_cursor_words,
    _codex_renderer_suffix,
    _cwd_footer,
    _displays_cwd,
    _needs_cwd_proof,
    _same_bound_cwd_footer,
    _same_hint_warning_footer,
    _task_cwd,
    _without_empty_composer_hint,
    _without_viewport_padding,
    check_codex_paste_geometry,
    codex_full_row_widths,
    codex_payload_forms,
    codex_wrap_words,
    codex_wrapped_renderings,
    single_line_renderings,
)


def insertion_observed(target, raw, text, before, **options):
    return adapter_for(target).insertion_observed(raw, text, before, **options)


async def execute(
    bridge,
    task,
    args,
    target,
    binding,
    running,
    progress,
    *,
    verifier=insertion_observed,
    verifier_version="literal-widget-v3",
):
    principal = task["principal"]
    policy = bridge.security.principal(principal, "agent.execute")
    if target not in policy.agents:
        raise BridgeError("agent_denied", "Selected agent is not granted")
    bridge.security.principal(principal, "terminal.execute")
    adapter = adapter_for(target)

    def release():
        approved = bridge.tasks.input_policy.dispatch(principal, args, task["id"])
        if not adapter.allows_text(approved.text, approved.submit):
            raise BridgeError("cli_action_unsupported", "This text action is not supported here")
        return approved

    async with bridge.sessions.agent_selection(principal, target, binding):
        navigation_dispatched = False
        approved = None
        if args.submit:
            current = await bridge.visible_handoffs.check_target(principal, target, binding)
            state = await bridge.visible_handoffs.binding_readiness(
                principal, target, binding, current
            )
            if "return_to_input" in state.get("allowed_actions", []) and state.get("input_empty"):
                from kirabridge.cli_navigation import return_to_input

                approved = release()
                await return_to_input(
                    bridge, task, target, binding, current, state, running, progress
                )
                navigation_dispatched = True
        await bridge.visible_handoffs.reconcile_target_reservations(
            principal, target, binding, explicit_paste_task_id=task["id"]
        )

        def evidence(**details):
            return {
                "evidence_type": "visible_literal_input",
                "terminal_input_attempted": True,
                "pane_id": args.pane_id,
                "expected_pid": args.expected_pid,
                "agent_pid": binding.agent_pid,
                "return_sent": False,
                "agent_confirmed": False,
                "automatic_retry": False,
                **details,
            }

        async def paste_attempted():
            await (progress if navigation_dispatched else running)(evidence(phase="inserting"))

        approved = approved or release()
        before = (
            await bridge.visible_handoffs.check_target(principal, target, binding, ready=True)
            if args.submit
            else None
        )
        if before is not None:
            await adapter.preflight_input(bridge.sessions, binding, approved.text, before)
        before_cwd = (
            await _task_cwd(bridge.sessions, binding)
            if adapter_for(target).capabilities.cwd_proof
            and before is not None
            and _needs_cwd_proof(before["text"])
            else None
        )
        result = await bridge.sessions.insert(
            principal,
            approved.model_copy(update={"submit": False}),
            before_transport=paste_attempted,
        )
        if args.submit:
            view = await bridge.visible_handoffs.check_target(principal, target, binding)
            verified = verifier(target, view["text"], approved.text, before["text"])
            verifier_options = {}
            if (
                not verified
                and adapter_for(target).capabilities.softwrap
                and verifier is insertion_observed
            ):
                selection = bridge.sessions.current_selection()
                if selection and len(approved.text) <= 1000:
                    try:
                        columns = await bridge.sessions.terminal_app.input_columns(
                            args.pane_id, identity_guard=selection[2], expected_screen=view["text"]
                        )
                    except BridgeError:
                        columns = None
                    if columns is not None:
                        verifier_options["columns"] = columns
                        verified = verifier(
                            target, view["text"], approved.text, before["text"], **verifier_options
                        )
            if not verified and before_cwd is not None:
                after_cwd = await _task_cwd(bridge.sessions, binding)
                if after_cwd == before_cwd:
                    verified = verifier(
                        target,
                        view["text"],
                        approved.text,
                        before["text"],
                        cwd=before_cwd,
                        **verifier_options,
                    )
            verification = {
                "verifier_version": verifier_version,
                "reason": "exact_widget_match" if verified else "exact_widget_mismatch",
                "before_screen_sha256": hashlib.sha256(before["text"].encode()).hexdigest(),
                "after_screen_sha256": hashlib.sha256(view["text"].encode()).hexdigest(),
                "expected_payload_sha256": hashlib.sha256(approved.text.encode()).hexdigest(),
                "expected_payload_chars": len(approved.text),
                **({"observed_columns": verifier_options["columns"]} if verifier_options else {}),
            }
            if not verified:
                await progress(
                    evidence(
                        phase="insertion_unverified",
                        paste_event_sent=True,
                        insertion_verified=False,
                        verification=verification,
                    )
                )
                raise UncertainExecution(
                    "visible_insert_unknown", "Literal insertion not verified; no Return sent"
                )
            await progress(
                evidence(
                    phase="submitting",
                    paste_event_sent=True,
                    insertion_verified=True,
                    verification=verification,
                )
            )
            # This transport checks both native identities and the exact screen
            # again. A menu after Return is a valid result; no agent ACK is due.
            await bridge.sessions.press_return(
                principal, args.pane_id, args.expected_pid, expected_screen=view["text"]
            )
            result = {**result, "return_sent": True}
            await progress(evidence(phase="sent", paste_event_sent=True, return_sent=True))
    bridge.tasks.input_policy.sent(principal, task["id"])
    return {
        **result,
        "pane_id": args.pane_id,
        "expected_pid": args.expected_pid,
        "input_handed_to_transport": True,
        "submitted": args.submit,
        "text_transferred": True,
        "insertion_verified": bool(args.submit),
        "acceptance_observed": False,
        "response_observed": False,
        "execution_confirmed": False,
        "scope": "literal terminal input; no agent work message or acknowledgement",
    }


__all__ = [
    "_without_viewport_padding",
    "_codex_renderer_suffix",
    "_without_empty_composer_hint",
    "_same_hint_warning_footer",
    "_cwd_footer",
    "_displays_cwd",
    "_same_bound_cwd_footer",
    "codex_wrap_words",
    "codex_wrapped_renderings",
    "_codex_cursor_words",
    "codex_full_row_widths",
    "check_codex_paste_geometry",
    "single_line_renderings",
    "codex_payload_forms",
    "_needs_cwd_proof",
    "_task_cwd",
    "insertion_observed",
    "execute",
]
