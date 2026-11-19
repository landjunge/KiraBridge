"""One normalized error for a task whose executor RETURNED a failure.

An exception already carries error.code. A returned `success: false` used to be stored
with error=None and the reason only inside the result; every consumer had to scrape it.
Here the reason is derived once, from the result's own structured fields (never text).
"""

from __future__ import annotations

import re

_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
KINDS = {"command_exit", "killed", "timeout", "tool_rejected", "validation", "agent_exit", "failed"}


def _code(value, fallback):
    return value if isinstance(value, str) and _CODE.fullmatch(value) else fallback


def _find(result, key):
    """Value of `key` in the result or its evidence (one level; no text parsing)."""
    for source in (result, result.get("evidence")):
        if isinstance(source, dict) and source.get(key) is not None:
            return source[key]
    return None


def normalize_failure(result):
    """Return {code, kind, retry_safe[, exit_code]} for a returned failure."""
    if not isinstance(result, dict):
        return {"code": "operation_failed", "kind": "failed", "retry_safe": False}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    nested = result.get("value", {}).get("error") if isinstance(result.get("value"), dict) else None
    if isinstance(nested, dict):  # ThreadDesk and other peers report a structured error
        code = _code(nested.get("code"), "tool_rejected")
        validation = code.endswith("_validation") or evidence.get("validation_failed") is True
        return {
            "code": code,
            "kind": "validation" if validation else "tool_rejected",
            # Only a request that provably never left this process may be repeated.
            "retry_safe": evidence.get("request_sent") is False,
        }
    exit_code = _find(result, "exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return {"code": "operation_failed", "kind": "failed", "retry_safe": False}
    if _find(result, "timed_out") is True:
        code, kind = "command_timeout", "timeout"
    elif _find(result, "terminated") is True or exit_code < 0:
        code, kind = "command_killed", "killed"
    elif isinstance(evidence.get("agent"), str):
        code, kind = "agent_exit_nonzero", "agent_exit"
    else:
        code, kind = "command_exit_nonzero", "command_exit"
    return {"code": code, "kind": kind, "retry_safe": False, "exit_code": exit_code}
