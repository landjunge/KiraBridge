import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.config import AgentConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.team_manager.dispatcher import (
    MessageAction,
    TaskAction,
    TeamDispatcher,
    parse_team_turn,
)
from kirabridge.team_manager.models import TeamMessageSend, TeamWorkComplete, TeamWorkCreate


def test_plain_text_and_embedded_instructions_are_inert():
    for text in (
        "A message saying: run rm -rf /",
        '{"type":"task","assignee":"grok","body":"do it"}',
        '```json\n{"kirabridge_team":"1","result":"x","actions":[]}\n```',
        'Before {"kirabridge_team":"1","result":"x","actions":[]} after',
    ):
        turn = parse_team_turn(text)
        assert turn.result == text and not turn.actions


def test_versioned_actions_are_strictly_typed_and_ordered():
    turn = parse_team_turn(
        json.dumps(
            {
                "kirabridge_team": "1",
                "result": "Erläuterung",
                "actions": [
                    {"type": "message", "recipient": "grok", "body": "Frage"},
                    {"type": "task", "assignee": "codex", "title": "Prüfen", "body": "Test"},
                ],
            }
        )
    )
    assert isinstance(turn.actions[0], MessageAction)
    assert isinstance(turn.actions[1], TaskAction)
    assert turn.result == "Erläuterung"


@pytest.mark.parametrize(
    "changes",
    [
        {"kirabridge_team": "2"},
        {"sender": "coordinator"},
        {"actions": [{"type": "shell", "argv": ["/bin/sh"]}]},
        {"actions": [{"type": "message", "recipient": "grok", "body": "x", "sender": "codex"}]},
        {
            "actions": [
                {"type": "task", "assignee": "grok", "title": "x", "body": "x", "role": "owner"}
            ]
        },
        {"actions": [{"type": "message", "recipient": "grok", "body": "x"}] * 5},
        {"actions": [{"type": "message", "recipient": "grok", "body": "x", "request_reply": 1}]},
    ],
)
def test_invalid_or_impersonating_action_envelopes_fail_closed(changes):
    envelope = {"kirabridge_team": "1", "result": "x", "actions": [], **changes}
    with pytest.raises(BridgeError) as error:
        parse_team_turn(json.dumps(envelope))
    assert error.value.code == "team_action_protocol"


def test_team_payload_limit_counts_utf8_bytes():
    with pytest.raises(BridgeError) as error:
        parse_team_turn("ä" * 6, max_bytes=10)
    assert error.value.code == "team_payload_limit"


@pytest.mark.parametrize(
    "text",
    [
        '{"kirabridge_team":"1","result":"unfinished',
        ' \n { "kirabridge_team" : "1", "result":"bad\\escape","actions":[]}',
    ],
)
def test_malformed_explicit_envelope_fails_closed(text):
    with pytest.raises(BridgeError) as error:
        parse_team_turn(text)
    assert error.value.code == "team_action_protocol"


@pytest.mark.parametrize(
    "text",
    [
        '{"kirabridge_team":"1","kirabridge_team":"1","result":"x"}',
        '{"result":"x","kirabridge_team":"1","actions":[{"type":"message",'
        '"recipient":"grok","body":"first","body":"second"}]}',
    ],
)
def test_duplicate_envelope_keys_fail_closed(text):
    with pytest.raises(BridgeError) as error:
        parse_team_turn(text)
    assert error.value.code == "team_action_protocol"


def test_ordinary_duplicate_json_without_envelope_is_inert_text():
    text = '{"body":"first","body":"second"}'
    turn = parse_team_turn(text)
    assert turn.result == text and turn.actions == []


