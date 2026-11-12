import base64
import json

import httpx
import pytest

from kirabridge.agent_manager.opencode_http import OpenCodeHTTPAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution


def user(ident="user_0", text="Answer without tools"):
    return {
        "info": {"id": ident, "sessionID": "ses_test", "role": "user", "time": {"created": 0}},
        "parts": [{"type": "text", "text": text}],
    }


def assistant(text="Harmless answer", *, completed=True, finish="stop", error=None):
    info = {
        "id": "msg_1",
        "sessionID": "ses_test",
        "role": "assistant",
        "time": {"created": 1, **({"completed": 2} if completed else {})},
        "parentID": "user_0",
        "modelID": "deepseek-flash",
        "providerID": "deepseek",
        "mode": "build",
        "agent": "build",
        "path": {"cwd": "/work", "root": "/work"},
        "cost": 0.01,
        "tokens": {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}},
    }
    if finish is not None:
        info["finish"] = finish
    if error is not None:
        info["error"] = error
    return {"info": info, "parts": [{"type": "text", "text": text}]}


class Server:
    def __init__(self, statuses=("busy", "idle"), message=None):
        self.requests = []
        self.statuses = list(statuses)
        self.user = user()
        self.message = message or assistant()
        # Idle baseline: the pre-prompt message list starts at a stable id.
        self.message["info"]["id"] = "msg_0"
        self.message["info"]["parentID"] = "user_0"
        self._turns = 0

    def handler(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_test"})
        if path == "/session/ses_test" and request.method == "GET":
            return httpx.Response(200, json={"id": "ses_test"})
        if path.endswith("/prompt_async"):
            # A new turn admits the client-assigned messageID as the user prompt
            # and appends a new assistant message whose parent is exactly it.
            self._turns += 1
            body = json.loads(request.content) if request.content else {}
            message_id = body.get("messageID", f"user_{self._turns}")
            self.user["info"]["id"] = message_id
            self.message["info"]["id"] = f"msg_{self._turns}"
            self.message["info"]["parentID"] = message_id
            return httpx.Response(204)
        if path == "/session/status":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            body = {"type": status}
            if status == "retry":
                body.update(attempt=1, message="provider retry", next=1)
            return httpx.Response(200, json={"ses_test": body})
        if path.endswith("/message"):
            return httpx.Response(200, json=[self.user, self.message])
        return httpx.Response(404)

    def body(self, method, suffix):
        for request in self.requests:
            if request.method == method and request.url.path.endswith(suffix):
                return json.loads(request.content)
        raise AssertionError(f"no {method} {suffix}")


def config(**overrides):
    values = {
        "kind": "opencode_http",
        "model": "deepseek/deepseek-flash",
        "server_url": "http://127.0.0.1:58836",
        "server_username_env": "KC_TEST_USER",
        "server_password_env": "KC_TEST_PASS",
    }
    values.update(overrides)
    return AgentConfig(**values)


async def execute(
    tmp_path, server, *, agent_config=None, local_tools=False, timeout=3.0, resume_session=None
):
    running, progress = [], []

    async def on_running(value):
        running.append(value)

    async def on_progress(value):
        progress.append(value)

    adapter = OpenCodeHTTPAdapter(transport=httpx.MockTransport(server.handler), poll_interval=0.01)
    result = await adapter.execute(
        {"id": "task-1", "principal": "owner"},
        AgentInput(
            agent="opencode_http",
            prompt="Answer without tools",
            cwd=str(tmp_path),
            timeout=timeout,
            local_tools=local_tools,
        ),
        agent_config or config(),
        [str(tmp_path)],
        on_running,
        on_progress,
        resume_session=resume_session,
    )
    return result, running, progress


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("KC_TEST_USER", "bridge-user")
    monkeypatch.setenv("KC_TEST_PASS", "bridge-pass")


async def test_task_handoff_binds_one_session_and_reports_live_status(tmp_path):
    server = Server()
    result, running, progress = await execute(tmp_path, server)

    assert result["success"] and result["text"] == "Harmless answer"
    assert result["evidence"]["adapter"] == "opencode_http"
    assert result["evidence"]["session_id"] == "ses_test"
    assert result["evidence"]["status_events"] == ["busy", "idle"]
    assert result["evidence"]["finish_reason"] == "stop"
    assert not result["project_completion_verified"]
    assert running == [
        {"agent": "opencode_http", "session_id": "ses_test", "event": "session_busy"}
    ]
    events = [item["event"] for item in progress]
    assert events[:4] == ["session_created", "prompt_admitted", "session_status", "session_status"]

    session_body = server.body("POST", "/session")
    assert session_body["title"] == "KiraBridge task-1"
    assert session_body["model"] == {"providerID": "deepseek", "id": "deepseek-flash"}
    assert session_body["metadata"] == {"kirabridge_task_id": "task-1"}
    assert session_body["permission"] == [{"permission": "*", "pattern": "*", "action": "deny"}]
    prompt_body = server.body("POST", "/prompt_async")
    assert prompt_body["model"] == {"providerID": "deepseek", "modelID": "deepseek-flash"}
    assert prompt_body["parts"] == [{"type": "text", "text": "Answer without tools"}]

    expected = base64.b64encode(b"bridge-user:bridge-pass").decode()
    assert server.requests[0].headers["authorization"] == "Basic " + expected


async def test_full_access_imposes_an_explicit_allow_rule(tmp_path):
    server = Server()
    result, _, _ = await execute(
        tmp_path,
        server,
        agent_config=config(allow_local_tools=True, bridge_tools=True),
        local_tools=True,
    )
    assert result["success"] and result["evidence"]["local_tools_enabled"]
    assert server.body("POST", "/session")["permission"] == [
        {"permission": "*", "pattern": "*", "action": "allow"}
    ]


async def test_missing_credentials_fail_without_exposing_values(tmp_path, monkeypatch):
    monkeypatch.delenv("KC_TEST_PASS")
    with pytest.raises(BridgeError) as caught:
        await execute(tmp_path, Server())
    assert caught.value.code == "agent_config"
    assert "bridge-pass" not in str(caught.value)


async def test_rejected_credentials_are_reported_as_authentication(tmp_path):
    def handler(request):
        return httpx.Response(401)

    adapter = OpenCodeHTTPAdapter(transport=httpx.MockTransport(handler), poll_interval=0.01)
    with pytest.raises(BridgeError) as caught:
        await adapter.execute(
            {"id": "task-1", "principal": "owner"},
            AgentInput(agent="opencode_http", prompt="hello", cwd=str(tmp_path), timeout=3),
            config(),
            [str(tmp_path)],
            record,
            record,
        )
    assert caught.value.code == "agent_auth"


async def test_provider_error_is_failed_without_retaining_the_message(tmp_path):
    message = assistant(
        text="", error={"name": "APIError", "data": {"message": "secret-provider-response"}}
    )
    result, running, _ = await execute(tmp_path, Server(message=message))
    assert not result["success"] and result["evidence"]["turn_failed"]
    assert result["evidence"]["provider_error"]["category"] == "provider"
    assert "secret-provider-response" not in json.dumps([result, running])


@pytest.mark.parametrize("reason", ["length", "content-filter", "tool-calls", "error"])
async def test_explicit_non_success_finish_is_failed(tmp_path, reason):
    result, _, _ = await execute(tmp_path, Server(message=assistant(finish=reason)))
    assert not result["success"] and result["evidence"]["turn_failed"]


async def test_missing_completion_evidence_is_unknown(tmp_path):
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, Server(message=assistant(completed=False)))
    assert caught.value.code == "agent_unconfirmed"


