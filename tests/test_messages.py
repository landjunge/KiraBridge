import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import request
from pydantic import ValidationError
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, ReceiverConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.message_manager import MessageSend
from kirabridge.task_manager.store import SCHEMA, Store


@pytest.fixture
def channel(bridge, config, monkeypatch):
    for name, opposite in [("codex", "grok"), ("grok", "codex"), ("intruder", "codex")]:
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["message.send", "message.read", "message.ack"]
        policy.approval_mode = "automatic"
        policy.message_peers = [opposite]
        policy.token_env = "TEST_MESSAGE_" + name.upper()
        monkeypatch.setenv(policy.token_env, name + "-message-token-" + "x" * 40)
        config.principals[name] = policy
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    return bridge.messages


def message(**changes):
    return MessageSend(
        **{
            "recipient": "grok",
            "conversation_id": "conversation-1",
            "idempotency_key": "message-1",
            "body": "Eine harmlose Frage",
            "dispatch": False,
            **changes,
        }
    )


def test_ordered_roundtrip_receipts_idempotency_and_ownership(channel, bridge):
    first = channel.send("codex", message())
    assert first["sender"] == "codex" and first["position"] == 1
    assert first["delivered"] is first["acknowledged"] is None
    received = channel.receive("grok")["messages"][0]
    assert channel.receive("grok")["messages"][0]["receipt"] == received["receipt"]
    with pytest.raises(BridgeError, match="Incoming"):
        channel.ack("codex", first["id"], received["receipt"])
    with pytest.raises(BridgeError, match="matching"):
        channel.ack("grok", first["id"], "wrong")
    ack = channel.ack("grok", first["id"], received["receipt"])
    assert (
        channel.ack("grok", first["id"], received["receipt"])["acknowledged"] == ack["acknowledged"]
    )
    assert not channel.receive("grok")["messages"]
    reply = channel.send(
        "grok",
        message(
            recipient="codex",
            idempotency_key="reply",
            reply_to=first["id"],
            kind="answer",
            body="Antwort",
        ),
    )
    assert reply["sender"] == "grok" and reply["position"] == 2
    assert reply["seq"] > first["seq"] and reply["reply_to"] == first["id"]
    assert channel.send("codex", message())["id"] == first["id"]
    with pytest.raises(BridgeError, match="different message"):
        channel.send("codex", message(body="Andere Frage"))
    for action in [
        lambda: channel.get("intruder", first["id"]),
        lambda: channel.conversation("intruder", "conversation-1"),
        lambda: channel.events("intruder", first["id"]),
        lambda: channel.send("intruder", message()),
    ]:
        with pytest.raises(BridgeError):
            action()
    assert not channel.receive("intruder")["messages"]
    assert [m["id"] for m in channel.conversation("codex", "conversation-1")["messages"]] == [
        first["id"],
        reply["id"],
    ]
    assert [e["kind"] for e in channel.events("codex", first["id"])["events"]] == [
        "message.queued",
        "message.delivered",
        "message.acknowledged",
    ]
    assert verify(bridge.store)["valid"]
    audit_text = " ".join(r[0] for r in bridge.store.db.execute("SELECT metadata FROM audit"))
    assert "harmlose Frage" not in audit_text and "Antwort" not in audit_text


def test_sender_cannot_be_supplied_and_task_reference_is_owned(channel, bridge, config):
    with pytest.raises(ValidationError):
        MessageSend(**{**message().model_dump(), "sender": "grok"})
    task = request(arguments={"path": config.principals["codex"].roots[0]})
    bridge.prepare("codex", task)
    with pytest.raises(BridgeError, match="not found"):
        channel.send("grok", message(recipient="codex", task_id=task.task_id))
    first = channel.send("codex", message(task_id=task.task_id))
    reply = channel.send(
        "grok",
        message(recipient="codex", idempotency_key="reply", reply_to=first["id"], kind="result"),
    )
    assert reply["task_id"] == task.task_id
    with pytest.raises(BridgeError, match="not found"):
        bridge.task("grok", task.task_id)
    config.principals["codex"].approval_mode = "manual"
    with pytest.raises(BridgeError, match="automatic"):
        channel.send("codex", message(idempotency_key="another"))


