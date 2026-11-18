"""Four managed turns for one assignee must run in separate processes at once."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team

from kirabridge.bridge_core.bridge import INPUTS
from kirabridge.bridge_core.config import AgentConfig, Config, PrincipalConfig, TeamWorkerConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer

MARKS = ("MARK-one", "MARK-two", "MARK-three", "MARK-four")


@pytest.fixture
def config(tmp_path):
    # TaskManager.start copies Config.concurrency into the normal-lane workers
    # once. Raising it later does not add workers, so the bridge must see 4
    # before the http fixture enters it. Team receivers read team.concurrency
    # the same way when the dispatcher starts.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = PrincipalConfig(
        capabilities=[*INPUTS, "bridge.health", "task.read", "task.cancel", "agent.inspect"],
        roots=[str(workspace)],
        executables=[sys.executable],
        agents=["codex", "grok"],
    )
    result = Config(
        data_dir=str(tmp_path / "state"),
        concurrency=4,
        principals={"local": policy, "other": policy.model_copy(deep=True)},
    )
    result.visible_handoffs.enabled = False
    result.team.concurrency = 4
    return result


def _blocking_grok(log_path):
    return f"""import json, os, sys, time
LOG = {str(log_path)!r}

def current_body(message):
    params = message.get("params") or {{}}
    chunks = params.get("prompt") or []
    text = ""
    if isinstance(chunks, list):
        for chunk in chunks:
            if isinstance(chunk, dict):
                text += chunk.get("text") or ""
    elif isinstance(chunks, str):
        text = chunks
    key = '{{"context_truncated":'
    start = text.rfind(key)
    if start < 0:
        return "MARK-missing"
    body = json.loads(text[start:]).get("current_work", {{}}).get("body")
    if isinstance(body, str) and body.startswith("MARK-"):
        return body
    return "MARK-missing"

