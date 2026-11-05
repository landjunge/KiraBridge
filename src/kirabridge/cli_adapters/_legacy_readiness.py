"""Current input widget plus a separately bound Codex turn observation.

Quoted output is not agent activity. Unknown frames/control sequences fail closed.
No input, process operations or identity inference takes place here.
"""

import re


def _codex_transcript_navigation(line):
    """Known transcript controls coexist with Codex's live input widget."""
    return bool(
        re.fullmatch(
            r"New activity · (?:"
            r"(?:↓ )?Back to bottom · esc|"
            r"enter/esc latest(?: · \? shortcuts)?(?:[ \t]+⚠ \d+ warnings? · f2 to view)?"
            r")",
            line.strip(),
        )
    )


def codex_input_footer(line):
    """Recognize only supported rows below the Codex composer."""
    line = line.strip()
    return bool(
        re.match(r"^GPT-\S+.*", line)
        or ("for agents" in line and "? for shortcuts" in line)
        or _codex_transcript_navigation(line)
    )


def _codex_standalone_warning_footer(lines):
    """The captured populated composer has exactly a model and warning row.

    Do not recognize warning-looking rows individually: their placement and
    the complete two-row footer distinguish this layout from extra content.
    """
    return bool(
        len(lines) == 2
        and re.fullmatch(r"GPT-\S+ [^·\n]+ · [^\n]+", lines[0])
        and re.fullmatch(r"⚠ [1-9][0-9]* warnings? · f2 to view", lines[1])
    )


def codex_input_footer_group(lines):
    """Validate the complete composer footer; warning rows never stand alone."""
    footer = [line.strip() for line in lines if line.strip()]
    return all(codex_input_footer(line) for line in footer) or _codex_standalone_warning_footer(
        footer
    )


def display_text(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\x1b\[[0-9;:]*m", "", text)
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    unknown = bool(re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text))
    return text, unknown


def input_view(target, text):
    text, unknown = display_text(text)
    if unknown:
        return ""
    if target == "grok" and "╭" in text:
        return text[text.rfind("╭") :]
    if target == "codex":
        # The busy Codex composer uses U+00BB; submitted history retains
        # U+203A. Ignoring the busy marker selects a previous submitted prompt
        # and misreports that old text as current pending input.
        prompts = list(re.finditer(r"(?m)^[ \t]*[›»][^\n]*", text))
        return text[prompts[-1].start() :] if prompts else ""
    return text if target not in {"grok", "codex"} else ""


def assess(target, raw, binding, protocol=None):
    text, controls = display_text(raw)
    view = input_view(target, text)
    base = {
        "target": target,
        "ready": False,
        "state": "unknown",
        "reason": "unknown_input_frame",
        "input_empty": False,
        "protocol_state": protocol.get("state", "unknown") if protocol is not None else "not_bound",
    }

    def result(state, reason):
        return {**base, "state": state, "reason": reason, "ready": state == "ready"}

    if controls or not view:
        return result("unknown", "unsupported_control_sequence" if controls else "prompt_not_found")
    first = view.splitlines()[0].strip()
    if target == "codex":
        # The final input row, not any previous user prompt in visible output.
        queue_composer = first.startswith("»")
        candidate = "›" + first[1:] if queue_composer else first
        empty = bool(re.fullmatch(binding.ready_pattern, candidate))
        base["input_empty"] = empty
        prelude = text[: text.rfind(view)].rstrip()
        current_block = re.split(r"\n[ \t]*\n", prelude)[-1] if prelude else ""
        current = current_block + "\n" + view
        if not empty:
            return result("input_not_empty", "existing_input_must_not_be_overwritten")
        if queue_composer:
            # Recognize the empty field without authorizing queued input into
            # a running turn. An idle protocol that disagrees also fails closed.
            return result(
                "unknown" if protocol and protocol.get("state") == "idle" else "working",
                "protocol_display_disagree"
                if protocol and protocol.get("state") == "idle"
                else "current_queue_composer",
            )
        if protocol and protocol.get("state") == "working":
            return result("working", "bound_codex_turn_active")
        if "tab to queue message" in view:
            return result("working", "current_queue_hint")
        # These exact controls navigate the transcript above the live composer;
        # they do not prove the input is hidden. Unknown scroll views still block.
        activity_text = "\n".join(
            line for line in current.splitlines() if not _codex_transcript_navigation(line)
        )
        scroll_controls = re.search(r"Back to bottom|enter/esc latest", activity_text, re.I)
        if scroll_controls and not (protocol and protocol.get("state") == "idle"):
            return result("scrolled", "current_scroll_controls")
        footer = [line.strip() for line in view.splitlines()[1:] if line.strip()]
        known_footer = codex_input_footer_group(footer)
        if not known_footer:
            return result("unknown", "unrecognized_footer_or_dialog")
        # Real progress is above the prompt. An idle protocol observation cannot
        # override a still-rendered current progress row (or vice versa).
        progress = re.search(
            r"(?m)^[ \t]*[•◦]\s+[^\n]*\([^\n]*esc to interrupt[^\n]*",
            current_block,
        )
        if progress:
            return result(
                "unknown" if protocol and protocol.get("state") == "idle" else "working",
                "protocol_display_disagree"
                if protocol and protocol.get("state") == "idle"
                else "current_progress_row",
            )
        if protocol is not None:
            return result(
                "ready" if protocol.get("state") == "idle" else "unknown",
                "bound_codex_turn_idle"
                if protocol.get("state") == "idle"
                else "bound_codex_state_unavailable",
            )
        # Without a bound protocol, ambiguous work words are not an idle proof.
        activity_text = "\n".join(
            line for line in text.splitlines() if not _codex_transcript_navigation(line)
        )
        if binding.busy_pattern and re.search(binding.busy_pattern, activity_text, re.I):
            return result("unknown", "unbound_ambiguous_activity_text")
        return result("ready", "current_empty_widget")

    empty = bool(re.search(binding.ready_pattern, view))
    base["input_empty"] = empty
    if not empty:
        return result("input_not_empty", "existing_input_or_unknown_widget")
    # The live status row sits directly above the composer. Older quotations
    # of Thinking or [stop] stay above that row and do not mean the turn is active.
    raw_prelude = text[: text.rfind("╭")].splitlines() if "╭" in text else []
    prelude = [line for line in raw_prelude if line.strip()]
    status = prelude[-1] if prelude else ""
    current = status + "\n" + view
    if binding.busy_pattern and re.search(binding.busy_pattern, current, re.I):
        return result("working", "visible_grok_activity")
    if re.search(r"Back to bottom|enter/esc latest", current, re.I):
        return result("scrolled", "current_scroll_controls")
    return result("ready", "current_empty_widget")
