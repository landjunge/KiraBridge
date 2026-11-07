"""Real authenticated HTTP distinguishes busy native admission from inbox guidance.

The terminal boundary is simulated; no operator terminal, live inbox or token is used.
"""
# Imported fixtures are used by pytest.
# ruff: noqa: F811

import json

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.message_manager import MessageSend


@pytest.fixture
def working_channel(visible, monkeypatch):
    bridge, transport = visible
    for name in ("chatgpt", "codex", "foreign"):
        if name == "foreign":
            bridge.config.principals[name] = bridge.config.principals["codex"].model_copy(deep=True)
        policy = bridge.config.principals[name]
        policy.token_env = "TEST_WORKING_CHANNEL_" + name.upper()
        monkeypatch.setenv(policy.token_env, name + "-working-" + "x" * 40)
    bridge.config.messaging.receivers["codex"] = ReceiverConfig(
        cwd=bridge.config.principals["codex"].roots[0], timeout=3
    )
    admissions = []

    async def working(*args):
        admissions.append(args)
        error = BridgeError("visible_target_working", "Codex is already working")
        error.observation = {
            "state": "working",
            "ready": False,
            "reason": "current_progress_row",
            "input_empty": True,
            "target": "codex",
        }
        raise error

    async def no_execution(*args, **kwargs):
        pytest.fail("Working-session guidance must not launch an agent execution")

    monkeypatch.setattr(bridge.visible_handoffs, "dispatch_ready", working)
    monkeypatch.setattr(bridge.agents, "execute", no_execution)
    return bridge, transport, admissions


async def connect(clients, endpoint):
    for name in ("chatgpt", "codex", "foreign"):
        await clients.connect(Peer(name, url=endpoint, token=name + "-working-" + "x" * 40))


async def call(clients, name, tool, arguments):
    return (await clients.call(name, tool, arguments)).structuredContent


def message(key, *, kind="note", conversation="ongoing-guidance"):
    return {
        "recipient": "codex",
        "conversation_id": conversation,
        "idempotency_key": key,
        "body": "Apply this additional whiteboard instruction at the next checkpoint.",
        "kind": kind,
        "dispatch": False,
        "request_reply": False,
    }


@pytest.mark.parametrize(
    "state,evidence,route",
    [
        ("failed", {}, "managed_receiver"),
        ("failed", {"phase": "managed_receiver"}, "managed_receiver"),
        ("blocked", {"phase": "direct_admission"}, "failed_visible_admission"),
        ("unknown", {"phase": "direct_admission"}, "managed_receiver"),
        ("completed", {"phase": "direct_admission"}, "managed_receiver"),
        ("queued", {"phase": "direct_admission"}, "pending_visible_terminal"),
        (
            "failed",
            {"phase": "direct_admission", "session_scope": "existing_visible_terminal"},
            "existing_visible_terminal",
        ),
    ],
)
def test_route_annotation_uses_persisted_failure_without_changing_history(
    working_channel, state, evidence, route
):
    bridge, _, _ = working_channel
    sent = bridge.messages.send("chatgpt", MessageSend(**message("route-evidence")))
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state,evidence) VALUES(?,?,?)",
        (sent["id"], state, json.dumps(evidence)),
    )
    before = list(bridge.store.db.iterdump())
    result = bridge.messages.get("chatgpt", sent["id"])
    assert result["processing_route"] == route
    assert result["processing"]["state"] == state
    assert result["processing"]["evidence"] == evidence
    assert list(bridge.store.db.iterdump()) == before