session = None
resumed = False
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        result = {{"protocolVersion": 1, "authMethods": [{{"id": "cached_token"}}]}}
    elif method == "authenticate":
        result = {{}}
    elif method == "session/new":
        session = "grok-parallel-%s-%s" % (os.getpid(), time.time_ns())
        result = {{"sessionId": session}}
    elif method == "session/load":
        session = msg["params"]["sessionId"]
        resumed = True
        result = {{}}
    elif method == "session/prompt":
        mark = current_body(msg)
        start = time.time()
        time.sleep(0.6)
        end = time.time()
        payload = json.dumps({{
            "pid": os.getpid(),
            "start": start,
            "end": end,
            "session_id": session,
            "resumed": resumed,
            "mark": mark,
        }}) + "\\n"
        fd = os.open(LOG, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        os.write(fd, payload.encode())
        os.close(fd)
        params = {{
            "sessionId": session,
            "update": {{
                "sessionUpdate": "agent_message_chunk",
                "content": {{"type": "text", "text": mark}},
            }},
        }}
        notice = {{"jsonrpc": "2.0", "method": "session/update", "params": params}}
        print(json.dumps(notice), flush=True)
        result = {{"stopReason": "end_turn"}}
    else:
        continue
    print(json.dumps({{"jsonrpc": "2.0", "id": msg["id"], "result": result}}), flush=True)
"""


def _stall_report(bridge, log_path):
    work_rows = [
        dict(row)
        for row in bridge.store.db.execute(
            "SELECT id, state, error, result, resume_session, core_task_id FROM team_work"
        )
    ]
    task_rows = [dict(row) for row in bridge.store.db.execute("SELECT id, state, error FROM tasks")]
    session_rows = [dict(row) for row in bridge.store.db.execute("SELECT * FROM team_sessions")]
    log_text = log_path.read_text() if log_path.exists() else ""
    return f"work={work_rows}\ntasks={task_rows}\nsessions={session_rows}\nlog={log_text!r}"


def _peak_overlap(rows):
    events = []
    for row in rows:
        events.append((row["start"], 1))
        events.append((row["end"], -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = peak = 0
    for _moment, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


async def _create_work(clients, mark):
    made = await clients.call(
        "local",
        "team_work_create",
        {
            "request": {
                "team_id": "parallel-team",
                "assignee": "grok",
                "title": "Parallel " + mark,
                "body": mark,
                "idempotency_key": "parallel-" + mark,
            }
        },
    )
    assert not made.structuredContent.get("error")
    return made.structuredContent["id"]


async def test_same_assignee_runs_four_managed_sessions_concurrently(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    assert config.concurrency == 4 and config.team.concurrency == 4
    assert len(bridge.tasks.workers) == config.concurrency + config.read_concurrency + 1
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    log_path = Path(root) / "team-parallel-sessions.log"
    agent_dir = tmp_path / "team-grok-parallel"
    agent_dir.mkdir()
    config.team.workers["grok"] = TeamWorkerConfig(
        agent="grok",
        cwd=root,
        timeout=15,
        execution_scope="separate_managed_session",
    )
    config.agents["grok"] = AgentConfig(
        kind="grok_acp",
        executable=fake_cli(agent_dir, _blocking_grok(log_path)),
    )
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        made = await clients.call(
            "local",
            "team_create",
            {
                "request": {
                    "team_id": "parallel-team",
                    "name": "Parallel",
                    "coordinator": "local",
                    "members": {"local": "coordinator", "grok": "worker"},
                    "idempotency_key": "parallel-team",
                }
            },
        )
        assert not made.structuredContent.get("error")
        created = [await _create_work(clients, mark) for mark in MARKS]
        await bridge.team_dispatcher.start()
        assert len(bridge.team_dispatcher.workers) == 4
        listed = {}
        terminal = {"completed", "failed", "unknown", "cancelled", "blocked"}
        try:
            async with asyncio.timeout(20):
                while True:
                    listed = (
                        await clients.call(
                            "local",
                            "team_work_list",
                            {"team_id": "parallel-team", "after": 0, "limit": 20},
                        )
                    ).structuredContent
                    rows = listed.get("work", [])
                    if len(rows) == 4 and all(row["state"] in terminal for row in rows):
                        break
                    await asyncio.sleep(0.05)
        except TimeoutError:
            pytest.fail("timed out before four turns finished\n" + _stall_report(bridge, log_path))
        if any(row["state"] != "completed" for row in listed.get("work", [])):
            pytest.fail("a finished turn was not completed\n" + _stall_report(bridge, log_path))
    by_body = {row["body"]: row for row in listed["work"]}
    assert set(by_body) == set(MARKS)
    assert [by_body[mark]["id"] for mark in MARKS] == created
    sessions = []
    for mark in MARKS:
        work = by_body[mark]
        assert work["state"] == "completed"
        assert work["result"] == mark
        assert work["assignee"] == "grok"
        assert work["resume_session"] is None
        assert work["evidence"]["session_resumed"] is False
        sessions.append(work["evidence"]["session_id"])
    assert len(set(sessions)) == 4
    logged = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    assert len(logged) == 4
    by_mark = {row["mark"]: row for row in logged}
    assert set(by_mark) == set(MARKS)
    pids = []
    for mark in MARKS:
        row = by_mark[mark]
        assert row["resumed"] is False
        assert row["session_id"] == by_body[mark]["evidence"]["session_id"]
        assert row["end"] - row["start"] >= 0.5
        pids.append(row["pid"])
    assert len(set(pids)) == 4
    assert len({row["session_id"] for row in logged}) == 4
    peak = _peak_overlap(logged)
    print(f"parallel_peak={peak}")
    assert peak >= 3, (
        "sessions ran serially or with too little overlap; "
        f"peak={peak} intervals={[(row['mark'], row['start'], row['end']) for row in logged]}"
    )
    stored = bridge.store.db.execute(
        "SELECT team_id, principal, state FROM team_sessions"
    ).fetchall()
    assert stored
    assert all(row["state"] != "active" for row in stored)
    idle_pairs = [(row["team_id"], row["principal"]) for row in stored if row["state"] == "idle"]
    assert len(idle_pairs) == len(set(idle_pairs))
    assert idle_pairs == [("parallel-team", "grok")]
