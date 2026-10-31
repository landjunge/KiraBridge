"""Paste literal CLI input and, when requested, send exactly one guarded Return.

The durable session.input task owns this attempt. Agent work messages keep their
separate receipt/reply protocol; literal input never creates such a message.
"""

import hashlib
import re
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.visible_readiness import display_text, input_view


def _without_viewport_padding(suffix):
    """Discard only final whitespace-only display rows, not payload or footer text."""
    lines = suffix.split("\n")
    while lines and not lines[-1].strip(" \t"):
        lines.pop()
    return "\n".join(lines)


def _codex_renderer_suffix(suffix):
    """Pin footer rows while allowing Codex to show/hide its inline F2 badge."""
    rows = []
    for line in _without_viewport_padding(suffix).split("\n"):
        badge = re.fullmatch(r"([ \t]*GPT-\S+[^\n]*?)[ \t]+⚠ [0-9]+ warnings? · f2 to view", line)
        # Only the exact optional badge is decoration. The same model/path row
        # must remain, in order; no standalone or added footer row is discarded.
        rows.append(badge[1] if badge else line)
    return "\n".join(rows)


def _without_empty_composer_hint(suffix):
    """Codex hides this last shortcut row when the empty composer receives text."""
    rows = suffix.split("\n")
    if (
        len(rows) >= 2
        and re.fullmatch(r"[ \t]*← for agents · \? for shortcuts", rows[-1])
        and re.fullmatch(r"[ \t]*GPT-\S+[^\n]*", rows[-2])
    ):
        # Operate only on the already-separated, pre-paste footer. Never strip
        # hint-shaped payload continuations or newly added post-paste rows.
        return "\n".join(rows[:-1])
    return None


def _cwd_footer(suffix):
    rows = _without_viewport_padding(suffix).split("\n")
    found = []
    for index, row in enumerate(rows):
        badge = re.fullmatch(r"([ \t]*GPT-\S+[^\n]*?)[ \t]+⚠ [0-9]+ warnings? · f2 to view", row)
        base = badge[1] if badge else row
        model = re.fullmatch(r"([ \t]*GPT-[^·\n]+[ \t]+·[ \t]+)([^\n]+)", base)
        if model:
            found.append((index, model[1], model[2], badge is not None))
    return (rows, *found[0]) if len(found) == 1 else None


def _displays_cwd(display, cwd, home):
    spellings = [cwd]
    if home and (cwd == home or cwd.startswith(home + "/")):
        spellings.append("~" + cwd[len(home) :])
    return any(
        display == spelling
        or (
            display.endswith("…")
            and display.count("…") == 1
            and 0 < len(display) - 1 < len(spelling)
            and spelling.startswith(display[:-1])
        )
        for spelling in spellings
    )


def _same_bound_cwd_footer(before, after, cwd, home):
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return False
    old, new = _cwd_footer(before), _cwd_footer(after)
    if old is None or new is None:
        return False
    old_rows, old_index, old_model, old_path, old_badge = old
    new_rows, new_index, new_model, new_path, new_badge = new
    if (
        old_index != new_index
        or old_model != new_model
        or len(old_rows) != len(new_rows)
        or not old_badge
        or new_badge
        or not old_path.endswith("…")
        or not new_path.startswith(old_path[:-1])
        or any(old_rows[i] != new_rows[i] for i in range(len(old_rows)) if i != old_index)
    ):
        return False
    return _displays_cwd(old_path, cwd, home) and _displays_cwd(new_path, cwd, home)