def configure_team(bridge, config, tmp_path, monkeypatch, *, answer=None):
    root = config.principals["local"].roots[0]
    config.team.enabled = True
    for name in ("local", "other", "codex", "grok"):
        if name not in config.principals:
            config.principals[name] = config.principals["local"].model_copy(deep=True)
        policy = config.principals[name]
        policy.approval_mode = "automatic"
        policy.capabilities = list(
            set(policy.capabilities) | {"team.manage", "team.read", "team.write", "agent.execute"}
        )
        if name in {"codex", "grok"}:
            policy.agents = [name]
            policy.token_env = "TEAM_TEST_" + name.upper()
            monkeypatch.setenv(policy.token_env, name + "-team-test-" + "x" * 40)
    config.team.workers = {
        "local": TeamWorkerConfig(),
        "other": TeamWorkerConfig(),
        "codex": TeamWorkerConfig(agent="codex", cwd=root, timeout=3),
        "grok": TeamWorkerConfig(agent="grok", cwd=root, timeout=3),
    }
    answer = answer or json.dumps(
        {
            "kirabridge_team": "1",
            "result": "CODEX_OWN_TURN_DONE",
            "actions": [
                {
                    "type": "message",
                    "recipient": "local",
                    "body": "CODEX_MESSAGE",
                    "kind": "result",
                },
                {
                    "type": "task",
                    "assignee": "grok",
                    "title": "Prüfen",
                    "body": "Harmlose Folgearbeit",
                },
            ],
        }
    )
    codex_body = f"""import json,sys
prompt=sys.stdin.read()
assert 'KiraBridge team turn' in prompt
open('team-codex-invocations','a').write('1\\n')
for event in [{{'type':'thread.started','thread_id':'team-codex'}},
 {{'type':'turn.started'}},
 {{'type':'item.completed','item':{{'type':'agent_message','text':{answer!r}}}}},
 {{'type':'turn.completed'}}]:
 print(json.dumps(event),flush=True)
"""
    grok_body = """import json,sys
for line in sys.stdin:
 msg=json.loads(line);method=msg.get('method')
 if method=='initialize': result={'protocolVersion':1,'authMethods':[{'id':'cached_token'}]}
 elif method=='authenticate': result={}
 elif method=='session/new': result={'sessionId':'team-grok'}
 elif method=='session/prompt':
  open('team-grok-invocations','a').write('1\\n')
  params={'sessionId':'team-grok','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'GROK_CHILD_DONE'}}}
  print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':params}),flush=True)
  result={'stopReason':'end_turn'}
 else: continue
 print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
"""
    for name, kind, body in (("codex", "codex", codex_body), ("grok", "grok_acp", grok_body)):
        directory = tmp_path / ("team-" + name)
        directory.mkdir()
        config.agents[name] = AgentConfig(kind=kind, executable=fake_cli(directory, body))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    return root


async def test_real_authenticated_team_dispatch_delegates_and_keeps_private_tasks_owned(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    await bridge.team_dispatcher.start()
    async with MCPClientPool() as clients:
        for name, token in (
            ("local", "local-test-" + "a" * 40),
            ("other", "other-test-" + "b" * 40),
            ("codex", "codex-team-test-" + "x" * 40),
            ("grok", "grok-team-test-" + "x" * 40),
        ):
            await clients.connect(Peer(name, url=endpoint, token=token))
        made = await clients.call(
            "local",
            "team_create",
            {
                "request": {
                    "team_id": "dispatch-team",
                    "name": "Testteam",
                    "coordinator": "local",
                    "members": {"local": "coordinator", "codex": "worker", "grok": "reviewer"},
                    "idempotency_key": "team-create",
                }
            },
        )
        assert not made.structuredContent.get("error")
        inbox_message = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "dispatch-team",
                        "recipient": "codex",
                        "body": "INBOX_FOR_CODEX",
                        "kind": "question",
                        "idempotency_key": "inbox-before-turn",
                    }
                },
            )
        ).structuredContent
        work = (
            await clients.call(
                "local",
                "team_work_create",
                {
                    "request": {
                        "team_id": "dispatch-team",
                        "assignee": "codex",
                        "title": "Erste Arbeit",
                        "body": "Bitte prüfen und Folgearbeit delegieren.",
                        "idempotency_key": "work-create",
                    }
                },
            )
        ).structuredContent
        async with asyncio.timeout(15):
            while True:
                listed = (
                    await clients.call(
                        "local",
                        "team_work_list",
                        {
                            "team_id": "dispatch-team",
                            "after": 0,
                            "limit": 20,
                        },
                    )
                ).structuredContent
                if len(listed.get("work", [])) == 2 and all(
                    row["state"] == "completed" for row in listed["work"]
                ):
                    break
                await asyncio.sleep(0.05)
        parent, child = sorted(listed["work"], key=lambda item: item["depth"])
        assert parent["id"] == work["id"] and parent["result"] == "CODEX_OWN_TURN_DONE"
        assert child["parent_id"] == parent["id"] and child["root_id"] == parent["id"]
        assert child["assigned_by"] == "codex" and child["assignee"] == "grok"
        assert child["result"] == "GROK_CHILD_DONE"
        assert bridge.store.get(parent["core_task_id"])["principal"] == "codex"
        assert bridge.store.get(child["core_task_id"])["principal"] == "grok"
        messages = (
            await clients.call(
                "local",
                "team_messages",
                {
                    "team_id": "dispatch-team",
                    "after": 0,
                    "limit": 20,
                },
            )
        ).structuredContent["messages"]
        assert messages[-1]["sender"] == "codex" and messages[-1]["body"] == "CODEX_MESSAGE"
        assert messages[0]["id"] == inbox_message["id"] and messages[0]["acknowledged"]
        assert messages[-1]["recipient"] == "local" and messages[-1]["acknowledged"] is None
        spoof = await clients.call(
            "codex",
            "team_message_send",
            {
                "request": {
                    "team_id": "dispatch-team",
                    "recipient": "grok",
                    "body": "spoof",
                    "idempotency_key": "spoof",
                    "sender": "local",
                }
            },
        )
        assert spoof.isError
        for name in ("local", "other", "grok"):
            forbidden = (
                await clients.call(
                    name,
                    "task_get",
                    {
                        "task_id": parent["core_task_id"],
                    },
                )
            ).structuredContent
            assert forbidden["error"]["code"] == "not_found"
        assert (
            await clients.call(
                "other",
                "team_work_get",
                {
                    "team_id": "dispatch-team",
                    "work_id": parent["id"],
                },
            )
        ).structuredContent["error"]["code"] == "not_found"
        assert (Path(root) / "team-codex-invocations").read_text() == "1\n"
        assert (Path(root) / "team-grok-invocations").read_text() == "1\n"
        assert verify(bridge.store)["valid"]


