"""Claude Code's visible composer between two horizontal rules; literal text only.

Claude wraps long input over continuation rows, so insertion is compared without
whitespace. A collapsed paste ("[Pasted text #1 …]") never matches: no Return.
No slash, menu, navigation or reply capability is claimed.
"""

import json
import re

from . import _legacy_readiness as legacy
from .contract import Capabilities

_RULE = re.compile(r"[ \t]*─{3,}(?: [^─\n]{1,120} ─+)?[ \t]*")
_PROMPT = "❯"
_SPINNER = re.compile(r"[ \t]*[✻✽✶✳✢·*] ")


def _compact(text):
    return re.sub(r"\s+", "", text)


def composer(text):
    """(status rows above, input rows, footer rows) of the LAST composer, or None."""
    lines = text.split("\n")
    for index in range(len(lines) - 1, 0, -1):
        if lines[index].lstrip().startswith(_PROMPT) and _RULE.fullmatch(lines[index - 1]):
            for end in range(index + 1, len(lines)):
                if _RULE.fullmatch(lines[end]):
                    return lines[: index - 1], lines[index:end], lines[end + 1 :]
            return None
    return None


def typed(rows):
    """Input text without the prompt marker and continuation indentation."""
    first = rows[0].lstrip()[len(_PROMPT) :].lstrip("  ")
    return "\n".join([first, *(row.strip() for row in rows[1:])]).strip()


class ClaudeCodeAdapter:
    name = "claude"
    capabilities = Capabilities(text=True)

    def input_view(self, raw):
        text, unknown = legacy.display_text(raw)
        found = None if unknown else composer(text)
        return "" if found is None else "\n".join(found[1] + found[2])

    def observe(self, raw, binding, protocol=None):
        text, controls = legacy.display_text(raw)
        found = None if controls else composer(text)
        result = {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_control_sequence" if controls else "prompt_not_found",
            "input_empty": False,
            "protocol_state": "not_bound",
        }
        if found is not None:
            above, rows, footer = found
            first = rows[0].replace(" ", " ").rstrip()
            empty = len(rows) == 1 and bool(re.fullmatch(binding.ready_pattern, first.strip()))
            # Only the live spinner row and the footer; quoted output never counts.
            nearest = [line for line in above if line.strip()][-2:]
            status = [line for line in nearest if _SPINNER.match(line)] + footer
            busy = binding.busy_pattern and re.search(binding.busy_pattern, "\n".join(status), re.I)
            state, reason = (
                ("input_not_empty", "existing_input_must_not_be_overwritten")
                if not empty
                else ("working", "visible_claude_activity")
                if busy
                else ("ready", "current_empty_widget")
            )
            result.update(input_empty=empty, state=state, reason=reason, ready=state == "ready")
        return {
            **result,
            "ui_state": "composer" if result["ready"] else "unknown",
            "work_state": "working" if result["state"] == "working" else "unknown",
            "allowed_actions": ["insert", "submit"] if result["ready"] else [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        return {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_return_frame",
            "allowed_actions": [],
        }

    def insertion_observed(self, raw, text, before, **options):
        old = composer(legacy.display_text(before)[0])
        new_text, controls = legacy.display_text(raw)
        new = None if controls else composer(new_text)
        if old is None or new is None or typed(old[1]) or "[Pasted text" in new_text:
            return False
        return bool(_compact(text)) and _compact(typed(new[1])) == _compact(text)

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        # Fresh-echo check for wrapped rows: compare without whitespace.
        return (
            "\nfunction observedPaste(before, after) {"
            "const c=s=>s.replace(/[\\s\\u00a0]+/g,''), p=c(" + json.dumps(text) + ");"
            "return p.length>0 && c(after).includes(p) && !c(before).includes(p);}\n"
        )

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return False

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        return True

    async def preflight_input(self, sessions, binding, text, before):
        return None
