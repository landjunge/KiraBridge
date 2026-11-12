"""Fake V2 OpenCode server fixtures exercising the /api adapter and correlation."""

import json

import httpx
import pytest

from kirabridge.agent_manager.opencode_http_v2 import OpenCodeHTTPV2Adapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution


def user_msg(ident, text, created=1):
    return {"id": ident, "time": {"created": created}, "text": text, "type": "user"}


def assistant_msg(ident, text, *, completed=2, finish="stop", created=2, model=None, agent="build"):
    return {
        "id": ident,
        "time": {"created": created, "completed": completed},
        "type": "assistant",
        "agent": agent,
        "model": model or {"id": "deepseek-flash", "providerID": "deepseek"},
        "content": [{"type": "text", "text": text}],
        "finish": finish,
    }


def idle_msg(ident, outcome="succeeded", created=3):
    return {"id": ident, "time": {"created": created}, "type": "idle", "outcome": outcome}


class Server:
    """Stateful fake V2 /api server; the prompt appends the projected turn."""

    def __init__(
        self,
        *,
        location=None,
        reply_text="Harmless answer",
        finish="stop",
        idle_outcome="succeeded",
        foreign=False,
        never_complete=False,
        multi_step=False,
        tool_calls_only=False,
        changed_id=False,
        cursor_never_ends=False,
        page_size=None,
        model=None,
    ):
        self.requests = []
        self.location = location
        self.reply_text = reply_text
        self.finish = finish
        self.idle_outcome = idle_outcome
        self.foreign = foreign
        self.never_complete = never_complete
        self.multi_step = multi_step
        self.tool_calls_only = tool_calls_only
        self.changed_id = changed_id
        self.cursor_never_ends = cursor_never_ends
        self.page_size = page_size
        self.model = model
        self.messages = []
        self.session_id = "ses_test"
        self._pages_served = 0

    def _info(self, body):
        location = body.get("location", {}).get("directory", self.location)
        return {
            "id": self.session_id,
            "projectID": "prj_x",
            "cost": {},
            "tokens": {},
            "time": {"created": 1, "updated": 1},
            "location": {"directory": location},
            "title": body.get("title", "session"),
            "model": body.get("model", {"id": "deepseek-flash", "providerID": "deepseek"}),
        }

    def handler(self, request):
        self.requests.append(request)
        path = request.url.path
        method = request.method
        if method == "POST" and path == "/api/session":
            body = json.loads(request.content) if request.content else {}
            self.session_id = body.get("id", "ses_test")
            if self.changed_id:
                self.session_id = "ses_other"
            return httpx.Response(200, json={"data": self._info(body)})
        if method == "GET" and path == f"/api/session/{self.session_id}":
            return httpx.Response(
                200, json={"data": self._info({"location": {"directory": self.location}})}
            )
        if method == "POST" and path == f"/api/session/{self.session_id}/prompt":
            body = json.loads(request.content) if request.content else {}
            mid = body.get("id", "msg_x")
            self.messages.append(user_msg(mid, body.get("text", "")))
            if self.foreign:
                self.messages.append(user_msg("msg_foreign", "foreign prompt", created=2))
                self.messages.append(assistant_msg("msg_foreign_a", "foreign answer", created=3))
            elif self.multi_step:
                self.messages.append(
                    assistant_msg("msg_step", "tool step", created=2, finish="tool-calls")
                )
                self.messages.append(assistant_msg("msg_final", self.reply_text, created=3))
                self.messages.append(idle_msg("msg_idle", self.idle_outcome, created=4))
            elif self.tool_calls_only:
                self.messages.append(
                    assistant_msg(
                        "msg_tool",
                        "tool step",
                        created=2,
                        completed=2,
                        finish="tool-calls",
                    )
                )
            elif self.never_complete:
                self.messages.append(
                    assistant_msg(
                        "msg_assistant",
                        self.reply_text,
                        completed=None,
                        finish=None,
                        model=self.model,
                    )
                )
            else:
                self.messages.append(
                    assistant_msg(
                        "msg_assistant", self.reply_text, finish=self.finish, model=self.model
                    )
                )
                self.messages.append(idle_msg("msg_idle", self.idle_outcome))
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": mid,
                        "sessionID": self.session_id,
                        "time": {"created": 1},
                        "type": "user",
                        "payload": {"text": body.get("text", "")},
                        "delivery": {},
                    }
                },
            )
        if method == "GET" and path == f"/api/session/{self.session_id}/message":
            order = request.url.params.get("order", "asc")
            ordered = list(reversed(self.messages)) if order == "desc" else list(self.messages)
            if self.cursor_never_ends:
                return httpx.Response(
                    200, json={"data": [], "cursor": {"next": "page-2", "previous": None}}
                )
            if self.page_size:
                start = self._pages_served * self.page_size
                data = ordered[start : start + self.page_size]
                has_more = start + self.page_size < len(ordered)
                self._pages_served += 1
                cursor = {"next": "page-2" if has_more else None, "previous": None}
            else:
                data = ordered
                cursor = {"next": None, "previous": None}
            return httpx.Response(200, json={"data": data, "cursor": cursor})
        return httpx.Response(404)


def config(**overrides):
    values = {
        "kind": "opencode_http_v2",
        "model": "deepseek/deepseek-flash",
        "server_url": "http://127.0.0.1:58836",
        "server_username_env": "KC_TEST_USER",
        "server_password_env": "KC_TEST_PASS",
    }
    values.update(overrides)
    return AgentConfig(**values)


