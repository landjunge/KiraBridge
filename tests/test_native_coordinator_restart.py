"""Persistent Bridge state and an isolated Codex protocol peer across restart."""

import asyncio
import json
import socket
import time
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn
from test_native_codex_turn import OTHER, ROOT, configure_team, template

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, ReceiverConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.platform_adapters.codex_host import CodexHost
from kirabridge.team_manager.models import TeamCreate, TeamWorkComplete, TeamWorkCreate


class PersistedCodex:
    def __init__(self, root, history, *, loaded, generation):
        self.root = root
        self.history = history
        self.loaded = set(loaded)
        self.generation = generation
        self.active = False
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
            "status": {
                "type": ("active" if self.active else "idle") if loaded else "notLoaded",
                "activeFlags": [],
            },
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
        past = self.turns()
        if method == "thread/turns/list":
            if self.active:
                past.append({"id": "active-user-turn", "status": "inProgress", "items": []})
            return {"data": list(reversed(past[-params["limit"] :]))}
        assert self.loaded == {ROOT, OTHER}
        assert not self.active, "the active user turn must receive no input"
        assert method == "turn/start" and "expectedTurnId" not in params
        body = params["input"][0]["text"]
        self.inputs.append((params["clientUserMessageId"], body))
        core = body.rsplit("]\n\n", 1)[-1]  # direct coordinator messages carry the role prefix
        if core in {"PING", "PING-BEFORE-RESTART"}:
            answer = "PONG"
        elif core == "FAIL":
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
                    yield clients, bridge
            finally:
                server.should_exit = True
                await asyncio.wait_for(serving, 8)


async def call(clients, who, tool, **params):
    result = await clients.call(who, tool, params)
    assert not result.isError, result.structuredContent
    content = result.structuredContent
    assert not content.get("error") or (
        tool in {"message_send", "team_work_get"} and "id" in content
    ), content
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


@pytest.fixture
def followup_setup(config, tmp_path, monkeypatch):
    root = configure_team(None, config, tmp_path, monkeypatch)
    config.team.workers["codex"].execution_scope = "existing_native_codex_root"
    config.team.coordinator_resume = True
    config.team.concurrency = 1
    config.visible_handoffs.native_codex = template(tmp_path)
    config.principals["local"].token_env = "RESTART_TEST_LOCAL"
    monkeypatch.setenv("RESTART_TEST_LOCAL", "local-" + "x" * 40)
    return config, root, tmp_path / "codex-turns.json"


def create_followup_team(bridge):
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="e2e",
            name="Follow-ups",
            coordinator="codex",
            members={"local": "worker", "codex": "coordinator", "grok": "worker"},
            idempotency_key="followup-team",
        ),
    )


def enqueue_followup(bridge, *, key):
    teams = bridge.teams
    original = teams.delegate("codex", TeamWorkCreate(**team_order("local", "Original order", key)))
    teams.work_complete(
        "local",
        TeamWorkComplete(
            team_id="e2e",
            work_id=original["id"],
            success=True,
            result="Completed delegated work",
            idempotency_key="completed-" + key,
        ),
    )
    assert teams.resume_coordinators() == 1
    return dict(
        bridge.store.db.execute(
            "SELECT * FROM team_coordinator_resumes WHERE work_id=?", (original["id"],)
        ).fetchone()
    )


async def followup_work(clients, work_id, state):
    return await poll(
        lambda: call(clients, "local", "team_work_get", team_id="e2e", work_id=work_id),
        lambda work: work["state"] == state,
    )


async def test_busy_followup_survives_restart_and_submits_same_work_once(
    followup_setup, monkeypatch
):
    config, root, history = followup_setup
    first = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="busy-before-restart")
    first.active = True
    async with connected(config, first, monkeypatch) as (clients, bridge):
        create_followup_team(bridge)
        link = enqueue_followup(bridge, key="resume-busy")
        identifier = link["resume_work_id"]
        await poll(lambda: asyncio.sleep(0, result=first.calls), bool)
        pending = await followup_work(clients, identifier, "queued")
        assert pending["core_task_id"] is None and identifier in bridge.team_dispatcher._defer
        assert [method for method, _ in first.calls] == ["thread/read"]
        assert not first.inputs

    second = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="busy-after-restart")
    second.active = True
    async with connected(config, second, monkeypatch) as (clients, bridge):
        await poll(lambda: asyncio.sleep(0, result=second.calls), bool)
        restored = await followup_work(clients, identifier, "queued")
        assert restored["created"] == pending["created"] and restored["core_task_id"] is None
        assert (
            dict(bridge.store.db.execute("SELECT * FROM team_coordinator_resumes").fetchone())
            == link
        )
        notice = bridge.store.db.execute(
            "SELECT receipt,acknowledged FROM completion_notices WHERE id=?", (link["notice_id"],)
        ).fetchone()
        assert notice["receipt"] == "resume-" + identifier and notice["acknowledged"] is not None
        assert not second.inputs
        second.active = False
        done = await followup_work(clients, identifier, "completed")
        core_id = "team-" + identifier
        assert done["id"] == identifier and done["core_task_id"] == core_id
        expected_input = str(uuid.uuid5(uuid.NAMESPACE_URL, "kirabridge-native-" + core_id))
        assert [message_id for message_id, _ in second.inputs] == [expected_input]
        assert link["work_id"] in second.inputs[0][1]
        core = bridge.store.get(core_id)
        assert core["state"] == "completed" and core["attempt"] == 1 and core["receipt"]

    third = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="after-completion")
    async with connected(config, third, monkeypatch) as (clients, bridge):
        await followup_work(clients, identifier, "completed")
        assert (
            bridge.store.db.execute("SELECT count(*) FROM team_coordinator_resumes").fetchone()[0]
            == 1
        )
        assert not third.inputs