@pytest.mark.parametrize("kind", ["work", "question"])
async def test_busy_work_is_held_without_input_or_automatic_inbox_delivery(
    working_channel, http_bridge, kind
):
    bridge, transport, admissions = working_channel
    _, endpoint = http_bridge
    request = message("busy-" + kind, kind=kind)
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        sent = await call(clients, "chatgpt", "message_send", {"message": request})
        identifier = sent["id"]
        assert sent["error"]["code"] == "visible_target_working"
        assert sent["processing_route"] == "failed_visible_admission"
        job = sent["processing"]
        assert job["state"] == "failed" and job["run_id"] is None
        assert job["claimed"] is None and job["started"] is None
        assert job["evidence"] == {
            "automatic_retry": False,
            "phase": "direct_admission",
            "reason": "visible_target_working",
            "terminal_input_attempted": False,
            "observation": {
                "state": "working",
                "ready": False,
                "reason": "current_progress_row",
                "input_empty": True,
                "target": "codex",
            },
        }
        assert sent["delivered"] is sent["receipt"] is sent["acknowledged"] is None
        hold = bridge.store.db.execute(
            "SELECT actor,reason FROM queue_holds WHERE queue_id='messages' AND item_id=?",
            (identifier,),
        ).fetchone()
        assert tuple(hold) == ("chatgpt", "direct_admission_rejected")
        assert len(admissions) == 1 and transport["calls"] == []

        # Repeating the same sender key reads the original outcome, never retries it.
        repeated = await call(clients, "chatgpt", "message_send", {"message": request})
        assert repeated["id"] == identifier and repeated["processing"] == job
        for reader in ("chatgpt", "codex"):
            stored = await call(clients, reader, "message_get", {"message_id": identifier})
            assert stored["body"] == request["body"] and stored["processing"] == job
            assert stored["processing_route"] == "failed_visible_admission"
        inbox = await call(
            clients,
            "codex",
            "message_receive",
            {"conversation_id": request["conversation_id"], "after": 0},
        )
        assert inbox["messages"] == []
        history = await call(
            clients,
            "codex",
            "conversation_get",
            {"conversation_id": request["conversation_id"]},
        )
        assert [entry["id"] for entry in history["messages"]] == [identifier]
        assert history["messages"][0]["processing"] == job
        assert len(admissions) == 1 and transport["calls"] == []
        assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 0


async def test_explicit_inbox_note_has_stable_receipt_until_recipient_ack(
    working_channel, http_bridge
):
    bridge, transport, admissions = working_channel
    _, endpoint = http_bridge
    request = message("new-checkpoint-guidance")
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        sent = await call(clients, "chatgpt", "message_send", {"message": request})
        unrelated = await call(
            clients,
            "chatgpt",
            "message_send",
            {"message": message("other-channel", conversation="other-channel")},
        )
        assert sent["processing"] is None
        assert sent["processing_route"] == "external_client_inbox"
        assert sent["delivered"] is sent["acknowledged"] is None
        assert admissions == [] and transport["calls"] == []
        assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0
        assert bridge.store.db.execute("SELECT count(*) FROM queue_holds").fetchone()[0] == 0
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0

        arguments = {"conversation_id": request["conversation_id"], "after": 0}
        received = await call(clients, "codex", "message_receive", arguments)
        entry = received["messages"][0]
        assert [item["id"] for item in received["messages"]] == [sent["id"]]
        assert entry["receipt"] and entry["delivered"] and entry["acknowledged"] is None
        repeated = await call(clients, "codex", "message_receive", arguments)
        assert repeated["messages"][0]["receipt"] == entry["receipt"]
        assert repeated["messages"][0]["id"] == entry["id"]
        retry = await call(clients, "chatgpt", "message_send", {"message": request})
        assert retry["id"] == sent["id"] and retry["receipt"] == entry["receipt"]
        pending_other = await call(
            clients, "chatgpt", "message_get", {"message_id": unrelated["id"]}
        )
        assert pending_other["delivered"] is None

        ack_args = {"message_id": sent["id"], "receipt": entry["receipt"]}
        for wrong_identity in ("chatgpt", "foreign"):
            denied = await call(clients, wrong_identity, "message_ack", ack_args)
            assert "error" in denied
        wrong_receipt = await call(
            clients, "codex", "message_ack", {**ack_args, "receipt": "foreign-receipt"}
        )
        assert "error" in wrong_receipt
        still_pending = await call(clients, "codex", "message_receive", arguments)
        assert still_pending["messages"][0]["receipt"] == entry["receipt"]

        # The cooperating consumer applies/deduplicates by ID before acknowledging.
        applied_ids = set()
        applied_bodies = []
        for delivery in (received, repeated, still_pending):
            for incoming in delivery["messages"]:
                if incoming["id"] not in applied_ids:
                    applied_bodies.append(incoming["body"])
                    applied_ids.add(incoming["id"])
        assert applied_bodies == [request["body"]]
        ack = await call(clients, "codex", "message_ack", ack_args)
        duplicate_ack = await call(clients, "codex", "message_ack", ack_args)
        assert ack["acknowledged"] == duplicate_ack["acknowledged"]
        assert (await call(clients, "codex", "message_receive", arguments))["messages"] == []
        assert admissions == [] and transport["calls"] == []
        assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM message_events WHERE message_id=? "
                "AND kind='message.acknowledged'",
                (sent["id"],),
            ).fetchone()[0]
            == 1
        )