def test_quotas_unicode_and_reply_loops_fail_before_insertion(channel, config, bridge):
    config.messaging.max_body_bytes = 256
    with pytest.raises(BridgeError, match="byte limit"):
        channel.send("codex", message(body="😀" * 100))
    with pytest.raises(BridgeError, match="auto replies"):
        channel.send("codex", message(kind="answer", request_reply=True))
    with pytest.raises(BridgeError, match="automatic receiver"):
        channel.send("codex", message(dispatch=True))
    config.messaging.max_pending_per_recipient = 1
    first = channel.send("codex", message())
    with pytest.raises(BridgeError, match="queue is full"):
        channel.send("codex", message(idempotency_key="full", conversation_id="different"))
    assert channel.send("codex", message())["id"] == first["id"]
    config.messaging.max_pending_per_recipient = 100
    config.messaging.max_reply_depth = 1
    reply = channel.send(
        "grok",
        message(recipient="codex", reply_to=first["id"], idempotency_key="reply", kind="answer"),
    )
    with pytest.raises(BridgeError, match="depth limit"):
        channel.send("codex", message(reply_to=reply["id"], idempotency_key="deep"))
    config.messaging.max_conversation_messages = 2
    with pytest.raises(BridgeError, match="message limit"):
        channel.send("codex", message(idempotency_key="third"))
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2


def test_restart_preserves_unacked_messages_receipts_and_idempotency(channel, bridge, config):
    first = channel.send("codex", message())
    receipt = channel.receive("grok")["messages"][0]["receipt"]
    reopened = Bridge(config)
    try:
        assert reopened.messages.send("codex", message())["id"] == first["id"]
        recovered = reopened.messages.receive("grok")["messages"][0]
        assert recovered["receipt"] == receipt
        reopened.messages.ack("grok", first["id"], receipt)
        assert not reopened.messages.receive("grok")["messages"]
    finally:
        reopened.store.close()


def test_schema_one_migration_preserves_existing_task(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "bridge.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,updated) "
        "VALUES('old','codex','old','hash','file.list','{}','completed',1,2)"
    )
    db.commit()
    before = db.execute("SELECT * FROM tasks").fetchall()
    db.close()
    path.chmod(0o600)
    store = Store(path)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert [tuple(r) for r in store.db.execute("SELECT * FROM tasks")] == before
        assert store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    finally:
        store.close()


