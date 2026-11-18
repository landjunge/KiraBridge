"""Team turns on the loaded Codex root go through the app-server API, never a terminal."""

# ruff: noqa: F811
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_agents import fake_cli  # noqa: F401
from test_mcp import http_bridge  # noqa: F401
from test_team_coordinator_resume import connect
from test_team_dispatcher import configure_team

from kirabridge.bridge_core.config import NativeCodexBinding
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.platform_adapters import codex_host
from kirabridge.platform_adapters.codex_turn import NativeCodexTurns

ROOT = "01a1ebef-1b5b-7871-a0a1-fd5be34cac5c"
OTHER = "01a1daf2-f415-7d82-9d87-eca8fc8b5678"


def template(tmp_path):
    return NativeCodexBinding(
        thread_id=OTHER,
        session_id=OTHER,
        codex_home=str(tmp_path),
        host_executable=str(tmp_path / "codex"),
        source="vscode",
    )


class FakeApp:
    """Scripted app-server: one or more loaded threads, one idle/active root."""

    def __init__(self, cwd, *, threads=None, active=False, answer="ANSWER", finish=True):
        self.cwd, self.active, self.answer, self.finish = cwd, active, answer, finish
        self.threads = threads if threads is not None else [ROOT]
        self.sent, self.body, self.calls = [], None, []

    def thread(self, thread_id):
        return {
            "id": thread_id,
            "sessionId": thread_id,
            "source": "cli",
            "cwd": str(self.cwd),
            "parentThreadId": None,
            "attachedToThreadId": None,
            "canAcceptDirectInput": True,
            "status": {"type": "active" if self.active else "idle", "activeFlags": []},
        }

    def turn(self, status="completed"):
        items = [
            {"type": "userMessage", "content": [{"type": "text", "text": self.body}]},
            {"type": "agentMessage", "phase": "final_answer", "text": self.answer},
        ]
        return {"id": "turn-1", "status": status, "items": items}

    async def call(self, method, params):
        self.calls.append(method)
        if method == "thread/loaded/list":
            return {"data": self.threads}
        if method == "thread/read":
            return {"thread": self.thread(params["threadId"])}
        if method == "thread/turns/list":
            if self.body is None:
                rows = [{"id": "old", "status": "inProgress"}] if self.active else []
                return {"data": rows}
            return {"data": [self.turn("completed" if self.finish else "inProgress")]}
        if method in {"turn/start", "turn/steer"}:
            self.sent.append(method)
            self.body = params["input"][0]["text"]
            return {"turn": {"id": "turn-1"}} if method == "turn/start" else {"turnId": "old"}
        raise AssertionError(method)


@pytest.fixture
def app(tmp_path, monkeypatch):
    state = FakeApp(tmp_path)

    @asynccontextmanager
    async def connection(self, binding):
        yield state, "generation"

    monkeypatch.setattr(codex_host.CodexHost, "connection", connection)
    return state


async def noop(evidence):
    return None


async def execute(app, tmp_path, timeout=5):
    return await NativeCodexTurns().execute(
        template(tmp_path),
        str(tmp_path),
        "11111111-1111-4111-8111-111111111111",
        "BODY",
        timeout,
        noop,
    )


async def test_the_one_loaded_root_in_the_cwd_gets_the_turn_and_its_exact_answer_returns(
    app, tmp_path
):
    result = await execute(app, tmp_path)
    assert result["final_message"] == "ANSWER" and result["thread_id"] == ROOT
    assert app.sent == ["turn/start"] and result["terminal_input_attempted"] is False


async def test_no_pin_needed_a_restarted_codex_is_found_by_cwd(app, tmp_path):
    app.threads = ["01a1ffff-0000-7000-8000-000000000001"]  # a different thread than any config
    assert (await execute(app, tmp_path))["thread_id"] == app.threads[0]


