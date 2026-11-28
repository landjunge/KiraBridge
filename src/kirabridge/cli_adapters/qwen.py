"""Qwen Code 0.28.6 Ink composer and visible literal-text verification."""

import re
from typing import NamedTuple

from . import UnsupportedAdapter
from ._legacy_readiness import display_text
from .contract import Capabilities

_PLACEHOLDERS = {"  Type your request, or /usage", "  Type your message or @path/to/file"}
_TOP_RULE = re.compile(r"─{10,}(?: [^─\n]{1,140} ──)?")
_BOTTOM_RULE = re.compile(r"─{10,}")
_MODEL = re.compile(r"➜[ \t]+[^·\n]+·[ \t]+\S[^\n]*")
_MODE = re.compile(
    r"(?:Auto[- ]mode|plan mode|auto-accept edits|⏸ ?(?:Ask permissions|Berechtigung anfragen)"
    r"|Planungsmodus|Änderungen automatisch akzeptieren|Auto-Modus)"
    r" *(?:\((?:Shift \+ )?Tab (?:to cycle|zum Wechseln)\))",
    re.I,
)
_BUSY = re.compile(r"\b(?:esc(?:ape)? to cancel|esc(?:ape)? zum abbrechen)\b|[⠀-⣿]", re.I)
_FOLDED = re.compile(r"\[Pasted Content \d+ chars\](?: #\d+)?")


class Composer(NamedTuple):
    previous: list[str]
    field: tuple[str, ...]
    chrome: tuple[str, ...]
    view: str


def composer(text):
    lines = text.rstrip().split("\n")
    if len(lines) < 5 or not (
        _MODEL.fullmatch(lines[-2].strip()) and _MODE.fullmatch(lines[-1].strip())
    ):
        return None
    end = len(lines) - 3
    if not _BOTTOM_RULE.fullmatch(lines[end].rstrip()):
        return None
    start = end - 1
    while start > 0 and lines[start].startswith("  "):
        start -= 1
    if not lines[start].startswith("> ") or not _TOP_RULE.fullmatch(lines[start - 1].rstrip()):
        return None
    field = tuple(line[2:] for line in lines[start:end])
    chrome = (lines[start - 1], *lines[end:])
    return Composer(lines[: start - 1], field, chrome, "\n".join(lines[start - 1 :]))


def _empty(frame):
    # BaseTextInput prepends two placeholder spaces in addition to the "> " prefix.
    return len(frame.field) == 1 and frame.field[0].rstrip() in _PLACEHOLDERS


def _busy(frame, binding=None):
    # Only the live rows adjacent to the composer count. Transcript output
    # from an older turn is separated from the live area by viewport padding.
    end = len(frame.previous)
    while end and not frame.previous[end - 1].strip():
        end -= 1
    start = end
    while start and frame.previous[start - 1].strip():
        start -= 1
    block = "\n".join(frame.previous[start:end])
    configured = getattr(binding, "busy_pattern", "")
    return bool(_BUSY.search(block) or (configured and re.search(configured, block, re.I)))


class QwenCodeAdapter(UnsupportedAdapter):
    capabilities = Capabilities(text=True)

    def __init__(self):
        super().__init__("qwen")

    def input_view(self, raw):
        text, controls = display_text(raw)
        found = None if controls else composer(text)
        return found.view if found else ""

    def observe(self, raw, binding, protocol=None):
        text, controls = display_text(raw)
        found = None if controls else composer(text)
        empty = bool(found and _empty(found))
        if found is None:
            state = "unknown"
            reason = "unsupported_control_sequence" if controls else "prompt_not_found"
        elif _busy(found, binding):
            state, reason = "working", "visible_qwen_activity"
        elif not empty:
            state, reason = "input_not_empty", "existing_input_must_not_be_overwritten"
        else:
            state, reason = "ready", "current_empty_widget"
        return {
            "target": self.name,
            "ready": state == "ready",
            "state": state,
            "reason": reason,
            "input_empty": empty,
            "ui_state": "composer" if found else "unknown",
            "work_state": "working" if state == "working" else "unknown",
            "allowed_actions": ["insert", "submit"] if state == "ready" else [],
            "protocol_state": "not_bound",
        }

    def insertion_observed(self, raw, text, before, **options):
        old, old_controls = display_text(before)
        new, new_controls = display_text(raw)
        if old_controls or new_controls or not text or _FOLDED.fullmatch(text):
            return False
        previous, current = composer(old), composer(new)
        return bool(
            previous
            and current
            and _empty(previous)
            and current.chrome == previous.chrome
            and not _busy(previous)
            and not _busy(current)
            and not _empty(current)
            and "\n".join(current.field) == text
        )

    def allows_text(self, text, submit):
        return True

    async def preflight_input(self, sessions, binding, text, before):
        # The Ink editor hides large pastes behind a character-count badge.
        # This representation does not establish the exact submitted payload.
        if len(text) > 1000 or text.count("\n") >= 10 or _FOLDED.fullmatch(text):
            from kirabridge.bridge_core.models import BridgeError

            raise BridgeError(
                "visible_input_geometry_ambiguous",
                "Qwen's paste badge cannot verify the exact payload; no text was pasted",
            )
