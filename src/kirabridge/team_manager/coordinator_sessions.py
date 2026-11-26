"""Fail-closed registry for coordinator session proofs.

Session eligibility is deliberately separate from role selection. Provider/session
integrations may register a proof for an execution scope; an unregistered scope is
never eligible to hold or receive the coordinator role.
"""

from __future__ import annotations

from collections.abc import Callable

CoordinatorSessionProof = Callable[[object, dict, object], bool]
_PROOFS: dict[str, CoordinatorSessionProof] = {}


def register_coordinator_session_proof(scope: str, proof: CoordinatorSessionProof) -> None:
    """Register one trusted host-side proof for a worker execution scope."""
    if not isinstance(scope, str) or not scope or not callable(proof):
        raise ValueError("Coordinator session proof needs a scope and callable")
    if scope in _PROOFS:
        raise ValueError(f"Coordinator session proof already registered: {scope}")
    _PROOFS[scope] = proof


def coordinator_session_proof(scope: str) -> CoordinatorSessionProof | None:
    """Return the registered proof; unknown scopes fail closed."""
    return _PROOFS.get(scope)
