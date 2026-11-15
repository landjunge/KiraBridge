import json
import time
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.config import AgentConfig, ReceiverConfig
from kirabridge.message_manager import MessageSend
from kirabridge.message_manager.guidance import consume, ready


@pytest.fixture
def managed(bridge, config):
    config.messaging.separate_managed_after = time.time() - 30
    for name, peer in [("codex_channel", "chatgpt"), ("chatgpt", "codex_channel")]:
        p = config.principals["local"].model_copy(deep=True)
        p.capabilities += ["message.read", "message.send", "message.ack", "agent.execute"]
        p.message_peers = [peer]
        p.agents = ["codex_channel"]
        p.approval_mode = "automatic"
        config.principals[name] = p
    config.agents["codex_channel"] = AgentConfig(kind="codex")
    config.messaging.receivers["codex_channel"] = ReceiverConfig(
        cwd=config.principals["local"].roots[0], timeout=5
    )
    calls = []

    class Pool:
        async def call(self, server, tool, args):
            assert server == "daemon"
            if tool == "message_receive":
                v = bridge.messages.receive("codex_channel", **args)
            elif tool == "message_ack":
                assert calls, "ACK must follow model processing"
                v = bridge.messages.ack("codex_channel", args["message_id"], args["receipt"])
            else:
                raise AssertionError(tool)
            return SimpleNamespace(isError=False, structuredContent=v)

    async def execute(task, args, policy, running, progress, **kw):
        assert task["principal"] == "codex_channel" and kw["separate_managed"]
        calls.append(json.loads(args.prompt))
        await running({"event": "turn.started", "session_id": "fixture"})
        return {
            "success": True,
            "text": "Guidance understood, UI wake unproven.",
            "evidence": {"turn_completed": True},
        }

    bridge.agents.execute = execute
    return bridge, config, Pool(), calls


def note(b, key, body="Original note ä🙂", **extra):
    return b.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex_channel",
            conversation_id="guidance",
            idempotency_key=key,
            body=body,
            kind="note",
            dispatch=False,
            request_reply=False,
            **extra,
        ),
    )


async def test_idle_batch_preserves_originals_acks_after_processing_and_no_reply(managed):
    b, cfg, pool, calls = managed
    original = [note(b, str(i), "body " + str(i)) for i in range(4)]
    assert ready(b.message_receiver, "codex_channel")
    assert await consume(b.message_receiver, "codex_channel", pool)
    assert len(calls) == 1
    assert [(x["id"], x["body"]) for x in calls[0]["messages"]] == [
        (x["id"], x["body"]) for x in original
    ]
    for row in original:
        actual = b.messages.get("chatgpt", row["id"])
        assert actual["acknowledged"] and actual["processing"]["state"] == "completed"
        assert actual["request_reply"] is False and actual["processing"]["reply_id"] is None
    assert b.store.db.execute("select count(*) from messages").fetchone()[0] == 4
    assert not ready(b.message_receiver, "codex_channel")
    assert not await consume(b.message_receiver, "codex_channel", pool)
    assert len(calls) == 1


async def test_busy_waits_for_boundary_without_interrupt(managed):
    b, cfg, pool, calls = managed
    busy = b.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex_channel",
            conversation_id="busy",
            idempotency_key="busy",
            body="Busy",
            kind="work",
            dispatch=True,
        ),
    )
    b.message_receiver._claim(busy["id"], direct=True)
    n = note(b, "waiting")
    assert not await consume(b.message_receiver, "codex_channel", pool)
    assert not calls and not b.messages.get("chatgpt", n["id"])["acknowledged"]
    b.store.db.execute(
        "update message_jobs set state='completed' where message_id=?", (busy["id"],)
    )
    assert await consume(b.message_receiver, "codex_channel", pool)


async def test_passive_before_cutoff_and_results_never_start_models(managed):
    b, cfg, pool, calls = managed
    n = note(b, "old")
    cfg.messaging.separate_managed_after = time.time() + 1
    assert not await consume(b.message_receiver, "codex_channel", pool)
    cfg.messaging.separate_managed_after = None
    assert not ready(b.message_receiver, "codex_channel")
    assert not await consume(b.message_receiver, "codex_channel", pool)
    cfg.messaging.separate_managed_after = time.time() - 30
    b.store.db.execute("update messages set kind='result' where id=?", (n["id"],))
    assert not ready(b.message_receiver, "codex_channel")
    assert not await consume(b.message_receiver, "codex_channel", pool)
    assert not calls


async def test_unknown_guidance_is_never_replayed(managed):
    b, cfg, pool, calls = managed
    n = note(b, "unknown")

    async def fail(*a, **k):
        raise RuntimeError("fixture failure")

    b.agents.execute = fail
    with pytest.raises(RuntimeError):
        await consume(b.message_receiver, "codex_channel", pool)
    actual = b.messages.get("chatgpt", n["id"])
    assert actual["processing"]["state"] == "unknown" and actual["acknowledged"] is None
    assert not await consume(b.message_receiver, "codex_channel", pool)


async def test_budget_and_owner_isolation(managed):
    b, cfg, pool, calls = managed
    n = note(b, "quota")
    cfg.messaging.max_runs_per_hour = 1
    prior = note(b, "prior")
    b.store.db.execute(
        "insert into message_jobs(message_id,state,claimed) values(?,'completed',?)",
        (prior["id"], time.time()),
    )
    assert not await consume(b.message_receiver, "codex_channel", pool)
    assert not calls and not b.messages.get("chatgpt", n["id"])["acknowledged"]
    assert not await consume(b.message_receiver, "chatgpt", pool)
