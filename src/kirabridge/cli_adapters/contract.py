"""Versioned program semantics. Adapters never authorize or post native input."""

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    text: bool = False
    separate_return: bool = False
    return_to_input: bool = False
    slash_commands: tuple[str, ...] = ()
    softwrap: bool = False
    cwd_proof: bool = False
    bound_turn: bool = False
    bound_reply: bool = False


class ProgramAdapter(Protocol):
    name: str
    capabilities: Capabilities

    def input_view(self, raw: str) -> str: ...
    def observe(self, raw, binding, protocol=None) -> dict: ...
    def return_readiness(self, raw, binding, protocol=None) -> dict: ...
    def insertion_observed(self, raw, text, before, **options) -> bool: ...
    def paste_source(self, text) -> str | None: ...
    def navigation_preserves(self, before, after, observation, after_state) -> bool: ...
    async def protocol_state(self, binding, observer) -> dict | None: ...
    def has_bound_protocol(self, binding) -> bool: ...
    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options) -> bool: ...
    def command_result(self, command, before, after, binding, protocol=None) -> dict: ...
    def allows_text(self, text, submit) -> bool: ...
    async def preflight_input(self, sessions, binding, text, before) -> None: ...


def inventory(adapter):
    return {
        "interface_version": 1,
        "program": adapter.name,
        "capabilities": asdict(adapter.capabilities),
        "scope": "program semantics, not permission or runtime readiness",
    }
