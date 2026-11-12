"""KiraBridge Live projection: read-only, honest state, same via MCP, no archive."""

import json
import time
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.live_status import MAX_AGENTS, observation_scope, project, render_text


def _local(bridge):
    if "logs.live" not in bridge.config.principals["local"].capabilities:
        bridge.config.principals["local"].capabilities.append("logs.live")
    return bridge


def _open(bridge, source_id, principal="local", **kw):
    bridge.live_logs.open(source_id, principal, operation="agent.execute", **kw)


def _durable(
    bridge,
    task_id,
    *,
    principal="local",
    state="queued",
    agent="opencode",
    age=0.0,
    error=None,
    result=None,
):
    created = time.time() - age
    bridge.store.db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,agent,state,"
        "created,updated,attempt,error,result) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (
            task_id,
            principal,
            task_id,
            "hash",
            "agent.execute",
            json.dumps({"agent": agent, "prompt": "SECRET-PROMPT"}),
            agent,
            state,
            created,
            created,
            error,
            json.dumps(result) if result is not None else None,
        ),
    )


def test_projection_maps_live_state_and_short_step(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="codex", transport="codex")
    bridge.live_logs.feed("t1", "local", {"event": "step_start", "agent": "codex"})
    row = project(bridge, "local")["agents"][0]
    assert row["family"] == "codex"
    assert row["state"] == "working" and row["step"] == "working"
    assert row["source"] == "live_observation" and row["unknown"] is False
    assert row["acceptance"] == "not_evaluated" and row["turn_ended"] is False

    bridge.live_logs.close("t1", exit_code=0)
    done = project(bridge, "local")["agents"][0]
    # A closed transport turn is not "agent work completed".
    assert done["state"] == "completed" and done["step"] == "turn ended"
    assert done["turn_ended"] is True and done["acceptance"] == "not_evaluated"


def test_projection_marks_stale_running_as_unknown(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="grok")
    bridge.live_logs.sources["t1"].updated = time.time() - 3600
    row = project(bridge, "local", now=time.time())["agents"][0]
    assert row["state"] == "unknown" and row["stale"] is True and row["unknown"] is True


def test_projection_marks_stale_durable_running_as_unknown(bridge):
    _local(bridge)
    _durable(bridge, "run-old", state="running", agent="qwen", age=3600)
    row = project(bridge, "local", now=time.time())["agents"][0]
    assert row["state"] == "unknown" and row["stale"] is True
    assert row["acceptance"] == "not_evaluated"


def test_projection_is_principal_scoped_by_default(bridge):
    _local(bridge)
    _open(bridge, "mine", agent="codex")
    _open(bridge, "theirs", principal="other", agent="grok")
    assert [a["task_id"] for a in project(bridge, "local")["agents"]] == ["mine"]
    assert project(bridge, "local")["scope"] == "own"


def test_team_observer_scope_reports_observed_and_excluded_principals(bridge):
    _local(bridge)
    bridge.config.principals["local"].capabilities.append("team.read")
    bridge.config.principals["other"].capabilities.append("team.read")

    def fake_teams(role, members):
        return SimpleNamespace(
            list=lambda _principal: {
                "teams": [
                    {
                        "id": "t",
                        "members": {
                            name: {"role": role if name == "local" else "worker", "active": True}
                            for name in members
                        },
                    }
                ]
            }
        )

    bridge.teams = fake_teams("observer", ["local", "other"])
    _open(bridge, "mine", agent="codex")
    _open(bridge, "theirs", principal="other", agent="grok")
    observed = project(bridge, "local")
    assert {a["task_id"] for a in observed["agents"]} == {"mine", "theirs"}
    assert observed["scope"] == "team_observer"
    assert observed["observed_principals"] == ["local", "other"]

    bridge.teams = fake_teams("worker", ["local", "other"])
    scoped = project(bridge, "local")
    assert [a["task_id"] for a in scoped["agents"]] == ["mine"]
    assert scoped["excluded_principals"] == ["other"]
    assert observation_scope(bridge, "local") == ({"local"}, {"other"})


def test_projection_requires_the_logs_capability(bridge):
    bridge.config.principals["local"].capabilities.remove("logs.live")
    with pytest.raises(BridgeError, match="Capability"):
        project(bridge, "local")


def test_projection_includes_queued_durable_task_without_a_live_source(bridge):
    _local(bridge)
    _durable(bridge, "queued-1", state="queued", agent="opencode")
    rows = project(bridge, "local")["agents"]
    assert [a["task_id"] for a in rows] == ["queued-1"]
    assert rows[0]["state"] == "queued" and rows[0]["source"] == "durable_task"
    assert rows[0]["family"] == "opencode"
    assert "SECRET-PROMPT" not in json.dumps(project(bridge, "local"))


def test_family_never_uses_the_operation_namespace(bridge):
    _local(bridge)
    _open(bridge, "t1")  # no agent set
    row = project(bridge, "local")["agents"][0]
    assert row["family"] == "unknown"
    _durable(bridge, "d1", state="queued", agent=None)
    durable = [a for a in project(bridge, "local")["agents"] if a["task_id"] == "d1"][0]
    assert durable["family"] == "unknown"


def test_projection_never_exposes_raw_output_or_prompt(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="qwen")
    bridge.live_logs.append("t1", "local", "stdout", "SECRET-STDOUT")
    bridge.live_logs.feed(
        "t1", "local", {"event": "text", "agent": "qwen", "text": "SECRET-ASSISTANT"}
    )
    rendered = json.dumps(project(bridge, "local"))
    assert "SECRET-STDOUT" not in rendered
    assert "SECRET-ASSISTANT" not in rendered
    assert project(bridge, "local")["agents"][0]["step"] == "responding"


