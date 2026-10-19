"""The three operator permission levels, shared by every authenticated entry point."""

from __future__ import annotations

from kirabridge.bridge_core.config import PrincipalConfig

LEVELS = {"full": "Voll erlaubt", "medium": "Mittel", "ask": "Nur mit Erlaubnis"}
READ_OPERATIONS = {
    "connection.check",
    "file.read",
    "file.list",
    "file.image",
    "clipboard.info",
    "process.list",
    "process.inspect",
    "agent.status",
    "policy.inspect",
    "handoff.status",
    "handoff.inbox",
    "threaddesk.read",
    "observations.read",
}


def level_for(policy: PrincipalConfig) -> str:
    if policy.permission_level:
        return policy.permission_level
    if policy.approval_mode == "manual":
        return "ask"
    return "full" if policy.allow_any_executable and "/" in policy.roots else "medium"


def automatic_for(policy: PrincipalConfig, operation: str) -> bool:
    if operation in policy.automatic_operations:
        return True
    # Existing policies retain their exact behavior until the operator selects a level.
    if policy.permission_level is None:
        return policy.approval_mode == "automatic"
    return policy.permission_level == "full" or (
        policy.permission_level == "medium" and operation in READ_OPERATIONS
    )


def state_exclusions(config, policy):
    explicit_full_grant = (
        policy.permission_level is not None and policy.allow_any_executable and "/" in policy.roots
    )
    return [] if explicit_full_grant else [str(config.state_path)]
