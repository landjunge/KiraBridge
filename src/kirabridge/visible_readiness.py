"""Compatibility facade for registered CLI program observations."""

from kirabridge.cli_adapters import adapter_for
from kirabridge.cli_adapters._legacy_readiness import (
    _codex_standalone_warning_footer,
    _codex_transcript_navigation,
    codex_input_footer,
    codex_input_footer_group,
    display_text,
)


def input_view(target, text):
    return adapter_for(target).input_view(text)


def assess(target, raw, binding, protocol=None):
    return adapter_for(target).observe(raw, binding, protocol)


__all__ = [
    "display_text",
    "_codex_transcript_navigation",
    "codex_input_footer",
    "_codex_standalone_warning_footer",
    "codex_input_footer_group",
    "input_view",
    "assess",
]
