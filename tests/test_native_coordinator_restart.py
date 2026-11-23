"""Persistent Bridge state and an isolated Codex protocol peer across restart."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn
from test_native_codex_turn import OTHER, ROOT, configure_team, template

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, ReceiverConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.platform_adapters.codex_host import CodexHost


class PersistedCodex:
    def __init__(self, root, history, *, loaded, generation):
        self.root = root
        self.history = history
        self.loaded = set(loaded)
        self.generation = generation
        self.calls = []
        self.inputs = []
        self.scrollback = []

    def turns(self):
        return json.loads(self.history.read_text()) if self.history.exists() else []

    def thread(self, identifier):
        loaded = identifier in self.loaded
        return {
            "id": identifier,
            "sessionId": identifier,
            "source": "cli",
            "cwd": self.root,
            "parentThreadId": None,
            "attachedToThreadId": None,
            "ephemeral": False,
            "canAcceptDirectInput": True if loaded else None,
            "status": {"type": "idle" if loaded else "notLoaded"},
        }

    async def call(self, method, params):
        self.calls.append((method, params))
        identifier = params["threadId"]
        assert identifier in {ROOT, OTHER}
        if method == "thread/read":
            return {"thread": self.thread(identifier)}
        assert identifier == ROOT, "the same-cwd decoy must receive no mutation"
        if method == "thread/resume":
            assert identifier not in self.loaded and params["excludeTurns"] is True
            self.loaded.add(identifier)
            return {"thread": self.thread(identifier)}
        assert self.loaded == {ROOT, OTHER}
        past = self.turns()
        if method == "thread/turns/list":
            return {"data": list(reversed(past[-params["limit"] :]))}
        assert method == "turn/start" and "expectedTurnId" not in params
        body = params["input"][0]["text"]
        self.inputs.append((params["clientUserMessageId"], body))
        if body == "PING":
            answer = "PONG"
        elif body == "FAIL":
            answer = None
        else:
            stage = "DECISION_RECORDED" if not past else "FOLLOWUP_DELIVERED"
            answer = json.dumps({"kirabridge_team": "1", "result": stage, "actions": []})
        items = [{"type": "userMessage", "content": params["input"]}]
        if answer is not None:
            items.append({"type": "agentMessage", "phase": "final_answer", "text": answer})
        turn = {
            "id": f"turn-{len(past) + 1}",
            "status": "completed" if answer is not None else "failed",
            "items": items,
        }
        self.history.write_text(json.dumps([*past, turn]))
        self.scrollback.append(body)
        return {"turn": turn}


@asynccontextmanager
async def connected(config, host, monkeypatch):
    @asynccontextmanager
    async def connection(_self, binding):
        assert binding.thread_id == binding.session_id == ROOT
        yield host, host.generation

    monkeypatch.setattr(CodexHost, "connection", connection)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        port = listener.getsockname()[1]
        config.port = port
        bridge = Bridge(config)
        server = uvicorn.Server(uvicorn.Config(create_http_app(bridge), log_level="critical"))
        async with bridge:
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(8):
                    while not server.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.01)
                endpoint = f"http://127.0.0.1:{port}/mcp"
                async with MCPClientPool() as clients:
                    await clients.connect(Peer("local", url=endpoint, token="local-" + "x" * 40))
                    await clients.connect(
                        Peer("codex", url=endpoint, token="codex-team-test-" + "x" * 40)
                    )
                    yield clients
            finally:
                server.should_exit = True
                await asyncio.wait_for(serving, 8)


async def call(clients, who, tool, **params):
    result = await clients.call(who, tool, params)
    assert not result.isError, result.structuredContent
    content = result.structuredContent
    assert not content.get("error") or (tool == "message_send" and "id" in content), content
    return result.structuredContent


async def poll(operation, ready):
    async with asyncio.timeout(10):
        while True:
            result = await operation()
            if ready(result):
                return result
            await asyncio.sleep(0.03)


def team_order(assignee, title, key):
    return {
        "team_id": "e2e",
        "assignee": assignee,
        "title": title,
        "body": title,
        "idempotency_key": key,
    }


async def ping(clients, text, key):
    return await call(
        clients,
        "local",
        "message_send",
        message={
            "recipient": "codex",
            "kind": "question",
            "body": text,
            "conversation_id": key,
            "idempotency_key": key,
            "request_reply": True,
            "dispatch": True,
        },
    )


@pytest.mark.parametrize("initially_loaded", [{ROOT, OTHER}, {OTHER}])
async def test_team_and_both_routes_recover_exactly_after_restart(
    config, tmp_path, monkeypatch, initially_loaded
):
    root = configure_team(None, config, tmp_path, monkeypatch)
    config.team.workers["codex"].execution_scope = "existing_native_codex_root"
    config.team.coordinator_resume = True
    config.visible_handoffs.enabled = True
    config.visible_handoffs.native_codex = template(tmp_path).model_copy(
        update={"protocol_version": "0.171.0"}
    )
    config.messaging.receivers["codex"] = ReceiverConfig(cwd=root, timeout=3)
    for principal in ("local", "codex"):
        config.principals[principal].capabilities += [
            "message.send",
            "message.read",
            "session.inspect",
            "session.input",
        ]
    config.principals["local"].message_peers = ["codex"]
    config.principals["codex"].message_peers = ["local"]
    config.principals["local"].token_env = "RESTART_TEST_LOCAL"
    monkeypatch.setenv("RESTART_TEST_LOCAL", "local-" + "x" * 40)
    config_file = tmp_path / "config.json"
    config_file.write_text(config.model_dump_json())
    history = tmp_path / "codex-turns.json"
    first = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="before-restart")
    async with connected(config, first, monkeypatch) as clients:
        team = await call(
            clients,
            "local",
            "team_create",
            request={
                "team_id": "e2e",
                "name": "Persisted coordination",
                "coordinator": "codex",
                "members": {"local": "worker", "codex": "coordinator", "grok": "reviewer"},
                "idempotency_key": "persisted-team",
            },
        )
        assert team["coordinator"] == "codex"
        prior = await call(
            clients,
            "local",
            "team_work_create",
            request=team_order("codex", "Prior decision", "prior"),
        )
        await poll(
            lambda: call(clients, "local", "team_work_get", team_id="e2e", work_id=prior["id"]),
            lambda work: work["state"] == "completed",
        )
        order = await call(
            clients, "codex", "team_work_create", request=team_order("local", "Open order", "open")
        )
    historical = first.turns()[0]
    assert "Prior decision" in historical["items"][0]["content"][0]["text"]
    assert "DECISION_RECORDED" in historical["items"][-1]["text"]

    second = PersistedCodex(root, history, loaded=initially_loaded, generation="after-restart")
    restored = Config.model_validate_json(config_file.read_text())
    async with connected(restored, second, monkeypatch) as clients:
        team = await call(clients, "local", "team_get", team_id="e2e")
        assert team["coordinator"] == "codex" and team["revision"] == 1
        done = await call(clients, "local", "team_work_get", team_id="e2e", work_id=prior["id"])
        opened = await call(clients, "local", "team_work_get", team_id="e2e", work_id=order["id"])
        assert done["result"] == "DECISION_RECORDED"
        assert opened["state"] == "queued_manual" and opened["body"] == "Open order"
        sent = await ping(clients, "PING", "after-restart-ping")
        pong = await poll(
            lambda: call(clients, "local", "message_get", message_id=sent["id"]),
            lambda row: row["processing"]["state"] == "completed",
        )
        assert pong["processing"]["result"]["text"] == "PONG"
        assert pong["processing"]["result"]["message_id"] == sent["id"]
        assert pong["processing"]["evidence"]["host_generation"] == "after-restart"
        assert pong["acknowledged"] is None
        assert second.turns()[0] == historical

        failed = await ping(clients, "FAIL", "after-restart-failure")
        failure = await poll(
            lambda: call(clients, "local", "message_get", message_id=failed["id"]),
            lambda row: row["processing"]["state"] == "unknown",
        )
        assert failure["processing"]["error"] == "native_codex_turn_unverified"
        assert failure["processing"]["evidence"]["turn_id"]
        assert failure["processing"]["request_reply_satisfied"] is False
        second.scrollback.clear()
        assert not second.scrollback
        reread = await call(clients, "local", "message_get", message_id=sent["id"])
        assert reread["processing"]["result"]["text"] == "PONG"

        await call(
            clients,
            "local",
            "team_work_complete",
            request={
                "team_id": "e2e",
                "work_id": order["id"],
                "success": True,
                "result": "Open order finished",
                "idempotency_key": "worker-completed",
            },
        )
        work = await poll(
            lambda: call(clients, "local", "team_work_list", team_id="e2e", after=0, limit=20),
            lambda listing: (
                len(listing["work"]) == 3
                and all(row["state"] == "completed" for row in listing["work"])
            ),
        )
        followup = work["work"][-1]
        assert followup["assignee"] == followup["assigned_by"] == "codex"
        assert followup["result"] == "FOLLOWUP_DELIVERED"
        assert len(second.inputs) == 3
        assert order["id"] in second.inputs[-1][1] and "Open order finished" in second.inputs[-1][1]
        assert second.inputs[0] == (sent["id"], "PING")
        assert second.inputs[1] == (failed["id"], "FAIL")
        assert sum(method == "thread/resume" for method, _ in second.calls) == (
            ROOT not in initially_loaded
        )
        assert {params["threadId"] for _, params in second.calls} == {ROOT}

    third = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="lookup-restart")
    async with connected(
        Config.model_validate_json(config_file.read_text()), third, monkeypatch
    ) as clients:
        persisted = await call(clients, "local", "message_get", message_id=sent["id"])
        assert persisted["processing"]["result"]["text"] == "PONG"
        persisted_failure = await call(clients, "local", "message_get", message_id=failed["id"])
        assert persisted_failure["processing"]["error"] == "native_codex_turn_unverified"
        repeated = await ping(clients, "PING", "after-restart-ping")
        assert repeated["id"] == sent["id"]
        listing = await call(clients, "local", "team_work_list", team_id="e2e", after=0, limit=20)
        assert [row["id"] for row in listing["work"]] == [prior["id"], order["id"], followup["id"]]
        assert third.calls == third.inputs == []