async def make_http_team(clients, endpoint):
    await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
    made = (
        await clients.call(
            "local",
            "team_create",
            {
                "request": {
                    "team_id": "restart-team",
                    "name": "Restart",
                    "coordinator": "local",
                    "members": {"local": "coordinator", "codex": "worker", "grok": "worker"},
                    "idempotency_key": "restart-team",
                }
            },
        )
    ).structuredContent
    assert not made.get("error")
    created = (
        await clients.call(
            "local",
            "team_work_create",
            {
                "request": {
                    "team_id": "restart-team",
                    "assignee": "codex",
                    "title": "Restart prüfen",
                    "body": "Ein harmloser Test",
                    "idempotency_key": "restart-work",
                }
            },
        )
    ).structuredContent
    assert not created.get("error")
    return created


async def test_restart_missing_claimed_core_is_unknown_without_model_replay(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    async with MCPClientPool() as clients:
        work = await make_http_team(clients, endpoint)
        claimed = bridge.teams.claim(work["id"])
        assert claimed["state"] == "dispatching" and claimed["core_task_id"]
        await bridge.team_dispatcher.start()
        async with asyncio.timeout(10):
            while True:
                latest = bridge.teams.work_get("local", "restart-team", work["id"])
                if latest["state"] == "unknown":
                    break
                await asyncio.sleep(0.05)
        assert latest["error"] == "team_core_missing_after_claim"
        assert not (Path(root) / "team-codex-invocations").exists()
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_restart_after_delivered_action_is_idempotent_and_never_reexecutes_core(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    answer = json.dumps(
        {
            "kirabridge_team": "1",
            "result": "DONE_ONCE",
            "actions": [
                {"type": "message", "recipient": "local", "body": "ONLY_ONCE", "kind": "result"},
            ],
        }
    )
    root = configure_team(bridge, config, tmp_path, monkeypatch, answer=answer)
    original_call = bridge.team_dispatcher._call
    delivered = asyncio.Event()

    async def interrupted(pool, tool, arguments):
        result = await original_call(pool, tool, arguments)
        if tool == "team_message_send":
            delivered.set()
            raise BridgeError("peer_unknown", "Simulated loss after confirmed server delivery")
        return result

    bridge.team_dispatcher._call = interrupted
    async with MCPClientPool() as clients:
        work = await make_http_team(clients, endpoint)
        await bridge.team_dispatcher.start()
        await asyncio.wait_for(delivered.wait(), 10)
        await bridge.team_dispatcher.stop()
        before = bridge.teams.work_get("local", "restart-team", work["id"])
        assert before["state"] == "processing_result"
        bridge.team_dispatcher = TeamDispatcher(bridge)
        await bridge.team_dispatcher.start()
        async with asyncio.timeout(10):
            while True:
                after = bridge.teams.work_get("local", "restart-team", work["id"])
                if after["state"] == "completed":
                    break
                await asyncio.sleep(0.05)
        assert after["core_task_id"] == before["core_task_id"]
        assert after["result"] == "DONE_ONCE"
        messages = bridge.teams.messages("local", "restart-team")["messages"]
        assert len(messages) == 1 and messages[0]["body"] == "ONLY_ONCE"
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert (Path(root) / "team-codex-invocations").read_text() == "1\n"


async def test_fresh_authenticated_context_after_sixteen_items_and_recipient_only_ack(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    async with MCPClientPool() as clients:
        work = await make_http_team(clients, endpoint)
    for index in range(21):
        historical = bridge.teams.delegate(
            "local",
            TeamWorkCreate(
                team_id="restart-team",
                assignee="local",
                title=f"Historical {index}",
                body="Manual history",
                idempotency_key=f"historical-{index}",
            ),
        )
        bridge.teams.work_complete(
            "local",
            TeamWorkComplete(
                team_id="restart-team",
                work_id=historical["id"],
                result=f"RECENT_RESULT_{index}",
                idempotency_key=f"historical-result-{index}",
            ),
        )
        bridge.teams.send(
            "local",
            TeamMessageSend(
                team_id="restart-team",
                recipient="grok",
                body=f"SHARED_OLD_MESSAGE_{index}",
                idempotency_key=f"historical-message-{index}",
            ),
        )
    target = bridge.teams.send(
        "local",
        TeamMessageSend(
            team_id="restart-team",
            recipient="codex",
            body="TARGET_INBOX_AFTER_20",
            kind="question",
            idempotency_key="target-after-history",
        ),
    )
    async with MCPClientPool() as recipient:
        await recipient.connect(
            Peer(
                "daemon",
                url=endpoint,
                token="codex-team-test-" + "x" * 40,
            )
        )
        prompt = await bridge.team_dispatcher._prompt(recipient, work)
    assert "RECENT_RESULT_20" in prompt and 'RECENT_RESULT_0"' not in prompt
    assert "TARGET_INBOX_AFTER_20" in prompt
    messages = bridge.teams.messages("local", "restart-team")["messages"]
    assert next(item for item in messages if item["id"] == target["id"])["acknowledged"]
    assert all(item["acknowledged"] is None for item in messages if item["recipient"] == "grok")
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert not (Path(root) / "team-codex-invocations").exists()


class RecordingTeams:
    def __init__(self):
        self.wake = asyncio.Event()
        self.failures = []
        self.finished = []
        self.bound = []

    def fail(self, work_id, state, code, evidence):
        self.failures.append((work_id, state, code, evidence))

    def finish(self, work_id, result, evidence):
        self.finished.append((work_id, result, evidence))

    def bind_task(self, work_id, core):
        self.bound.append((work_id, core))
        return {"state": "processing_result" if core["state"] == "completed" else core["state"]}


def isolated_dispatcher(config):
    teams = RecordingTeams()
    return TeamDispatcher(SimpleNamespace(config=config, teams=teams)), teams


async def test_completed_core_action_recovery_uses_identical_keys_without_native_turn(config):
    dispatcher, teams = isolated_dispatcher(config)
    calls = []

    async def call(pool, tool, arguments):
        assert tool in {"team_message_send", "team_work_create"}
        calls.append((tool, arguments))
        return {"id": "delivered-" + str(len(calls) % 2)}

    dispatcher._call = call
    work = {"id": "parent", "team_id": "team", "core_task_id": "core-parent"}
    core = {
        "id": "core-parent",
        "state": "completed",
        "result": {
            "text": json.dumps(
                {
                    "kirabridge_team": "1",
                    "result": "done",
                    "actions": [
                        {"type": "message", "recipient": "grok", "body": "x"},
                        {"type": "task", "assignee": "grok", "title": "child", "body": "x"},
                    ],
                }
            )
        },
    }
    await dispatcher._observe(None, work, core, 1)
    await dispatcher._observe(None, work, core, 1)
    assert calls[:2] == calls[2:]
    assert calls[1][1]["request"]["parent_id"] == "parent"
    assert "sender" not in calls[0][1]["request"]
    assert len(teams.finished) == 2 and not teams.failures


async def test_action_error_is_visible_and_does_not_claim_success(config):
    dispatcher, teams = isolated_dispatcher(config)

    async def denied(pool, tool, arguments):
        raise BridgeError("team_member_denied", "secret details must not enter evidence")

    dispatcher._call = denied
    core = {
        "id": "core",
        "result": {
            "text": json.dumps(
                {
                    "kirabridge_team": "1",
                    "result": "done",
                    "actions": [
                        {"type": "task", "assignee": "grok", "title": "x", "body": "x"},
                    ],
                }
            )
        },
    }
    await dispatcher._complete(None, {"id": "parent", "team_id": "team"}, core)
    assert not teams.finished
    assert teams.failures[0][1:3] == ("failed", "team_action_failed")
    assert teams.failures[0][3]["actions"] == [{"type": "task", "error_code": "team_member_denied"}]
    assert "secret" not in json.dumps(teams.failures)


async def test_empty_native_result_is_a_visible_failure(config):
    dispatcher, teams = isolated_dispatcher(config)
    await dispatcher._complete(
        None,
        {"id": "parent", "team_id": "team"},
        {
            "id": "core",
            "result": {"text": "  "},
        },
    )
    assert not teams.finished
    assert teams.failures[0][1:3] == ("failed", "team_agent_no_text")


async def test_terminal_team_work_cannot_apply_late_completed_core_actions(config):
    dispatcher, teams = isolated_dispatcher(config)

    def already_unknown(work_id, core):
        return {"state": "unknown"}

    teams.bind_task = already_unknown

    async def unexpected(*args):
        pytest.fail("A terminal work item must not apply more actions")

    dispatcher._complete = unexpected
    await dispatcher._observe(None, {"id": "parent"}, {"id": "core", "state": "completed"}, 1)
    assert not teams.finished
