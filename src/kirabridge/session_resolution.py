"""Fresh exact visible identities, with explicit ambiguity rather than guessed windows."""

from kirabridge.bridge_core.models import BridgeError


async def resolve(sessions, bindings, principal, target, reference=None):
    configured = bindings.get(target)
    if configured is None:
        raise BridgeError(
            "visible_target_missing", "Agent needs an operator-configured input contract"
        )
    if reference is not None:
        selected = await sessions.selected(principal, reference.pane_id, reference.expected_pid)
        actual, binding = sessions.explicit_agent_binding(selected)
        if actual != target:
            raise BridgeError("visible_target_changed", "Selected session contains another agent")
        return binding
    if configured:
        try:
            row = await sessions.selected(principal, configured.pane_id, configured.expected_pid)
            if sessions.binding_matches(row, configured, target):
                return configured.model_copy(update={"expected_pid": row["expected_pid"]})
        except BridgeError as exc:
            if exc.code not in {
                "session_selection_changed",
                "visible_target_changed",
                "session_missing",
            }:
                raise
    catalog = await sessions.catalog(principal)
    rows = catalog.get("sessions", [])
    candidates = [
        row
        for row in rows
        if row.get("agent_candidate") == target and not row.get("agent_candidates_ambiguous")
    ]
    if len(candidates) != 1:
        raise BridgeError(
            "visible_target_ambiguous" if candidates else "visible_target_missing",
            "Select an exact current session from session_catalog; nothing was sent",
        )
    actual, binding = sessions.explicit_agent_binding(candidates[0])
    if actual != target or binding is None:
        raise BridgeError("visible_target_changed", "Current agent identity could not be bound")
    return binding
