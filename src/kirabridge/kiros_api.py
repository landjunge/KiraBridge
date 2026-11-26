"""Narrow, stable facade for the KirOS module (KirOS docs/SPEC.md, section 8, item 1).

Purpose: give KirOS a single import surface -- ``kirabridge.kiros_api`` -- for the
stable KiraBridge building blocks it consumes. This module contains no logic; it
re-exports the canonical implementations so behaviour stays defined in one place.

Stability contract: the names in ``__all__`` are the supported surface. Renaming,
removing, or re-typing any of them requires a change from the KirOS point of view
and must be caught by tests/test_kiros_api.py. Everything else in KiraBridge
remains internal and may change without notice.

Credential note: ``keychain_credential`` returns a secret string that stays in
memory for the caller only. Never log, print, or persist any key value obtained
through this facade.
"""

from __future__ import annotations

from kirabridge.agent_manager.acp import ACPClient
from kirabridge.agent_manager.openrouter import OpenRouterAdapter
from kirabridge.agent_manager.openrouter_credentials import (
    credential_status,
    keychain_credential,
)
from kirabridge.completion_handoff import record_completion
from kirabridge.openrouter_models import (
    OPENROUTER_DEEPSEEK_MAX_PRICE,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_FREE_MODELS,
    OPENROUTER_PAID_MODELS,
)

__all__ = [
    "ACPClient",
    "OPENROUTER_DEEPSEEK_MAX_PRICE",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_FREE_MODELS",
    "OPENROUTER_PAID_MODELS",
    "OpenRouterAdapter",
    "credential_status",
    "keychain_credential",
    "record_completion",
]