def insertion_observed(target, raw, text, before, *, cwd=None, home=None):
    """Recognize the exact payload in the current widget, never a history match."""
    cleaned, controls = display_text(raw)
    previous, previous_controls = display_text(before)
    if controls or previous_controls:
        return False
    view = input_view(target, cleaned)
    previous_view = input_view(target, previous)
    if target == "codex":
        marker = re.match(r"[ \t]*› ?", view)
        previous_marker = re.match(r"[ \t]*› ?", previous_view)
        if marker is None or previous_marker is None:
            return False
        content = view[marker.end() :]
        # Pin the actual ready widget's suffix before pasting. Only explicitly
        # supported renderer decoration may change; a payload continuation
        # resembling GPT/status/navigation chrome must never be discarded.
        newline = previous_view.find("\n")
        suffix = previous_view[newline:] if newline >= 0 else ""
        before_variants = [suffix]
        without_hint = _without_empty_composer_hint(_without_viewport_padding(suffix))
        if without_hint is not None:
            # Preserve the original warning badge for the separately bound
            # CWD-reflow proof; normalization would erase its prerequisite.
            before_variants.append(without_hint)
        # Codex can collapse multiline pasted text. The empty pre-state,
        # clipboard transaction and exact count bind this view to this paste.
        collapsed = f"[Pasted Content {len(text)} chars]"
        for expected in (text, text.replace("\n", "\n  "), collapsed):
            if not content.startswith(expected):
                continue
            actual_suffix = content[len(expected) :]
            if actual_suffix and not actual_suffix.startswith("\n"):
                continue
            rendered_after = _codex_renderer_suffix(actual_suffix)
            for before_variant in before_variants:
                if rendered_after == _codex_renderer_suffix(before_variant):
                    return True
                if _same_bound_cwd_footer(
                    before_variant, actual_suffix, cwd, home or str(Path.home())
                ):
                    return True
        return False
    if target == "grok":
        marker = re.search(r"(?m)^[ \t]*│[ \t]*❯ ?", view)
        if marker is None:
            return False
        previous_bottom = re.search(r"(?m)^[ \t]*╰[─┴╯ \t]*$", previous_view)
        bottom = re.search(r"(?m)^[ \t]*╰[─┴╯ \t]*$", view)
        if (
            previous_bottom is None
            or bottom is None
            or view[bottom.start() :] != previous_view[previous_bottom.start() :]
        ):
            return False
        content = view[marker.end() : bottom.start()].removesuffix("\n")
        # Borders are display decoration, not user input. Keep all interior
        # characters, so an added or changed continuation cannot be submitted.
        lines = content.splitlines()
        normalized = "\n".join(re.sub(r"[ \t]*│[ \t]*$", "", line) for line in lines)
        return normalized == text
    return False


def _needs_cwd_proof(text):
    view = input_view("codex", text)
    newline = view.find("\n")
    footer = _cwd_footer(view[newline:]) if newline >= 0 else None
    return bool(
        footer
        and footer[-1]
        and footer[-2].startswith(("/", "~/"))
        and footer[-2].endswith("…")
        and footer[-2].count("…") == 1
    )


async def _task_cwd(sessions, binding):
    selection = sessions.current_selection()
    if (
        not selection
        or selection[0] != "codex"
        or selection[1] != binding
        or not isinstance(selection[2], dict)
        or binding.agent_pid not in selection[2]
    ):
        return None
    observe = getattr(sessions.terminal_app, "process_working_directory", None)
    if observe is None:
        return None
    try:
        return await observe(binding.agent_pid, expected_identity=selection[2][binding.agent_pid])
    except BridgeError as exc:
        if exc.code != "process_cwd_unavailable":
            raise
        return None


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
    verifier_version="literal-widget-v2",
):
    principal = task["principal"]
    policy = bridge.security.principal(principal, "agent.execute")
    if target not in policy.agents:
        raise BridgeError("agent_denied", "Selected agent is not granted")
    bridge.security.principal(principal, "terminal.execute")
    async with bridge.sessions.agent_selection(principal, target, binding):
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
            await running(evidence(phase="inserting"))

        approved = bridge.tasks.input_policy.dispatch(principal, args, task["id"])
        before = (
            await bridge.visible_handoffs.check_target(principal, target, binding, ready=True)
            if args.submit
            else None
        )
        before_cwd = (
            await _task_cwd(bridge.sessions, binding)
            if target == "codex" and before is not None and _needs_cwd_proof(before["text"])
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
            if not verified and before_cwd is not None:
                after_cwd = await _task_cwd(bridge.sessions, binding)
                if after_cwd == before_cwd:
                    verified = verifier(
                        target, view["text"], approved.text, before["text"], cwd=before_cwd
                    )
            verification = {
                "verifier_version": verifier_version,
                "reason": "exact_widget_match" if verified else "exact_widget_mismatch",
                "before_screen_sha256": hashlib.sha256(before["text"].encode()).hexdigest(),
                "after_screen_sha256": hashlib.sha256(view["text"].encode()).hexdigest(),
                "expected_payload_sha256": hashlib.sha256(approved.text.encode()).hexdigest(),
                "expected_payload_chars": len(approved.text),
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
        "execution_confirmed": False,
        "scope": "literal terminal input; no agent work message or acknowledgement",
    }
