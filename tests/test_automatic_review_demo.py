"""Automatic demo boundary tests; CLI processes here are explicit test doubles."""

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401

from kirabridge.automatic_review_demo import AutomaticDemo, validate_evidence
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def demo_for_test(tmp_path, config):
    root = tmp_path / "demo"
    root.mkdir()
    demo = AutomaticDemo(root, sys.executable, Path(__file__), timeout=2)
    demo.site = Path(config.principals["local"].roots[0])
    policy = config.principals["local"].model_copy(deep=True)
    policy.approval_mode = "automatic"
    config.principals["codex"] = policy
    return demo


async def test_real_http_task_null_error_completion_and_idempotency(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,  # noqa: F811
):
    bridge, endpoint = http_bridge
    demo = demo_for_test(tmp_path, config)
    monkeypatch.setenv("DEMO_TEST_TOKEN", "demo-test-" + "x" * 40)
    config.principals["codex"].token_env = "DEMO_TEST_TOKEN"
    cli = fake_cli(
        tmp_path,
        """import json,sys
sys.stdin.read()
open('invocations','a').write('1\\n')
for event in [{'type':'thread.started','thread_id':'explicit-test-session'},
              {'type':'turn.started'}, {'type':'turn.completed'}]:
 print(json.dumps(event),flush=True)
""",
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("codex", url=endpoint, token="demo-test-" + "x" * 40))
        demo.pool = pool
        first = await demo.turn("test-turn", "test double, no provider")
        second = await demo.turn("test-turn", "test double, no provider")
        assert first["id"] == second["id"]
        assert (demo.site / "invocations").read_text() == "1\n"
        (demo.root / "STOP").touch()
        with pytest.raises(RuntimeError, match="operator_stop"):
            await demo.turn("blocked", "must not dispatch")
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


async def test_stop_terminates_only_owned_test_process(http_bridge, config, tmp_path, monkeypatch):  # noqa: F811
    bridge, endpoint = http_bridge
    demo = demo_for_test(tmp_path, config)
    demo.timeout = 5
    monkeypatch.setenv("DEMO_STOP_TOKEN", "demo-stop-" + "x" * 40)
    config.principals["codex"].token_env = "DEMO_STOP_TOKEN"
    cli = fake_cli(
        tmp_path,
        """import json,sys,time
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'owned-stop-test'}),flush=True)
print(json.dumps({'type':'turn.started'}),flush=True)
time.sleep(30)
""",
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("codex", url=endpoint, token="demo-stop-" + "x" * 40))
        demo.pool = pool
        task = asyncio.create_task(demo.turn("stop-test", "explicit sleeping test process"))
        async with asyncio.timeout(5):
            while True:
                row = bridge.store.db.execute(
                    "SELECT state FROM tasks WHERE id='stop-test'"
                ).fetchone()
                if row and row[0] == "running":
                    break
                await asyncio.sleep(0.02)
        (demo.root / "STOP").touch()
        with pytest.raises(RuntimeError, match="operator_stop"):
            await task
        stopped = await bridge.tasks.wait("codex", "stop-stop-test", 5)
        assert stopped["state"] == "completed"
        async with asyncio.timeout(5):
            while "stop-test" in bridge.terminal.sessions:
                await asyncio.sleep(0.02)
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2


def test_actual_acceptance_evidence_and_cross_link_rejection():
    root = Path(__file__).resolve().parents[1] / "examples/review-demo/automatic-20261019-02"
    data = json.loads((root / "evidence.json").read_text())
    validate_evidence(root, data)
    changed = copy.deepcopy(data)
    changed["messages"][2]["reply_to"] = "unrelated-review"
    with pytest.raises(RuntimeError, match="correlation"):
        validate_evidence(root, changed)
    changed = copy.deepcopy(data)
    changed["browser"]["page_sha256"] = "stale"
    with pytest.raises(RuntimeError, match="correlation"):
        validate_evidence(root, changed)
    readback = json.loads((root / "connector-readback.json").read_text())
    assert readback["result"]["state"] == "completed"
    assert readback["result"]["result"]["text"] == (root / "site/index.html").read_text()


@pytest.mark.parametrize("outcome,expected", [("failed", "failed"), ("timeout", "unknown")])
async def test_failed_or_timed_out_turn_is_never_retried(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
    outcome,
    expected,  # noqa: F811
):
    bridge, endpoint = http_bridge
    demo = demo_for_test(tmp_path, config)
    demo.timeout = 0.5 if outcome == "timeout" else 2
    monkeypatch.setenv("DEMO_ERROR_TOKEN", "demo-error-" + "x" * 40)
    config.principals["codex"].token_env = "DEMO_ERROR_TOKEN"
    body = """import json,sys,time
sys.stdin.read()
open('error-invocations','a').write('1\\n')
print(json.dumps({'type':'thread.started','thread_id':'explicit-error-test'}),flush=True)
print(json.dumps({'type':'turn.started'}),flush=True)
"""
    body += (
        "time.sleep(30)"
        if outcome == "timeout"
        else "print(json.dumps({'type':'turn.failed'}),flush=True)"
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=fake_cli(tmp_path, body))
    async with MCPClientPool() as pool:
        await pool.connect(Peer("codex", url=endpoint, token="demo-error-" + "x" * 40))
        demo.pool = pool
        with pytest.raises(RuntimeError, match="execution not confirmed"):
            await demo.turn("error-test", "explicit failing test double")
        assert bridge.store.get("error-test", "codex")["state"] == expected
        assert (demo.site / "error-invocations").read_text() == "1\n"
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert not bridge.terminal.sessions