async def test_timeout_while_busy_is_unknown(tmp_path):
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, Server(statuses=("busy",)), timeout=0.05)
    assert caught.value.code == "agent_timeout"


async def test_cwd_outside_allowed_roots_is_denied_before_any_request(tmp_path):
    server = Server()
    adapter = OpenCodeHTTPAdapter(transport=httpx.MockTransport(server.handler))
    with pytest.raises(BridgeError) as caught:
        await adapter.execute(
            {"id": "task-1", "principal": "owner"},
            AgentInput(agent="opencode_http", prompt="hello", cwd="/etc", timeout=3),
            config(),
            [str(tmp_path)],
            record,
            record,
        )
    assert caught.value.code == "path_denied"
    assert server.requests == []


async def record(value):
    pass


def test_agent_manager_registers_the_http_adapter():
    from kirabridge.agent_manager import AgentManager
    from kirabridge.bridge_core.config import Config
    from kirabridge.terminal_manager import TerminalManager

    manager = AgentManager(Config(), TerminalManager())
    assert isinstance(manager.adapters["opencode_http"], OpenCodeHTTPAdapter)


def test_only_a_credential_free_loopback_server_url_is_accepted():
    for url in ("http://example.com:58836", "http://user:pass@127.0.0.1:58836", "file:///tmp/x"):
        with pytest.raises(ValueError):
            config(server_url=url)