async def execute(tmp_path, server, *, resume_session=None, timeout=3.0):
    running, progress = [], []

    async def on_running(value):
        running.append(value)

    async def on_progress(value):
        progress.append(value)

    adapter = OpenCodeHTTPV2Adapter(
        transport=httpx.MockTransport(server.handler), poll_interval=0.01
    )
    result = await adapter.execute(
        {"id": "task-1", "principal": "owner"},
        AgentInput(
            agent="opencode_http_v2",
            prompt="Answer without tools",
            cwd=str(tmp_path),
            timeout=timeout,
        ),
        config(),
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


async def test_create_prompt_and_correlate_reply(tmp_path):
    server = Server(location=str(tmp_path))
    result, running, _ = await execute(tmp_path, server)
    assert result["success"] and result["text"] == "Harmless answer"
    assert result["evidence"]["adapter"] == "opencode_http_v2"
    assert result["evidence"]["session_id"].startswith("ses_")
    assert result["evidence"]["session_id"] == server.session_id
    assert result["evidence"]["finish_reason"] == "stop"
    assert result["evidence"]["observed_model"] == {
        "id": "deepseek-flash",
        "providerID": "deepseek",
    }
    assert not result["project_completion_verified"]
    assert [r.url.path for r in server.requests if r.method == "POST"] == [
        "/api/session",
        f"/api/session/{server.session_id}/prompt",
    ]
    assert running == [
        {"agent": "opencode_http_v2", "session_id": server.session_id, "event": "session_busy"}
    ]


async def test_only_the_v2_api_surface_is_used(tmp_path):
    server = Server(location=str(tmp_path))
    await execute(tmp_path, server)
    paths = {r.url.path for r in server.requests}
    assert all(p.startswith("/api/") for p in paths)
    assert not any(p.startswith("/session/") for p in paths)


async def test_resume_verifies_session_and_location(tmp_path):
    server = Server(location=str(tmp_path))
    result, _, _ = await execute(tmp_path, server, resume_session="ses_test")
    assert result["success"] and result["evidence"]["session_resumed"] is True
    assert not [r for r in server.requests if r.method == "POST" and r.url.path == "/api/session"]


async def test_resume_rejects_a_changed_location(tmp_path):
    server = Server(location="/elsewhere")
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, resume_session="ses_test")
    assert caught.value.code == "session_unknown"


async def test_resume_requires_a_v2_session_id(tmp_path):
    server = Server(location=str(tmp_path))
    with pytest.raises(BridgeError) as caught:
        await execute(tmp_path, server, resume_session="legacy-session")
    assert caught.value.code == "agent_identity"


async def test_foreign_input_interleaved_is_unknown(tmp_path):
    server = Server(location=str(tmp_path), foreign=True)
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server)
    assert caught.value.code == "agent_unconfirmed"


async def test_uncompleted_assistant_times_out(tmp_path):
    server = Server(location=str(tmp_path), never_complete=True)
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, timeout=0.2)
    assert caught.value.code == "agent_timeout"


async def test_paging_follows_cursor(tmp_path):
    server = Server(location=str(tmp_path), page_size=1)
    result, _, _ = await execute(tmp_path, server)
    assert result["success"] and result["text"] == "Harmless answer"


async def test_explicit_non_success_finish_is_failed(tmp_path):
    server = Server(location=str(tmp_path), finish="length")
    result, _, _ = await execute(tmp_path, server)
    assert not result["success"] and result["evidence"]["turn_failed"]


async def test_failed_finish_reports_a_safe_category(tmp_path):
    server = Server(location=str(tmp_path), finish="content-filter")
    result, _, _ = await execute(tmp_path, server)
    assert not result["success"]
    assert result["evidence"]["provider_error"]["category"] == "content_filter"


async def test_multi_part_turn_returns_the_final_assistant(tmp_path):
    server = Server(location=str(tmp_path), multi_step=True, reply_text="final answer")
    result, _, _ = await execute(tmp_path, server)
    assert result["success"] and result["text"] == "final answer"
    assert result["evidence"]["message_id"] == "msg_final"


async def test_tool_calls_only_is_not_promoted_to_success(tmp_path):
    server = Server(location=str(tmp_path), tool_calls_only=True)
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, timeout=0.2)
    assert caught.value.code == "agent_timeout"


async def test_create_rejects_a_changed_session_id(tmp_path):
    server = Server(location=str(tmp_path), changed_id=True)
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server)
    assert caught.value.code == "agent_identity"


async def test_paging_window_is_fail_closed(tmp_path):
    server = Server(location=str(tmp_path), cursor_never_ends=True)
    with pytest.raises(UncertainExecution) as caught:
        await execute(tmp_path, server, timeout=0.2)
    assert caught.value.code == "agent_unconfirmed"


async def test_observed_model_is_reported_separately_from_requested(tmp_path):
    server = Server(
        location=str(tmp_path),
        model={"id": "other-model", "providerID": "other-provider"},
    )
    result, _, _ = await execute(tmp_path, server)
    assert result["evidence"]["model"] == "deepseek/deepseek-flash"
    assert result["evidence"]["observed_model"] == {
        "id": "other-model",
        "providerID": "other-provider",
    }


async def test_cwd_outside_roots_is_denied(tmp_path):
    adapter = OpenCodeHTTPV2Adapter(
        transport=httpx.MockTransport(Server().handler), poll_interval=0.01
    )
    with pytest.raises(BridgeError) as caught:
        await adapter.execute(
            {"id": "task-1", "principal": "owner"},
            AgentInput(agent="opencode_http_v2", prompt="hello", cwd="/etc", timeout=1),
            config(),
            [str(tmp_path)],
            record,
            record,
        )
    assert caught.value.code == "path_denied"


async def record(value):
    pass
