"""OpenCode's left-bordered composer, including its rendered empty placeholder.

OpenCode 1.4.4 draws an empty composer with a left ``┃`` border, a placeholder
row (``Ask anything... "<example>"``), the agent/model row and a ``╹▀`` bottom
bar. The placeholder text is not user input. Only the documented example
prompts are treated as empty; any other row content is a real draft and blocks
overwrite. A frame without the complete composer stays unknown.
"""

import re

from . import _legacy_readiness as legacy
from .contract import Capabilities

_PLACEHOLDER = re.compile(r"Ask anything\.\.\.(?: \"[^\"\n]{1,120}\")?")
_SHELL_PLACEHOLDER = re.compile(r"Run a command\.\.\.(?: \"[^\"\n]{1,120}\")?")
_EXAMPLES = (
    "Fix a TODO in the codebase",
    "What is the tech stack of this project?",
    "Fix broken tests",
    "Explain how authentication works",
    "Find and fix security vulnerabilities",
    "Add unit tests for the user service",
    "Refactor this function to be more readable",
    "What does this error mean?",
    "Help me debug this issue",
    "Generate API documentation",
    "Optimize database queries",
    "Add input validation",
    "Create a new component for...",
    "How do I deploy this project?",
    "Review my code for best practices",
    "Add error handling to this function",
    "Explain this regex pattern",
    "Convert this to TypeScript",
    "Add logging throughout the codebase",
    "What dependencies are outdated?",
    "Help me write a migration script",
    "Implement caching for this endpoint",
    "Add pagination to this list",
    "Create a CLI command for...",
    "How do environment variables work here?",
)


def _empty_text(text):
    text = text.strip()
    if not text or _SHELL_PLACEHOLDER.fullmatch(text):
        return False
    match = _PLACEHOLDER.fullmatch(text)
    if match is None:
        return False
    if text == "Ask anything...":
        return True
    quoted = text[len('Ask anything... "') : -1]
    return quoted in _EXAMPLES


def composer(text):
    """The last complete OpenCode composer, or None for an unknown frame."""
    lines = text.split("\n")
    bottom = next(
        (
            index
            for index in range(len(lines) - 1, -1, -1)
            if re.fullmatch(r" *╹▀{10,} *", lines[index])
        ),
        None,
    )
    if bottom is None:
        return None
    start = bottom
    while start and re.fullmatch(r" *┃[^\n]*", lines[start - 1]):
        start -= 1
    rows = lines[start:bottom]
    if len(rows) < 4:
        return None
    inner = []
    for row in rows:
        stripped = row.strip()
        if not stripped.startswith("┃") or stripped.count("┃") != 1:
            return None
        inner.append(stripped[1:].rstrip())
    if inner[0].strip() or not inner[-1].strip():
        return None
    return {
        "start": start,
        "end": bottom,
        "content": inner[1:-1],
        "footer": inner[-1],
    }


def _content_rows(found):
    return [row.strip() for row in found["content"] if row.strip()]


def _input_empty(found):
    rows = _content_rows(found)
    if not rows:
        return True
    return len(rows) == 1 and _empty_text(rows[0])


def _shell_mode(found):
    rows = _content_rows(found)
    return bool(rows and _SHELL_PLACEHOLDER.fullmatch(rows[0]))


def _typed(found):
    return "\n".join(_content_rows(found))


class OpenCodeAdapter:
    name = "opencode"
    capabilities = Capabilities(text=True)

    def input_view(self, raw):
        text, unknown = legacy.display_text(raw)
        found = None if unknown else composer(text)
        if found is None:
            return ""
        lines = text.split("\n")
        return "\n".join(lines[found["start"] : found["end"] + 1])

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
            if _shell_mode(found):
                # A shell-mode composer would execute pasted text as a command.
                result = {**result, "reason": "opencode_shell_mode"}
            elif not _input_empty(found):
                result = {
                    **result,
                    "state": "input_not_empty",
                    "reason": "existing_input_must_not_be_overwritten",
                }
            else:
                prelude = text.split("\n")[: found["start"]]
                # Only the live status row directly above the composer counts;
                # older quoted work must not be mistaken for current activity.
                status = next((line for line in reversed(prelude) if line.strip()), "")
                busy_pattern = getattr(binding, "busy_pattern", "") if binding else ""
                busy = bool(busy_pattern and re.search(busy_pattern, status, re.I))
                result = {
                    **result,
                    "input_empty": True,
                    "state": "working" if busy else "ready",
                    "reason": "visible_opencode_activity" if busy else "current_empty_widget",
                }
        return {
            **result,
            "ready": result["state"] == "ready",
            "ui_state": "composer" if result["state"] == "ready" else "unknown",
            "work_state": "working" if result["state"] == "working" else "unknown",
            "allowed_actions": ["insert", "submit"] if result["state"] == "ready" else [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        text, controls = legacy.display_text(raw)
        found = None if controls else composer(text)
        if found is None:
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "prompt_not_found",
                "allowed_actions": [],
            }
        if _shell_mode(found):
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "opencode_shell_mode",
                "allowed_actions": [],
            }
        if _input_empty(found):
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "empty_opencode_composer",
                "allowed_actions": [],
            }
        status = next(
            (line for line in reversed(text.split("\n")[: found["start"]]) if line.strip()),
            "",
        )
        busy_pattern = getattr(binding, "busy_pattern", "") if binding else ""
        if busy_pattern and re.search(busy_pattern, status, re.I):
            return {
                "target": self.name,
                "ready": False,
                "state": "working",
                "reason": "visible_opencode_activity",
                "allowed_actions": [],
            }
        return {
            "target": self.name,
            "ready": True,
            "state": "ready",
            "reason": "current_nonempty_composer",
            "input_empty": False,
            "allowed_actions": ["return"],
        }

    def insertion_observed(self, raw, text, before, **options):
        previous, previous_controls = legacy.display_text(before)
        current, controls = legacy.display_text(raw)
        if controls or previous_controls:
            return False
        old = composer(previous)
        new = composer(current)
        if old is None or new is None or not _input_empty(old):
            return False
        return bool(text) and _typed(new) == text

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        # The exact boxed payload is verified by insertion_observed before any
        # Return; this only keeps the native fresh-echo check conservative.
        return None

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return False

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        return True

    async def preflight_input(self, sessions, binding, text, before):
        return None
