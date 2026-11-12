"""Grok Build's existing boxed composer; no Codex menu or navigation fallback."""

import re

from . import _legacy_readiness as legacy
from .contract import Capabilities


class GrokBuildAdapter:
    name = "grok"
    capabilities = Capabilities(text=True)

    def input_view(self, raw):
        return legacy.input_view(self.name, raw)

    def observe(self, raw, binding, protocol=None):
        result = legacy.assess(self.name, raw, binding, protocol)
        return {
            **result,
            "ui_state": "composer" if result["ready"] else "unknown",
            "work_state": "working" if result["state"] == "working" else "unknown",
            "allowed_actions": ["insert", "submit"] if result["ready"] else [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        text, controls = legacy.display_text(raw)
        view = legacy.input_view(self.name, text)
        if controls or not view:
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "unsupported_return_frame",
                "allowed_actions": [],
            }
        state = legacy.grok_input_state(view)
        if state is None:
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "unrecognized_grok_composer",
                "allowed_actions": [],
            }
        if state:
            return {
                "target": self.name,
                "ready": False,
                "state": "unknown",
                "reason": "empty_grok_composer",
                "allowed_actions": [],
            }
        raw_prelude = text[: text.rfind("╭")].splitlines() if "╭" in text else []
        status = next((line for line in reversed(raw_prelude) if line.strip()), "")
        current = status + "\n" + view
        busy_pattern = getattr(binding, "busy_pattern", "") if binding else ""
        if busy_pattern and re.search(busy_pattern, current, re.I):
            return {
                "target": self.name,
                "ready": False,
                "state": "working",
                "reason": "visible_grok_activity",
                "allowed_actions": [],
            }
        if re.search(r"Back to bottom|enter/esc latest", current, re.I):
            return {
                "target": self.name,
                "ready": False,
                "state": "scrolled",
                "reason": "current_scroll_controls",
                "allowed_actions": [],
            }
        # Only an observed, current nonempty composer authorizes one Return.
        # The caller binds this decision to the exact captured screen.
        return {
            "target": self.name,
            "ready": True,
            "state": "ready",
            "reason": "current_nonempty_composer",
            "input_empty": False,
            "allowed_actions": ["return"],
        }

    def insertion_observed(self, raw, text, before, **options):
        from .rendering import insertion_observed

        return insertion_observed(self.name, raw, text, before, **options)

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        from .grok_echo import paste_source

        return paste_source(text)

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return self.insertion_observed(raw, text, before, **options)

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        # Preserve the existing literal Grok input route. No parsed slash/menu
        # capability is claimed; unknown results remain unconfirmed.
        return True

    async def preflight_input(self, sessions, binding, text, before):
        from kirabridge.bridge_core.models import BridgeError

        from .grok_echo import single_row_capacity, verifiable_payload

        capacity = single_row_capacity(before["text"])
        # A readable box proves any verifiable payload, including long and
        # multiline text. An unreadable box is not treated as proof: the exact
        # post-paste observation still decides. Preflight must not become a new
        # blanket refusal of every visible input just because one renderer's
        # title border was not recognized.
        if capacity is not None and not verifiable_payload(text):
            error = BridgeError(
                "visible_input_geometry_ambiguous",
                "Grok's boxed renderer cannot verify this payload exactly; no text was pasted",
            )
            error.observation = {
                "target": self.name,
                "observed_content_columns": capacity,
                "reason": "unsupported_grok_box_rendering",
                "terminal_input_attempted": False,
                "automatic_retry": False,
            }
            raise error
