"""Real bounded local processes/MCP transport; provider responses are simulations."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from conftest import archive_task, request
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401
from test_messages import channel  # noqa: F401

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.completion_client import CompletionClient
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def automatic(config):
    config.principals["local"].approval_mode = "automatic"


def terminal(config, code, task_id="work", timeout=3):
    return request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", code],
            "cwd": config.principals["local"].roots[0],
            "timeout": timeout,
        },
        task_id=task_id,
    )


async def test_immediate_completion_before_listener_and_route_is_atomic(bridge, config):
    automatic(config)
    value = terminal(config, "print('fast result')")
    async with bridge:
        bridge.prepare("local", value, completion_target="assistant-session-a")
        await bridge.tasks.wait("local", value.task_id)
        notice = (await bridge.completions.wait("local", "assistant-session-a", wait_seconds=0))[
            "notices"
        ][0]
        assert notice["payload"]["outcome"] == "success"
        assert "fast result" not in notice["payload"]["summary"]
        assert "fast result" in bridge.task("local", value.task_id)["result"]["stdout"]
        assert notice["payload"]["task_id"] == "work"
        assert not bridge.completions.receive("local", "assistant-session-b")["notices"]
        bridge.prepare("local", value, completion_target="assistant-session-a")
        with pytest.raises(BridgeError, match="fixed"):
            bridge.prepare("local", value, completion_target="assistant-session-b")
        assert len(bridge.completions.receive("local", "assistant-session-a")["notices"]) == 1


@pytest.mark.parametrize(
    "code,timeout,outcome",
    [
        ("raise SystemExit(7)", 3, "error"),
        ("import time; time.sleep(30)", 0.1, "timeout"),
        ("print('quota exhausted in ordinary output'); raise SystemExit(2)", 3, "error"),
    ],
)
async def test_terminal_failure_timeout_and_no_speculative_quota(
    bridge, config, code, timeout, outcome
):
    automatic(config)
    value = terminal(config, code, timeout=timeout)
    async with bridge:
        bridge.prepare("local", value)
        await bridge.tasks.wait("local", value.task_id)
        payload = bridge.completions.receive("local")["notices"][0]["payload"]
        assert payload["outcome"] == outcome
        assert payload["quota_diagnosis"] == "not_established"
        assert not bridge.terminal.sessions


async def test_unknown_recovery_session_then_reconciliation_are_distinct_notices(bridge, config):
    automatic(config)
    value = terminal(config, "print('not actually started')")
    archive_task(bridge, value, "local")
    bridge.store.claim("dead", 10)
    bridge.store.transition("work", State.RUNNING, {"session_id": "owned-session"}, owner="dead")
    assert bridge.store.recover() == 1
    unknown = bridge.completions.receive("local")["notices"][0]
    assert unknown["payload"]["outcome"] == "unknown"
    assert unknown["payload"]["session_id"] == "owned-session"
    assert unknown["payload"]["execution_outcome_unknown"]
    bridge.completions.ack("local", unknown["id"], unknown["receipt"])
    bridge.tasks.reconcile("work", State.COMPLETED, "operator reference, not provider execution")
    corrected = bridge.completions.receive("local")["notices"][0]
    assert corrected["id"] != unknown["id"]
    assert corrected["payload"]["session_id"] == "owned-session"
    assert corrected["payload"]["supersedes"] == unknown["id"]
    assert corrected["payload"]["completion_basis"] == "local_operator_attestation"
    assert corrected["payload"]["outcome"] == "success"
    assert not bridge.completions.receive("other")["notices"]
    with pytest.raises(BridgeError, match="not found"):
        bridge.completions.ack("other", corrected["id"], corrected["receipt"])


def test_state_and_notice_roll_back_together(bridge, config, monkeypatch):
    automatic(config)
    archive_task(bridge, terminal(config, "pass"), "local")
    bridge.store.claim("owner", 10)
    bridge.store.transition("work", State.RUNNING, {"pid": 123}, owner="owner")
    import kirabridge.completion_manager as module

    def fail(*args):
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(module, "record_task_completion", fail)
    with pytest.raises(RuntimeError, match="outbox"):
        bridge.store.transition("work", State.COMPLETED, {"exit_code": 0}, owner="owner")
    assert bridge.store.get("work")["state"] == "running"
    assert not bridge.completions.receive("local")["notices"]
    assert not bridge.store.db.execute("SELECT 1 FROM events WHERE state='completed'").fetchone()


async def test_cancel_pending_and_terminate_running_produce_cancelled_notice(bridge, config):
    bridge.prepare(
        "local", terminal(config, "pass", task_id="pending"), completion_target="pending"
    )
    bridge.tasks.cancel_queued("local", "pending")
    assert bridge.completions.receive("local", "pending")["notices"][0]["payload"]["outcome"] == (
        "cancelled"
    )
    automatic(config)
    async with bridge:
        bridge.prepare(
            "local",
            terminal(config, "import time;time.sleep(30)", timeout=10),
            completion_target="active",
        )
        async with asyncio.timeout(5):
            while bridge.store.get("work")["state"] != "running":
                await asyncio.sleep(0.02)
        await bridge.terminal.terminate("local", "work")
        await bridge.tasks.wait("local", "work")
        assert bridge.completions.receive("local", "active")["notices"][0]["payload"][
            "outcome"
        ] == ("cancelled")


@pytest.mark.parametrize(
    "code,category",
    [
        ("insufficient_quota", "quota_exhausted"),
        ("rate_limit_exceeded", "rate_limit"),
        (None, None),
    ],
)
async def test_codex_structured_provider_evidence_only(bridge, config, tmp_path, code, category):
    automatic(config)
    events = [
        {"type": "thread.started", "thread_id": "SIMULATED-provider-session"},
        {"type": "turn.started"},
        {"type": "turn.failed", "error": {"code": code, "message": "quota maybe"}},
    ]
    cli = fake_cli(
        tmp_path,
        "import sys\nsys.stdin.read()\n"
        + "\n".join("print(" + repr(json.dumps(event)) + ",flush=True)" for event in events),
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    value = request(
        "agent.execute",
        {
            "agent": "codex",
            "cwd": config.principals["local"].roots[0],
            "prompt": "test adapter only",
            "timeout": 3,
        },
    )
    async with bridge:
        bridge.prepare("local", value)
        await bridge.tasks.wait("local", value.task_id)
        payload = bridge.completions.receive("local")["notices"][0]["payload"]
        assert payload["session_id"] == "SIMULATED-provider-session"
        assert payload["outcome"] == ("provider_error" if category else "error")
        assert payload["quota_diagnosis"] == (
            "evidenced" if category == "quota_exhausted" else "not_established"
        )
        if category:
            assert payload["provider_error"]["event_sha256"]


async def test_longer_task_callback_without_status_polling_and_reconnect(
    http_bridge,  # noqa: F811
    config,  # noqa: F811
):
    bridge, endpoint = http_bridge
    automatic(config)
    peer = Peer("local", url=endpoint, token="local-test-" + "a" * 40)
    received, calls = [], []
    async with CompletionClient(peer) as listener:
        original = listener.pool.call

        async def traced(identity, tool, arguments):
            calls.append(tool)
            return await original(identity, tool, arguments)

        listener.pool.call = traced
        waiting = asyncio.create_task(listener.listen("assistant-long", received.append, once=True))
        await asyncio.sleep(0.05)
        async with MCPClientPool() as sender:
            await sender.connect(peer)
            await sender.call(
                "local",
                "task_request",
                {
                    "request": terminal(
                        config, "import time;time.sleep(0.8);print('long finished')"
                    ).model_dump(),
                    "completion_target": "assistant-long",
                },
            )
        notice = await asyncio.wait_for(waiting, 5)
        assert notice["payload"]["outcome"] == "success"
        assert [n["id"] for n in received] == [notice["id"]]
        assert "task_get" not in calls and "completion_receive" in calls
        assert not bridge.completions.receive("local", "assistant-long")["notices"]
        # Disconnect after delivery but before processing/ack. New connection gets same receipt.
        bridge.prepare(
            "local", terminal(config, "pass", task_id="reconnect"), completion_target="reconnect"
        )
        first = (await bridge.completions.wait("local", "reconnect"))["notices"][0]
        await listener.pool.disconnect("local")
        notices = []
        second = await listener.listen("reconnect", notices.append, once=True, timeout=5)
        assert second["id"] == first["id"] and second["receipt"] == first["receipt"]
        repeated = bridge.completions.ack("local", second["id"], second["receipt"])
        assert repeated["acknowledged"]
        with pytest.raises(BridgeError, match="Matching"):
            bridge.completions.ack("local", second["id"], "invalid")


async def test_callback_failure_leaves_notice_for_later_consumer(
    http_bridge,  # noqa: F811
    config,  # noqa: F811
):
    bridge, endpoint = http_bridge
    automatic(config)
    bridge.prepare("local", terminal(config, "pass"))
    await bridge.tasks.wait("local", "work")
    notice = bridge.completions.receive("local")["notices"][0]
    peer = Peer("local", url=endpoint, token="local-test-" + "a" * 40)

    def broken_callback(value):
        raise RuntimeError("simulated consumer interruption")

    async with CompletionClient(peer) as client:
        with pytest.raises(RuntimeError, match="consumer interruption"):
            await client.listen("default", broken_callback, once=True, timeout=5)
    reopened = Bridge(config)
    try:
        again = reopened.completions.receive("local")["notices"][0]
        assert (again["id"], again["receipt"]) == (notice["id"], notice["receipt"])
    finally:
        reopened.store.close()
    received = []
    async with CompletionClient(peer) as client:
        await client.listen("default", received.append, once=True, timeout=5)
    assert received[0]["id"] == notice["id"]
    assert not bridge.completions.receive("local")["notices"]


@pytest.mark.parametrize(
    "status,category",
    [(401, "authentication"), (429, "rate_limit"), (402, "provider"), (503, "provider")],
)
async def test_simulated_grok_http_status_is_not_quota_diagnosis(
    bridge, config, monkeypatch, status, category
):
    import httpx

    automatic(config)
    monkeypatch.setenv("SIMULATED_GROK_KEY", "not-a-real-key")
    config.agents["grok"] = AgentConfig(
        kind="grok_api", model="simulator", api_key_env="SIMULATED_GROK_KEY"
    )
    original = httpx.AsyncClient
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(status, json={"error": "simulated provider response"})

    monkeypatch.setattr(
        "kirabridge.agent_manager.httpx.AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    value = request(
        "agent.execute",
        {
            "agent": "grok",
            "prompt": "SIMULATION ONLY",
            "cwd": config.principals["local"].roots[0],
            "timeout": 2,
        },
    )
    async with bridge:
        bridge.prepare("local", value)
        await bridge.tasks.wait("local", value.task_id)
        payload = bridge.completions.receive("local")["notices"][0]["payload"]
        assert payload["outcome"] == "provider_error"
        assert payload["provider_error"]["http_status"] == status
        assert payload["provider_error"]["category"] == category
        assert payload["quota_diagnosis"] == "not_established"
        assert len(calls) == 1


async def test_unknown_codex_preserves_observed_structured_error(bridge, config, tmp_path):
    automatic(config)
    events = [
        {"type": "thread.started", "thread_id": "SIMULATED-incomplete"},
        {"type": "turn.started"},
        {"type": "error", "error": {"code": "insufficient_quota"}},
    ]
    cli = fake_cli(
        tmp_path,
        "import sys\nsys.stdin.read()\n"
        + "\n".join("print(" + repr(json.dumps(event)) + ",flush=True)" for event in events),
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    value = request(
        "agent.execute",
        {
            "agent": "codex",
            "prompt": "SIMULATION ONLY",
            "cwd": config.principals["local"].roots[0],
            "timeout": 2,
        },
    )
    async with bridge:
        bridge.prepare("local", value)
        await bridge.tasks.wait("local", value.task_id)
        payload = bridge.completions.receive("local")["notices"][0]["payload"]
        assert payload["state"] == "unknown" and payload["execution_outcome_unknown"]
        assert payload["session_id"] == "SIMULATED-incomplete"
        assert payload["provider_error"]["code"] == "insufficient_quota"
        assert payload["quota_diagnosis"] == "evidenced"


@pytest.mark.parametrize("failure", [False, True])
async def test_simulated_grok_receiver_completes_back_to_requesting_sender(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    failure,  # noqa: F811
):
    from test_messages import configure_receivers, message

    bridge, endpoint = http_bridge
    configure_receivers(bridge, config, tmp_path)
    if failure:
        failure_dir = tmp_path / "grok-failure"
        failure_dir.mkdir()
        config.agents["grok"] = AgentConfig(
            kind="grok_acp", executable=fake_cli(failure_dir, "raise SystemExit(4)")
        )
    await bridge.message_receiver.start()
    peer = Peer("codex", url=endpoint, token="codex-message-token-" + "x" * 40)
    async with MCPClientPool() as sender:
        await sender.connect(peer)
        request_message = message(dispatch=True, request_reply=False)
        result = await sender.call(
            "codex",
            "message_send",
            {"message": request_message.model_dump(), "completion_target": "sender-assistant"},
        )
        assert not result.isError
        message_id = result.structuredContent["id"]
    values = []
    async with CompletionClient(peer) as client:
        notice = await client.listen("sender-assistant", values.append, once=True, timeout=10)
    assert notice["payload"]["message_id"] == message_id
    assert notice["payload"]["source"] == "message"
    assert notice["payload"]["outcome"] == ("unknown" if failure else "success")
    assert notice["payload"]["quota_diagnosis"] == "not_established"
    if not failure:
        assert notice["payload"]["session_id"] == "managed-grok-session"
    assert not bridge.completions.receive("codex", "sender-assistant")["notices"]


async def test_completion_outlives_one_transport_wait_window(
    http_bridge,  # noqa: F811
    config,  # noqa: F811
):
    bridge, endpoint = http_bridge
    automatic(config)
    peer = Peer("local", url=endpoint, token="local-test-" + "a" * 40)
    count = 0
    values = []
    async with CompletionClient(peer) as client:
        original = client.pool.call

        async def traced(identity, tool, arguments):
            nonlocal count
            assert tool != "task_get"
            if tool == "completion_receive":
                count += 1
            return await original(identity, tool, arguments)

        client.pool.call = traced
        waiting = asyncio.create_task(
            client.listen("beyond-window", values.append, once=True, timeout=30)
        )
        bridge.prepare(
            "local",
            terminal(config, "import time;time.sleep(21);print('past window')", timeout=25),
            completion_target="beyond-window",
        )
        await waiting
    assert count >= 2
    assert len(values) == 1 and values[0]["payload"]["outcome"] == "success"


def test_child_tasks_inherit_originating_assistant_target(bridge, config):
    automatic(config)
    parent = terminal(config, "pass", task_id="origin")
    archive_task(bridge, parent, "local", completion_target="originating-session")
    child = request("terminal.execute", parent.arguments, task_id="child", parent="origin")
    archive_task(bridge, child, "local")
    route = bridge.store.db.execute(
        "SELECT target FROM completion_routes WHERE task_id='child'"
    ).fetchone()[0]
    assert route == "originating-session"


def test_visible_acceptance_has_actual_correlated_receipts_and_codex_session():
    root = Path(__file__).resolve().parents[1] / "examples/completion-demo/run-20261019-01"
    data = json.loads((root / "evidence.json").read_text())
    assert data["passed"] and data["audit"]["valid"]
    assert data["no_task_status_polling_by_consumer"]
    assert data["immediate_finished_before_listener"]
    assert data["reconnect_receipt_stable"]
    assert len(data["receipts"]) == len(data["acknowledged"]) == 6
    assert len({item["id"] for item in data["receipts"]}) == 6
    tasks = {task["id"]: task for task in data["tasks"]}
    assert not any(task.get("agent") == "grok" for task in tasks.values())
    for notice in data["receipts"]:
        task = tasks[notice["payload"]["task_id"]]
        assert notice["payload"]["state"] == task["state"]
        if task.get("agent") == "codex":
            assert notice["payload"]["session_id"] == task["result"]["evidence"]["session_id"]
            assert task["result"]["evidence"]["turn_completed"]
    assert all(item["acknowledged"] for item in data["acknowledged"])


async def test_terminated_codex_process_has_cancelled_notice_but_unknown_agent_outcome(
    bridge, config, tmp_path
):
    automatic(config)
    cli = fake_cli(
        tmp_path,
        """import json,sys,time
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'SIMULATED-cancelled-session'}),flush=True)
print(json.dumps({'type':'turn.started'}),flush=True)
time.sleep(30)
""",
    )
    config.agents["codex"] = AgentConfig(kind="codex", executable=cli)
    value = request(
        "agent.execute",
        {
            "agent": "codex",
            "prompt": "SIMULATION ONLY",
            "cwd": config.principals["local"].roots[0],
            "timeout": 10,
        },
    )
    async with bridge:
        bridge.prepare("local", value)
        async with asyncio.timeout(5):
            while bridge.store.get(value.task_id)["state"] != "running":
                await asyncio.sleep(0.02)
        await bridge.terminal.terminate("local", value.task_id)
        await bridge.tasks.wait("local", value.task_id)
        payload = bridge.completions.receive("local")["notices"][0]["payload"]
        assert payload["state"] == "unknown" and payload["execution_outcome_unknown"]
        assert payload["outcome"] == "cancelled"
        assert payload["process_id"] and payload["session_id"] == "SIMULATED-cancelled-session"
