"""Compact, read-only projection of observed agent work for KiraBridge Live.

Derived only from the existing ``LiveLogHub`` observation and the durable task
records: it adds no queue, no second history/archive and no execution right.
The monitor window and the authorized MCP read return the *same* projection, so
a closed window never hides the read service.

The caller sees their own observed work plus, only when an existing team grant
(owner/coordinator/observer) allows a read-only cross-principal observation, the
team's worker principals. The projection states that scope, the excluded
principals and the source gaps explicitly; actual all-agent acceptance remains a
separate gate.

States describe the observed process or task, never the fachliche Abnahme. A
recorded failure (exit code other than 0, a recorded error, a failed source or a
failed durable task) is shown as blocked; a closed transport without any exit
status is unknown, not completed. A turn that ended with exit 0 is labelled
``turn ended`` and keeps ``acceptance: not_evaluated`` — never "agent work
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


def _failure(source):
    """Failure evidence the existing source already recorded; never guessed.

    Only the category is exposed, not the recorded error text, so an error
    message cannot leak paths, prompts or secrets into the projection.
    """
    if source.error is not None:
        return "error"
    if isinstance(source.exit_code, int) and source.exit_code != 0:
        return "exit_code"
    if source.state == "failed":
        return "failed_state"
    return None


def _task_result(task):
    """The durable task result, if it is the JSON object it should be."""
    if not isinstance(task["result"], str) or not task["result"]:
        return None
    try:
        value = json.loads(task["result"])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


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


def _source_row(source, now, task=None):
    age = max(0.0, now - float(source.updated))
    stale = age > STALE_SECONDS and source.state == "running"
    failure = _failure(source)
    settled = task["state"] if task is not None else None
    uncertain = settled == "unknown"
    if uncertain:
        # A proven uncertain effect (UncertainExecution or a possibly observed
        # side effect) already settled the durable task as unknown with
        # automatic_retry false. That evidence wins over a source-level
        # error/failed flag: it is not a confirmed failure and must not look
        # like one.
        failure = None
    exit_code = source.exit_code if isinstance(source.exit_code, int) else None
    # The durable task record for the same id already holds the settled outcome:
    # success false becomes State.FAILED and an error is stored verbatim. Read
    # that evidence instead of turning a failed turn into a success.
    if task is not None and not uncertain:
        result = _task_result(task)
        if failure is None and task["error"]:
            failure = "error"
        if failure is None and task["state"] == "failed":
            failure = "unsuccessful"
        if exit_code is None and result is not None:
            stored = result.get("exit_code")
            if isinstance(stored, int):
                exit_code = stored
                if stored != 0 and failure is None:
                    failure = "exit_code"
    turn_ended = source.state in {"closed", "failed"} or settled in {"completed", "failed"}
    if stale:
        state, step = "unknown", "stale"
    elif uncertain:
        # Unknown stays unknown: no confirmed failure, no retry implication.
        state, step = "unknown", "outcome uncertain, not retried"
    elif failure is not None:
        state, step = "blocked", "failed"
    elif source.state == "closed" or settled == "completed":
        if exit_code == 0 or (exit_code is None and settled == "completed"):
            state, step = "completed", "turn ended"
        else:
            # Closed without any recorded exit status: the outcome is
            # unconfirmed and is never presented as a successful completion.
            state, step = "unknown", "turn ended, result unconfirmed"
    else:
        state = SOURCE_STATE.get(source.state, "unknown")
        step = None
    return {
        "task_id": source.source_id,
        "principal": source.principal,
        "agent": source.agent,
        "family": _family(source.agent),
        "transport": source.transport,
        "operation": source.operation,
        "state": state,
        "step": step if step is not None else _step(source.entries),
        "turn_ended": turn_ended,
        "acceptance": "not_evaluated",
        "exit_code": exit_code,
        "failure": failure,
        "uncertain": uncertain,
        "observed_at": float(source.updated),
        "age_seconds": round(age, 3),
        "stale": stale,
        "unknown": state == "unknown",
        "source": "live_observation",
    }


def _durable_row(row, now):
    failed = row["state"] == "failed"
    uncertain = row["state"] == "unknown"
    if row["state"] in {"queued", "accepted"}:
        state = "queued"
    elif failed:
        state = "blocked"
    elif uncertain:
        # An uncertain effect is not working and not a confirmed failure.
        state = "unknown"
    else:
        state = "working"
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
    if state == "queued":
        step = "queued"
    elif stale:
        step = "stale"
    elif failed:
        step = "failed"
    elif uncertain:
        step = "outcome uncertain, not retried"
    else:
        step = None
    return {
        "task_id": row["id"],
        "principal": row["principal"],
        "agent": agent,
        "family": _family(agent),
        "transport": "durable_task",
        "operation": row["operation"],
        "state": state,
        "step": step,
        "turn_ended": failed,
        "acceptance": "not_evaluated",
        "exit_code": None,
        "failure": "task_error" if failed else None,
        "uncertain": uncertain,
        "observed_at": observed,
        "age_seconds": round(age, 3),
        "stale": stale,
        "unknown": state == "unknown",
        "source": "durable_task",
    }


def _coverage():
    """What this projection can and cannot see; stated, not implied."""
    return {
        "observed_sources": ["live_observation", "durable_task"],
        "not_observed": "External agents that write neither a bridge live source nor a "
        "bridge task are not observed here — for example an agent started outside "
        "KiraBridge, an adapter without live observation, or a principal outside the "
        "reported scope. The list shows only what the bridge actually observed.",
        "acceptance": "This projection never derives a fachliche Abnahme. A running "
        "process or an ended turn is not confirmed work; acceptance is a separate gate.",
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
    live_sources = [
        source for source in bridge.live_logs.sources.values() if source.principal in visible
    ]
    # Settled outcome evidence for the observed live sources, read from the
    # existing durable task record with the same id (no new store, no inference).
    evidence = {}
    if live_sources:
        ids = sorted({source.source_id for source in live_sources})
        id_marks = ",".join("?" for _ in ids)
        principal_marks = ",".join("?" for _ in visible)
        for row in bridge.store.db.execute(
            "SELECT id, state, error, result FROM tasks "
            f"WHERE id IN ({id_marks}) AND principal IN ({principal_marks})",
            (*ids, *visible),
        ).fetchall():
            evidence[row["id"]] = row
    agents = [
        _source_row(source, observed_at, evidence.get(source.source_id)) for source in live_sources
    ]
    seen = {agent["task_id"] for agent in agents}
    rows = []
    if visible:
        placeholders = ",".join("?" for _ in visible)
        rows = bridge.store.db.execute(
            "SELECT id, principal, operation, args, agent, state, error, created, started "
            "FROM tasks "
            f"WHERE principal IN ({placeholders}) "
            "AND state IN ('queued','accepted','running','failed','unknown') "
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
        "coverage": _coverage(),
        "text_scope": "read-only live projection from the existing observation and durable "
        "task records; not durable audit; no invented percentages; the state is a process "
        "or task state, and a running process or an ended turn is not confirmed facharbeit",
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
        family = agent.get("family") or "unknown"
        stale = " (stale)" if agent.get("stale") else ""
        task = agent["task_id"]
        if agent.get("failure"):
            evidence = (
                f"exit {agent['exit_code']}"
                if agent.get("exit_code") is not None
                else "failure recorded"
            )
            lines.append(
                f"{family} · blocked ({evidence}){stale} · {task} · "
                "fachliche Abnahme nicht bewertet"
            )
        elif agent["state"] == "completed":
            lines.append(
                f"{family} · turn ended, process only{stale} · {task} · "
                "fachliche Abnahme nicht bewertet"
            )
        elif agent["state"] == "unknown":
            lines.append(f"{family} · unknown{stale} · {agent.get('step') or 'unknown'} · {task}")
        else:
            step = agent.get("step") or agent["state"]
            lines.append(f"{family} · {agent['state']}{stale} · {step} · {task}")
    return "\n".join(lines)