@pytest.mark.parametrize("failure", ["wrong-session", "reoccupied"])
async def test_unverified_or_reoccupied_followup_is_never_replayed(
    followup_setup, monkeypatch, failure
):
    config, root, history = followup_setup
    host = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation=failure)
    original_thread = host.thread

    def thread(identifier):
        if failure == "reoccupied":
            host.active = len(host.calls) > 1
        else:
            host.active = True
        result = original_thread(identifier)
        if failure == "wrong-session":
            result["sessionId"] = OTHER
        return result

    host.thread = thread
    async with connected(config, host, monkeypatch) as (clients, bridge):
        create_followup_team(bridge)
        link = enqueue_followup(bridge, key=failure)
        identifier = link["resume_work_id"]
        original = await followup_work(clients, identifier, "unknown")
        expected_error = (
            "native_codex_binding_changed"
            if failure == "wrong-session"
            else "native_codex_target_not_ready"
        )
        assert (
            original["error"] == expected_error and original["core_task_id"] == "team-" + identifier
        )
        assert not host.inputs and identifier not in bridge.team_dispatcher._defer
        assert {params["threadId"] for _, params in host.calls} == {ROOT}
        core = bridge.store.get(original["core_task_id"])
        assert core["state"] == "unknown" and core["receipt"] and core["attempt"] == 1

    idle = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="verified-idle")
    async with connected(config, idle, monkeypatch) as (clients, bridge):
        observed = await followup_work(clients, identifier, "unknown")
        assert (
            observed == original
            and bridge.store.get(original["core_task_id"])["receipt"] == core["receipt"]
        )
        assert not idle.calls and not idle.inputs


