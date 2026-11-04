"""Codex-only Return grammar, isolated from OS transport and task coordination."""

import re

from ._legacy_readiness import assess, codex_input_footer_group, display_text, input_view
from .codex_menus import resume_readiness, resume_selector, unsupported_confirmation_frame


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