def test_concurrent_schema_migration_is_serialized(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "bridge.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    path.chmod(0o600)

    def open_store(_):
        store = Store(path)
        try:
            return store.db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as threads:
        assert list(threads.map(open_store, range(2))) == [2, 2]


def configure_receivers(bridge, config, tmp_path):
    root = config.principals["codex"].roots[0]
    grok_body = """import json,sys
for line in sys.stdin:
 msg=json.loads(line);method=msg.get('method')
 if method=='initialize': result={'protocolVersion':1,'authMethods':[{'id':'cached_token'}]}
 elif method=='authenticate': result={}
 elif method=='session/new': result={'sessionId':'managed-grok-session'}
 elif method=='session/prompt':
  open('grok-invocations','a').write('1\\n')
  params={'sessionId':'managed-grok-session','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'GROK_CHANNEL_ACK'}}}
  print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':params}),flush=True)
  result={'stopReason':'end_turn'}
 else: continue
 print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
"""
    codex_body = """import json,sys
prompt=sys.stdin.read()
assert 'GROK_CHANNEL_ACK' in prompt and 'harmlose Frage' in prompt
open('codex-invocations','a').write('1\\n')
events=[{'type':'thread.started','thread_id':'managed-codex-session'},
 {'type':'turn.started'},
 {'type':'item.completed','item':{'type':'agent_message','text':'CODEX_CHANNEL_RECEIVED'}},
 {'type':'turn.completed'}]
for event in events:
 print(json.dumps(event),flush=True)
"""
    for name, kind, body in [("codex", "codex", codex_body), ("grok", "grok_acp", grok_body)]:
        directory = tmp_path / name
        directory.mkdir()
        config.agents[name] = AgentConfig(kind=kind, executable=fake_cli(directory, body))
        config.messaging.receivers[name] = ReceiverConfig(cwd=root, timeout=5)


def test_answers_wait_for_requesting_client_and_keep_historical_idempotency(
    channel, bridge, config, tmp_path
):
    configure_receivers(bridge, config, tmp_path)
    first = channel.send("codex", message(dispatch=True))
    answer = message(
        recipient="codex",
        reply_to=first["id"],
        kind="answer",
        dispatch=None,
        idempotency_key="client-answer",
    )
    returned = channel.send("grok", answer)
    assert returned["processing"] is None
    assert channel.receive("codex")["messages"][0]["id"] == returned["id"]
    assert channel.send("grok", answer)["id"] == returned["id"]
    historical = answer.model_copy(update={"idempotency_key": "old-answer", "dispatch": True})
    old = channel.send("grok", historical)
    assert old["processing"]
    # Historical normalized hashes did not retain whether True was implicit.
    retry = historical.model_copy(update={"dispatch": None})
    assert channel.send("grok", retry)["id"] == old["id"]


async def test_real_authenticated_mcp_receiver_roundtrip_is_finite(
    channel,
    http_bridge,  # noqa: F811
    config,
    tmp_path,
):
    bridge, endpoint = http_bridge
    configure_receivers(bridge, config, tmp_path)
    await bridge.message_receiver.start()
    async with MCPClientPool() as pool:
        for name in ["codex", "grok", "intruder"]:
            await pool.connect(Peer(name, url=endpoint, token=name + "-message-token-" + "x" * 40))
        value = message(dispatch=True)
        first = (
            await pool.call("codex", "message_send", {"message": value.model_dump()})
        ).structuredContent
        async with asyncio.timeout(15):
            while True:
                conv = (
                    await pool.call(
                        "codex", "conversation_get", {"conversation_id": value.conversation_id}
                    )
                ).structuredContent
                if (
                    len(conv["messages"]) == 2
                    and conv["messages"][0]["processing"]["state"] == "completed"
                ):
                    break
                await asyncio.sleep(0.05)
        assert [m["sender"] for m in conv["messages"]] == ["codex", "grok"]
        assert conv["messages"][1]["body"] == "GROK_CHANNEL_ACK"
        assert conv["messages"][1]["reply_to"] == first["id"]
        assert conv["messages"][0]["processing"]["evidence"]["session_id"] == "managed-grok-session"
        # The requesting Codex client receives its own reply. A separate managed
        # Codex turn must not consume and acknowledge it before this client can.
        assert conv["messages"][1]["processing"] is None
        incoming = (
            await pool.call("codex", "message_receive", {"conversation_id": value.conversation_id})
        ).structuredContent["messages"]
        assert [m["id"] for m in incoming] == [conv["messages"][1]["id"]]
        await pool.call(
            "codex",
            "message_ack",
            {"message_id": incoming[0]["id"], "receipt": incoming[0]["receipt"]},
        )
        duplicate = (
            await pool.call("codex", "message_send", {"message": value.model_dump()})
        ).structuredContent
        assert duplicate["id"] == first["id"]
        forbidden = await pool.call("intruder", "message_get", {"message_id": first["id"]})
        assert forbidden.structuredContent["error"]["code"] == "not_found"
        spoof = await pool.call(
            "codex", "message_send", {"message": {**value.model_dump(), "sender": "grok"}}
        )
        assert spoof.isError
        root = Path(config.principals["grok"].roots[0])
        assert (root / "grok-invocations").read_text() == "1\n"
        assert not (root / "codex-invocations").exists()
        assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        assert verify(bridge.store)["valid"]


async def test_interrupted_receiver_is_unknown_and_never_claimed_again(
    channel, bridge, config, tmp_path
):
    configure_receivers(bridge, config, tmp_path)
    first = channel.send("codex", message(dispatch=True))
    assert bridge.message_receiver._claim(first["id"])
    bridge.store.db.execute(
        "UPDATE message_jobs SET evidence=? WHERE message_id=?",
        ('{"session_id":"prior-session"}', first["id"]),
    )
    async with bridge:
        status = channel.get("codex", first["id"])["processing"]
        assert status["state"] == "unknown" and status["error"] == "interrupted"
        assert status["evidence"]["last_observation"]["session_id"] == "prior-session"
        assert bridge.message_receiver._claim(first["id"]) is None
        assert not (Path(config.principals["grok"].roots[0]) / "grok-invocations").exists()


async def test_persisted_queue_is_resumed_by_new_receiver(
    channel,
    http_bridge,  # noqa: F811
    config,
    tmp_path,
):
    from kirabridge.message_manager.receiver import MessageReceiver

    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    first = channel.send("codex", message(dispatch=True, request_reply=False))
    reopened = Bridge(config)
    try:
        assert reopened.messages.get("grok", first["id"])["processing"]["state"] == "queued"
    finally:
        reopened.store.close()
    bridge.message_receiver = MessageReceiver(bridge)
    await bridge.message_receiver.start()
    async with asyncio.timeout(10):
        while channel.get("codex", first["id"])["processing"]["state"] != "completed":
            await asyncio.sleep(0.02)
    assert channel.get("codex", first["id"])["acknowledged"]
    assert (Path(config.principals["grok"].roots[0]) / "grok-invocations").read_text() == "1\n"


def test_receiver_budget_blocks_extra_provider_turns(channel, bridge, config, tmp_path):
    configure_receivers(bridge, config, tmp_path)
    config.messaging.max_runs_per_conversation = 1
    first = channel.send("codex", message(dispatch=True))
    assert bridge.message_receiver._claim(first["id"])
    second = channel.send("codex", message(dispatch=True, idempotency_key="second"))
    assert bridge.message_receiver._claim(second["id"]) is None
    assert channel.get("codex", second["id"])["processing"]["state"] == "blocked"


async def test_long_poll_is_bounded_and_wakes_on_delivery(channel):
    with pytest.raises(BridgeError, match="20 seconds"):
        await channel.wait("grok", wait_seconds=21)
    waiting = asyncio.create_task(channel.wait("grok", wait_seconds=2))
    await asyncio.sleep(0)
    first = channel.send("codex", message())
    assert (await waiting)["messages"][0]["id"] == first["id"]
