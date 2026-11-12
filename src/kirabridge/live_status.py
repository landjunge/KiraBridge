"""Compact, read-only projection of observed agent work for KiraBridge Live.

Derived only from the existing ``LiveLogHub`` observation and the durable task
records: it adds no queue, no second history/archive and no execution right.
The monitor window and the authorized MCP read return the *same* projection, so
a closed window never hides the read service. Steps are short human labels, not
terminal output; unknown or stale work is marked as such and no percentage or
"process present = work done" claim is invented.
"""

from __future__ import annotations

import json
import time

from kirabridge.bridge_core.models import BridgeError

# A running source that has not updated within this window is stale (unknown),
# not silently "working".
STALE_SECONDS = 120.0
# Hard bound so one poll cannot return an unbounded list.
MAX_AGENTS = 32
# Read only the newest durable tasks; they are a bounded supplement to the
# live sources, never a second queue.
MAX_TASKS = 32

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


def _family(agent, operation):
    if isinstance(agent, str) and agent:
        return agent
    if isinstance(operation, str) and operation:
        return operation.split(".", 1)[0]
    return "unknown"


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


def _source_row(source, principal, now):
    age = max(0.0, now - float(source.updated))
    stale = age > STALE_SECONDS and source.state == "running"
    state = "unknown" if stale else SOURCE_STATE.get(source.state, "unknown")
    if state == "completed":
        step = "done"
    elif state == "blocked":
        step = "failed"
    else:
        step = _step(source.entries)
    return {
        "task_id": source.source_id,
        "agent": source.agent,
        "family": _family(source.agent, source.operation),
        "transport": source.transport,
        "operation": source.operation,
        "state": state,
        "step": step,
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
    return {
        "task_id": row["id"],
        "agent": agent,
        "family": _family(agent, row["operation"]),
        "transport": "durable_task",
        "operation": row["operation"],
        "state": state,
        "step": "queued" if state == "queued" else None,
        "observed_at": observed,
        "age_seconds": round(max(0.0, now - observed), 3),
        "stale": False,
        "unknown": False,
        "source": "durable_task",
    }


def project(bridge, principal, *, now=None):
    """Return the compact, read-only live projection for one principal.

    Reads only the principal's own live sources and durable tasks. No prompts,
    thoughts, secrets, raw logs, percentages or archive are produced.
    """
    bridge.security.principal(principal, "logs.live")
    observed_at = float(now if now is not None else time.time())
    agents = [
        _source_row(source, principal, observed_at)
        for source in bridge.live_logs.sources.values()
        if source.principal == principal
    ]
    seen = {agent["task_id"] for agent in agents}
    rows = bridge.store.db.execute(
        "SELECT id, principal, operation, args, agent, state, created, started FROM tasks "
        "WHERE principal=? AND state IN ('queued','accepted','running') "
        "ORDER BY created DESC LIMIT ?",
        (principal, MAX_TASKS),
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
        "scope": "read-only live projection from the existing observation and durable "
        "task records; not durable audit; no invented percentages; a present process "
        "is not confirmed facharbeit",
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


def require_catalog(bridge, principal):
    """Reject a principal without the existing live-observation capability."""
    if getattr(bridge, "live_logs", None) is None:
        raise BridgeError("logs_unavailable", "Live observation is not configured")
    bridge.security.principal(principal, "logs.live")