def test_server_fields_are_rejected_for_other_kinds():
    with pytest.raises(ValueError):
        AgentConfig(kind="opencode", model="opencode/test", server_url="http://127.0.0.1:1")


async def test_resume_reuses_the_exact_server_session_without_creating_another(tmp_path):
    server = Server()
    result, _, progress = await execute(tmp_path, server, resume_session="ses_test")
    assert result["success"] and result["text"] == "Harmless answer"
    assert result["evidence"]["session_id"] == "ses_test"
    assert result["evidence"]["session_resumed"] is True
    assert not [r for r in server.requests if r.method == "POST" and r.url.path == "/session"]
    assert [r for r in server.requests if r.method == "GET" and r.url.path == "/session/ses_test"]
    assert server.body("POST", "/prompt_async")["parts"] == [
        {"type": "text", "text": "Answer without tools"}
    ]
    assert progress[0] == {
        "agent": "opencode_http",
        "session_id": "ses_test",
        "event": "session_resumed",
    }


async def test_unknown_resumed_session_is_not_recreated(tmp_path):
    server = Server()
    server.handler_original = server.handler

    def missing(request):
        if request.url.path == "/session/ses_missing":
            return httpx.Response(404)
        return server.handler_original(request)

    server.handler = missing

    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, resume_session="ses_missing")
    assert caught.value.code == "session_unknown"
    assert not [r for r in server.requests if r.method == "POST" and r.url.path == "/session"]


async def test_idle_baseline_message_is_not_reused_as_a_new_turn(tmp_path):
    server = Server()
    original = server.handler

    def stale(request):
        if request.url.path.endswith("/prompt_async"):
            # A resumed idle session that produces no new assistant message.
            return httpx.Response(204)
        return original(request)

    server.handler = stale
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, resume_session="ses_test")
    assert caught.value.code == "agent_unconfirmed"


async def test_foreign_session_response_is_not_accepted(tmp_path):
    server = Server()
    server.message["info"]["sessionID"] = "ses_foreign"
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server)
    assert caught.value.code == "agent_unconfirmed"


async def test_foreign_parent_response_is_not_accepted(tmp_path):
    server = Server()
    original = server.handler

    def foreign_parent(request):
        if request.url.path.endswith("/prompt_async"):
            server._turns += 1
            body = json.loads(request.content) if request.content else {}
            server.user["info"]["id"] = body.get("messageID", "user_1")  # our prompt admitted
            server.message["info"]["id"] = f"msg_{server._turns}"  # new assistant
            # The assistant replies to a foreign prompt, not the messageID we sent.
            server.message["info"]["parentID"] = "user_foreign"
            return httpx.Response(204)
        return original(request)

    server.handler = foreign_parent
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server)
    assert caught.value.code == "agent_unconfirmed"


async def test_foreign_prompt_and_answer_are_not_accepted(tmp_path):
    server = Server()
    original = server.handler

    def foreign_turn(request):
        if request.url.path.endswith("/prompt_async"):
            server._turns += 1
            # A foreign client also admits a prompt whose user+assistant pair is
            # self-consistent, but its parent is not our assigned messageID.
            server.user["info"]["id"] = "user_foreign"
            server.message["info"]["id"] = f"msg_{server._turns}"
            server.message["info"]["parentID"] = "user_foreign"
            return httpx.Response(204)
        return original(request)

    server.handler = foreign_turn
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server)
    assert caught.value.code == "agent_unconfirmed"


async def test_resume_from_initial_idle_still_detects_the_new_turn(tmp_path):
    server = Server(statuses=("idle",))
    result, _, _ = await execute(tmp_path, server, resume_session="ses_test")
    assert result["success"] and result["text"] == "Harmless answer"
    assert result["evidence"]["session_resumed"] is True