def test_text_summary_is_short_and_honest(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="codex")
    bridge.live_logs.feed("t1", "local", {"event": "step_start"})
    text = project(bridge, "local")["summary_text"]
    assert "codex" in text and "working" in text and "t1" in text
    assert render_text({"agents": []}) == "No observed agent work right now."


def test_projection_is_bounded(bridge):
    _local(bridge)
    for index in range(MAX_AGENTS + 5):
        _open(bridge, f"t{index}", agent="codex")
    result = project(bridge, "local")
    assert result["count"] == MAX_AGENTS and result["truncated"] is True


def test_nonzero_exit_code_is_blocked_never_completed(bridge):
    _local(bridge)
    _open(bridge, "bad", agent="codex", transport="codex")
    bridge.live_logs.close("bad", exit_code=1)
    row = project(bridge, "local")["agents"][0]
    # exit != 0 comes from the existing source and must not read as success.
    assert row["state"] == "blocked"
    assert row["failure"] == "exit_code" and row["exit_code"] == 1
    assert row["step"] == "failed"
    assert row["turn_ended"] is True and row["acceptance"] == "not_evaluated"
    summary = project(bridge, "local")["summary_text"]
    assert "blocked" in summary and "exit 1" in summary
    assert "completed" not in summary


def test_recorded_error_is_blocked_even_with_exit_zero(bridge):
    _local(bridge)
    _open(bridge, "err", agent="grok")
    bridge.live_logs.close("err", exit_code=0, error="approval_denied")
    row = project(bridge, "local")["agents"][0]
    # A recorded error wins over an exit code that would otherwise look clean.
    assert row["state"] == "blocked" and row["failure"] == "error"
    # The recorded error text itself is not exposed.
    assert "approval_denied" not in json.dumps(project(bridge, "local"))


def test_closed_without_exit_status_is_unknown_not_completed(bridge):
    _local(bridge)
    _open(bridge, "bare", agent="qwen")
    bridge.live_logs.close("bare")
    row = project(bridge, "local")["agents"][0]
    assert row["state"] == "unknown" and row["unknown"] is True
    assert row["step"] == "turn ended, result unconfirmed"
    assert row["exit_code"] is None and row["failure"] is None
    assert row["turn_ended"] is True and row["acceptance"] == "not_evaluated"


def test_exit_zero_completed_keeps_process_and_acceptance_separate(bridge):
    _local(bridge)
    _open(bridge, "ok", agent="codex")
    bridge.live_logs.close("ok", exit_code=0)
    row = project(bridge, "local")["agents"][0]
    assert row["state"] == "completed" and row["step"] == "turn ended"
    assert row["exit_code"] == 0 and row["failure"] is None
    assert row["acceptance"] == "not_evaluated" and row["turn_ended"] is True
    summary = project(bridge, "local")["summary_text"]
    # Process/turn end and fachliche Abnahme are stated separately.
    assert "turn ended, process only" in summary
    assert "fachliche Abnahme nicht bewertet" in summary
    assert "completed" not in summary


def test_failed_durable_task_is_blocked(bridge):
    _local(bridge)
    _durable(bridge, "failed-1", state="failed", agent="opencode", error="exec_spawn_failed")
    row = project(bridge, "local")["agents"][0]
    assert row["state"] == "blocked" and row["failure"] == "task_error"
    assert row["step"] == "failed" and row["acceptance"] == "not_evaluated"
    assert "exec_spawn_failed" not in json.dumps(project(bridge, "local"))


def test_success_false_durable_outcome_overrides_a_clean_exit_code(bridge):
    _local(bridge)
    _durable(
        bridge,
        "turn",
        state="failed",
        agent="codex",
        result={"success": False, "exit_code": 0},
    )
    _open(bridge, "turn", agent="codex")
    bridge.live_logs.close("turn", exit_code=0)
    row = project(bridge, "local")["agents"][0]
    # success false is already settled in the durable task (state failed); a
    # clean exit code must not turn it into a success-like display.
    assert row["state"] == "blocked" and row["failure"] == "unsuccessful"
    assert row["turn_ended"] is True and row["acceptance"] == "not_evaluated"
    assert "blocked" in project(bridge, "local")["summary_text"]


def test_completed_durable_outcome_allows_completed_without_exit_code(bridge):
    _local(bridge)
    _durable(bridge, "turn", state="completed", agent="grok", result={"success": True})
    _open(bridge, "turn", agent="grok")
    bridge.live_logs.close("turn")
    row = project(bridge, "local")["agents"][0]
    # The durable record settled as completed, so the transport end is a
    # process completion — still not a fachliche Abnahme.
    assert row["state"] == "completed" and row["step"] == "turn ended"
    assert row["acceptance"] == "not_evaluated"


def test_projection_states_what_it_cannot_observe(bridge):
    _local(bridge)
    coverage = project(bridge, "local")["coverage"]
    assert coverage["observed_sources"] == ["live_observation", "durable_task"]
    assert "are not observed here" in coverage["not_observed"]
    assert "never derives a fachliche Abnahme" in coverage["acceptance"]
    # Scope stays honest: no widening beyond own principal without a team role.
    assert project(bridge, "local")["excluded_principals"] == []
    assert project(bridge, "local")["scope"] == "own"
