"""Explicit adapter registry; importing it performs no process or service action."""

from .contract import Capabilities, ProgramAdapter, inventory


class UnsupportedAdapter:
    capabilities = Capabilities()

    def __init__(self, name):
        self.name = name

    def input_view(self, raw):
        return raw if self.name is None else ""

    def observe(self, raw, binding, protocol=None):
        return {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_cli_program",
            "input_empty": False,
            "ui_state": "unknown",
            "work_state": "unknown",
            "allowed_actions": [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        return {**self.observe(raw, binding, protocol), "reason": "unsupported_return_frame"}

    def insertion_observed(self, *args, **options):
        return False

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
        return False

    async def preflight_input(self, sessions, binding, text, before):
        return None


class AdapterRegistry:
    def __init__(self, adapters=()):
        self._adapters = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ProgramAdapter):
        if not adapter.name or adapter.name in self._adapters:
            raise ValueError("Adapter name must be unique and explicit")
        self._adapters[adapter.name] = adapter

    def get(self, name):
        return self._adapters.get(name) or UnsupportedAdapter(name)

    def describe(self, name):
        return inventory(self.get(name))


_default = None


def default_registry():
    global _default
    if _default is None:
        from .claude import ClaudeCodeAdapter
        from .codex import CodexAdapter
        from .grok import GrokBuildAdapter
        from .opencode import OpenCodeAdapter

        _default = AdapterRegistry(
            [CodexAdapter(), GrokBuildAdapter(), ClaudeCodeAdapter(), OpenCodeAdapter()]
        )
    return _default


def adapter_for(name):
    return default_registry().get(name)