@pytest.mark.parametrize("threads", [[], [ROOT, OTHER]])
async def test_zero_or_two_candidates_never_receive_input(app, tmp_path, threads):
    app.threads = threads
    with pytest.raises(BridgeError) as error:
        await execute(app, tmp_path)
    assert error.value.code == "native_codex_root_not_unique" and app.sent == []


async def test_other_cwd_is_not_a_candidate(app, tmp_path):
    app.cwd = tmp_path / "elsewhere"
    with pytest.raises(BridgeError):
        await execute(app, tmp_path)
    assert app.sent == []


async def test_relative_thread_cwd_is_never_chosen(app, tmp_path):
    app.cwd = Path(".")
    with pytest.raises(BridgeError) as error:
        await NativeCodexTurns().execute(
            template(tmp_path),
            str(Path.cwd()),
            "11111111-1111-4111-8111-111111111111",
            "BODY",
            5,
            noop,
        )
    assert error.value.code == "native_codex_root_not_unique" and app.sent == []


async def test_final_answer_before_the_user_message_is_not_verified(app, tmp_path):
    original = app.turn

    def reversed_items(status="completed"):
        row = original(status)
        row["items"] = [row["items"][1], row["items"][0]]
        return row

    app.turn = reversed_items
    with pytest.raises(UncertainExecution) as error:
        await execute(app, tmp_path)
    assert error.value.code == "native_codex_turn_unverified" and app.sent == ["turn/start"]
    app.turn = original
    assert (await execute(app, tmp_path))["final_message"] == "ANSWER"


async def test_a_running_turn_is_never_steered(app, tmp_path):
    app.active = True
    with pytest.raises(BridgeError) as error:
        await execute(app, tmp_path)
    assert error.value.code == "native_codex_target_not_ready" and app.sent == []


async def test_unfinished_turn_is_unknown_and_never_resent(app, tmp_path):
    app.finish = False
    with pytest.raises(UncertainExecution) as error:
        await execute(app, tmp_path, timeout=0.01)
    assert error.value.code == "native_codex_reply_unknown" and app.sent == ["turn/start"]


async def test_answer_without_our_exact_user_message_is_not_verified(app, tmp_path):
    original = app.turn

    def foreign(status="completed"):
        row = original(status)
        row["items"][0]["content"][0]["text"] = "someone else's input"
        return row

    app.turn = foreign
    with pytest.raises(UncertainExecution) as error:
        await execute(app, tmp_path)
    assert error.value.code == "native_codex_turn_unverified"


async def test_team_chain_runs_on_the_native_root_without_any_terminal(
    http_bridge, config, tmp_path, monkeypatch
):
    bridge, endpoint = http_bridge
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    config.team.workers["codex"].execution_scope = "existing_native_codex_root"
    config.visible_handoffs.native_codex = template(tmp_path)
    state = FakeApp(root, answer=json.dumps({"kirabridge_team": "1", "result": "NATIVE_DONE"}))

    @asynccontextmanager
    async def connection(self, binding):
        yield state, "generation"

    monkeypatch.setattr(codex_host.CodexHost, "connection", connection)
    await bridge.team_dispatcher.start()
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        await clients.call(
            "local",
            "team_work_create",
            {
                "request": {
                    "team_id": "e2e",
                    "assignee": "codex",
                    "title": "Native",
                    "body": "Do it.",
                    "idempotency_key": "native-order",
                }
            },
        )
        async with asyncio.timeout(20):
            while True:
                listed = (
                    await clients.call(
                        "local", "team_work_list", {"team_id": "e2e", "after": 0, "limit": 5}
                    )
                ).structuredContent["work"]
                if listed and listed[0]["state"] in {"completed", "failed", "unknown"}:
                    break
                await asyncio.sleep(0.05)
    assert listed[0]["state"] == "completed", listed[0]
    assert listed[0]["result"] == "NATIVE_DONE"
    assert state.sent == ["turn/start"] and "KiraBridge team turn" in state.body
    assert not (Path(root) / "team-codex-invocations").exists()  # no CLI/terminal ran
