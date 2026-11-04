"""Grok Build's existing boxed composer; no Codex menu or navigation fallback."""

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
        return {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_return_frame",
            "allowed_actions": [],
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
        return None

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return self.insertion_observed(raw, text, before, **options)

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        # Preserve the existing literal Grok input route. No parsed slash/menu
        # capability is claimed; unknown results remain unconfirmed.
        return True

    async def preflight_input(self, sessions, binding, text, before):
        return None