async def test_busy_followups_leave_later_worker_work_visible_and_expire(
    followup_setup, monkeypatch
):
    config, root, history = followup_setup
    host = PersistedCodex(root, history, loaded={ROOT, OTHER}, generation="busy-queue")
    host.active = True
    original_call = host.call

    async def slow_call(method, params):
        await asyncio.sleep(0.02)
        return await original_call(method, params)

    host.call = slow_call
    monkeypatch.setattr("kirabridge.team_manager.dispatcher._NATIVE_BUSY_RECHECK_SECONDS", 0.01)
    async with connected(config, host, monkeypatch) as (clients, bridge):
        create_followup_team(bridge)
        busy = [
            enqueue_followup(bridge, key=f"busy-{index}")["resume_work_id"] for index in range(16)
        ]
        ordinary = bridge.teams.delegate(
            "local", TeamWorkCreate(**team_order("grok", "Ordinary worker order", "ordinary"))
        )
        expired = enqueue_followup(bridge, key="expired")["resume_work_id"]
        with bridge.store.transaction():
            bridge.store.db.execute(
                "UPDATE team_work SET created=? WHERE id=?",
                (time.time() - config.queue_stale_seconds - 1, expired),
            )
        done = await followup_work(clients, ordinary["id"], "completed")
        assert done["result"] == "GROK_CHILD_DONE"
        ended = await followup_work(clients, expired, "blocked")
        assert ended["error"] == "stale_queue_expired" and ended["core_task_id"] is None
        assert all(
            bridge.teams.work_get("local", "e2e", identifier)["core_task_id"] is None
            for identifier in busy
        )
        assert not host.inputs
        assert all(method == "thread/read" for method, _ in host.calls)


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
    worker_cwd = configure_team(None, config, tmp_path, monkeypatch)
    native_cwd = tmp_path / "operator-session"
    native_cwd.mkdir()
    receiver_cwd = tmp_path / "message-worker"
    receiver_cwd.mkdir()
    assert len({worker_cwd, str(native_cwd), str(receiver_cwd)}) == 3
    config.team.workers["codex"].execution_scope = "existing_native_codex_root"
    config.team.coordinator_resume = True
    config.visible_handoffs.enabled = True
    config.visible_handoffs.native_codex = template(tmp_path).model_copy(
        update={"protocol_version": "0.171.0"}
    )
    config.messaging.receivers["codex"] = ReceiverConfig(cwd=str(receiver_cwd), timeout=3)
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
    observe_reply = CodexHost.wait_reply
    before_ledger = asyncio.Event()

    async def pause_before_ledger(host, binding, turn_id, body, timeout, **kwargs):
        if body.endswith("PING-BEFORE-RESTART"):
            before_ledger.set()
            await asyncio.Event().wait()
        return await observe_reply(host, binding, turn_id, body, timeout, **kwargs)

    monkeypatch.setattr(CodexHost, "wait_reply", pause_before_ledger)
    first = PersistedCodex(
        str(native_cwd), history, loaded={ROOT, OTHER}, generation="before-restart"
    )
    async with connected(config, first, monkeypatch) as (clients, _):
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
        pending = await ping(clients, "PING-BEFORE-RESTART", "pending-restart-ping")
        async with asyncio.timeout(3):
            await before_ledger.wait()
        pending_read = await call(clients, "local", "message_get", message_id=pending["id"])
        assert pending_read["processing"]["state"] == "running"
        assert pending_read["processing"]["evidence"]["turn_id"] == first.turns()[-1]["id"]
        assert first.turns()[-1]["items"][-1]["text"] == "PONG"
    historical = first.turns()[0]
    assert "Prior decision" in historical["items"][0]["content"][0]["text"]
    assert "DECISION_RECORDED" in historical["items"][-1]["text"]

    second = PersistedCodex(
        str(native_cwd), history, loaded=initially_loaded, generation="after-restart"
    )
    restored = Config.model_validate_json(config_file.read_text())
    monkeypatch.setattr(CodexHost, "wait_reply", observe_reply)
    async with connected(restored, second, monkeypatch) as (clients, _):
        team = await call(clients, "local", "team_get", team_id="e2e")
        assert team["coordinator"] == "codex" and team["revision"] == 1
        done = await call(clients, "local", "team_work_get", team_id="e2e", work_id=prior["id"])
        opened = await call(clients, "local", "team_work_get", team_id="e2e", work_id=order["id"])
        assert done["result"] == "DECISION_RECORDED"
        assert opened["state"] == "queued_manual" and opened["body"] == "Open order"
        recovered = await poll(
            lambda: call(clients, "local", "message_get", message_id=pending["id"]),
            lambda row: row["processing"]["state"] == "completed",
        )
        assert recovered["processing"]["result"]["text"] == "PONG"
        assert recovered["processing"]["result"]["message_id"] == pending["id"]
        assert recovered["processing"]["result"]["turn_id"] == first.turns()[1]["id"]
        assert recovered["processing"]["evidence"]["reconciled_without_input"] is True
        assert recovered["processing"]["evidence"]["thread_cwd"] == str(native_cwd.resolve())
        assert not second.inputs
        assert second.loaded == initially_loaded
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
        assert second.inputs[0][0] == sent["id"]
        assert second.inputs[0][1].startswith("[Du bist Koordinator")
        assert second.inputs[0][1].endswith("]\n\nPING")
        assert second.inputs[1][0] == failed["id"] and second.inputs[1][1].endswith("]\n\nFAIL")
        assert sum(method == "thread/resume" for method, _ in second.calls) == (
            ROOT not in initially_loaded
        )
        assert {params["threadId"] for _, params in second.calls} == {ROOT}

    third = PersistedCodex(
        str(native_cwd), history, loaded={ROOT, OTHER}, generation="lookup-restart"
    )
    async with connected(
        Config.model_validate_json(config_file.read_text()), third, monkeypatch
    ) as (clients, _):
        persisted = await call(clients, "local", "message_get", message_id=sent["id"])
        assert persisted["processing"]["result"]["text"] == "PONG"
        persisted_failure = await call(clients, "local", "message_get", message_id=failed["id"])
        assert persisted_failure["processing"]["error"] == "native_codex_turn_unverified"
        repeated = await ping(clients, "PING", "after-restart-ping")
        assert repeated["id"] == sent["id"]
        listing = await call(clients, "local", "team_work_list", team_id="e2e", after=0, limit=20)
        assert [row["id"] for row in listing["work"]] == [prior["id"], order["id"], followup["id"]]
        assert third.calls == third.inputs == []
