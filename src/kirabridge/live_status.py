"""Compact, read-only projection of observed agent work for KiraBridge Live.

Derived only from the existing ``LiveLogHub`` observation and the durable task
records: it adds no queue, no second history/archive and no execution right.
The monitor window and the authorized MCP read return the *same* projection, so
a closed window never hides the read service.

The caller sees their own observed work plus, only when an existing team grant
(owner/coordinator/observer) allows a read-only cross-principal observation, the
team's worker principals. The projection states that scope and the excluded
principals explicitly; actual all-agent acceptance remains a separate gate.
Steps are short human labels, not terminal output. A closed transport turn is
labelled ``turn ended`` with ``acceptance: not_evaluated`` — never "agent work
completed". Unknown or stale work is marked as such; no percentage is invented.
"""

from __future__ import annotations

import json
import time

# A running source/task that has not updated within this window is stale
# (unknown), not silently "working".
STALE_SECONDS = 120.0
# Hard bound so one poll cannot return an unbounded list.
MAX_AGENTS = 32
# Read only the newest durable tasks; they are a bounded supplement to the
# live sources, never a second queue.
MAX_TASKS = 32
# Team roles that may read the team's shared work read-only (team_manager roles).
ROLE_OBSERVERS = {"owner", "coordinator", "observer"}

# Adapter progress event -> short human step. Never the raw event text/prompt.
STEP = {
    "process_spawned": "starting",
    "session_created": "session ready",
    "session_resumed": "resumed",
    "prompt_admitted": "working",
    "session_busy": "working",
    "step_start": "working",
    "text": "responding",
    "model_text": "responding",
    "reasoning": "thinking",
    "step_finish": "finishing",
    "tool_call": "working",
    "session_status": "waiting",
}
SOURCE_STATE = {
    "running": "working",
    "closed": "completed",
    "failed": "blocked",
}


def _family(agent):
    """A real agent/product name, or ``unknown`` — never an operation namespace."""
    return agent if isinstance(agent, str) and agent else "unknown"


def _last_event(entries):
    for _seq, channel, _at, text, _size in reversed(entries):
        if channel != "events":
            continue
        try:
            value = json.loads(text)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
    return None


def _step(entries):
    event = _last_event(entries)
    if event is None:
        return None
    kind = event.get("event")
    return STEP.get(kind) if isinstance(kind, str) else None


def observation_scope(bridge, principal):
    """The own principal plus team members this principal may observe read-only.

    Reuses the existing team roles (owner/coordinator/observer may read shared
    team data). No new grant and no unsafe widening: any other role keeps only
    its own principal, and the excluded team members are reported, not hidden.
    """
    observed, excluded = {principal}, set()
    teams = getattr(bridge, "teams", None)
    if teams is None:
        return observed, excluded
    try:
        listing = teams.list(principal)
    except Exception:
        # No team.read grant or no membership: only the own principal.
        return observed, excluded
    for team in listing.get("teams", []):
        members = team.get("members", {})
        own_role = members.get(principal, {}).get("role")
        for name, info in members.items():
            if not info.get("active", True) or name == principal:
                continue
            if own_role in ROLE_OBSERVERS:
                observed.add(name)
            else:
                excluded.add(name)
    return observed, excluded


def _source_row(source, now):
    age = max(0.0, now - float(source.updated))
    stale = age > STALE_SECONDS and source.state == "running"
    state = "unknown" if stale else SOURCE_STATE.get(source.state, "unknown")
    turn_ended = source.state == "closed"
    if state == "completed":
        step = "turn ended"
    elif state == "blocked":
        step = "failed"
    else:
        step = _step(source.entries)
    return {
        "task_id": source.source_id,
        "principal": source.principal,
        "agent": source.agent,
        "family": _family(source.agent),
        "transport": source.transport,
        "operation": source.operation,
        "state": state,
        "step": step,
        "turn_ended": turn_ended,
        "acceptance": "not_evaluated",
        "observed_at": float(source.updated),
        "age_seconds": round(age, 3),
        "stale": stale,
        "unknown": state == "unknown",
        "source": "live_observation",
    }


