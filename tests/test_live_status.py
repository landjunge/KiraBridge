"""KiraBridge Live projection: read-only, honest state, same via MCP, no archive."""

import json
import time

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.live_status import MAX_AGENTS, project, render_text


def _local(bridge):
    bridge.config.principals["local"].capabilities.append("logs.live")
    return bridge


def _open(bridge, source_id, **kw):
    bridge.live_logs.open(source_id, "local", operation="agent.execute", **kw)


def test_projection_maps_live_state_and_short_step(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="codex", transport="codex")
    bridge.live_logs.feed("t1", "local", {"event": "step_start", "agent": "codex"})
    rows = project(bridge, "local")["agents"]
    assert len(rows) == 1
    row = rows[0]
    assert row["family"] == "codex"
    assert row["state"] == "working" and row["step"] == "working"
    assert row["source"] == "live_observation" and row["unknown"] is False
    assert row["observed_at"] > 0 and "age_seconds" in row

    bridge.live_logs.close("t1", exit_code=0)
    done = project(bridge, "local")["agents"][0]
    assert done["state"] == "completed" and done["step"] == "done"


def test_projection_marks_stale_running_as_unknown(bridge):
    _local(bridge)
    _open(bridge, "t1", agent="grok")
    bridge.live_logs.sources["t1"].updated = time.time() - 3600
    row = project(bridge, "local", now=time.time())["agents"][0]
    assert row["state"] == "unknown" and row["stale"] is True and row["unknown"] is True


def test_projection_is_principal_scoped(bridge):
    _local(bridge)
    _open(bridge, "mine", agent="codex")
    bridge.live_logs.open("theirs", "other", operation="agent.execute", agent="grok")
    assert [a["task_id"] for a in project(bridge, "local")["agents"]] == ["mine"]
    bridge.config.principals["other"].capabilities.append("logs.live")
    assert [a["task_id"] for a in project(bridge, "other")["agents"]] == ["theirs"]


def test_projection_requires_the_logs_capability(bridge):
    bridge.config.principals["local"].capabilities.remove("logs.live")
    with pytest.raises(BridgeError, match="Capability"):
        project(bridge, "local")


def test_projection_includes_queued_durable_task_without_a_live_source(bridge):
    _local(bridge)
    bridge.store.db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,agent,state,"
        "created,updated,attempt) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
        (
            "queued-1",
            "local",
            "queued-1",
            "hash",
            "agent.execute",
            json.dumps({"agent": "opencode", "prompt": "SECRET-PROMPT"}),
            "opencode",
            "queued",
            time.time(),
            time.time(),
        ),
    )
    rows = project(bridge, "local")["agents"]
    assert [a["task_id"] for a in rows] == ["queued-1"]
    assert rows[0]["state"] == "queued" and rows[0]["source"] == "durable_task"
    assert rows[0]["family"] == "opencode"


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