def _durable_row(row, now):
    state = "queued" if row["state"] in {"queued", "accepted"} else "working"
    try:
        args = json.loads(row["args"]) if row["args"] else {}
    except ValueError:
        args = {}
    agent = args.get("agent") if isinstance(args, dict) else None
    agent = agent if isinstance(agent, str) and agent else row["agent"]
    observed = float(row["started"] or row["created"])
    age = max(0.0, now - observed)
    # A durable task in "running" with no live update past the window is a stale
    # unknown, exactly like a stale live source — never working forever.
    stale = state == "working" and age > STALE_SECONDS
    if stale:
        state = "unknown"
    return {
        "task_id": row["id"],
        "principal": row["principal"],
        "agent": agent,
        "family": _family(agent),
        "transport": "durable_task",
        "operation": row["operation"],
        "state": state,
        "step": "queued" if state == "queued" else ("stale" if stale else None),
        "turn_ended": False,
        "acceptance": "not_evaluated",
        "observed_at": observed,
        "age_seconds": round(age, 3),
        "stale": stale,
        "unknown": state == "unknown",
        "source": "durable_task",
    }


def project(bridge, principal, *, now=None):
    """Return the compact, read-only live projection for one principal.

    Reads the caller's own observed work and — only with an existing team
    observer grant — the team's worker principals. No prompts, thoughts, secrets,
    raw logs, percentages or archive are produced.
    """
    bridge.security.principal(principal, "logs.live")
    observed_at = float(now if now is not None else time.time())
    visible, excluded = observation_scope(bridge, principal)
    visible = sorted(visible)
    agents = [
        _source_row(source, observed_at)
        for source in bridge.live_logs.sources.values()
        if source.principal in visible
    ]
    seen = {agent["task_id"] for agent in agents}
    rows = []
    if visible:
        placeholders = ",".join("?" for _ in visible)
        rows = bridge.store.db.execute(
            "SELECT id, principal, operation, args, agent, state, created, started FROM tasks "
            f"WHERE principal IN ({placeholders}) "
            "AND state IN ('queued','accepted','running') "
            "ORDER BY created DESC LIMIT ?",
            (*visible, MAX_TASKS),
        ).fetchall()
    for row in rows:
        if row["id"] in seen:
            continue
        agents.append(_durable_row(row, observed_at))
    agents.sort(key=lambda item: item["observed_at"], reverse=True)
    truncated = len(agents) > MAX_AGENTS
    agents = agents[:MAX_AGENTS]
    counts: dict[str, int] = {}
    for agent in agents:
        counts[agent["state"]] = counts.get(agent["state"], 0) + 1
    result = {
        "ok": True,
        "observed_at": observed_at,
        "count": len(agents),
        "truncated": truncated,
        "counts": counts,
        "agents": agents,
        "own_principal": principal,
        "observed_principals": visible,
        "excluded_principals": sorted(excluded),
        "scope": "own" if visible == [principal] else "team_observer",
        "scope_note": "own work plus team members this principal may observe read-only; "
        "excluded principals are not observed, and all-agent acceptance is a separate gate",
        "text_scope": "read-only live projection from the existing observation and durable "
        "task records; not durable audit; no invented percentages; a present process or a "
        "closed transport turn is not confirmed facharbeit",
    }
    result["summary_text"] = render_text(result)
    return result


def render_text(projection, *, limit=12):
    """Short, human-readable text for Kira/ChatGPT: no code or raw logs."""
    agents = projection.get("agents", [])[:limit]
    if not agents:
        return "No observed agent work right now."
    lines = []
    for agent in agents:
        step = agent.get("step") or agent["state"]
        stale = " (stale)" if agent.get("stale") else ""
        lines.append(f"{agent['family']} · {agent['state']}{stale} · {step} · {agent['task_id']}")
    return "\n".join(lines)
