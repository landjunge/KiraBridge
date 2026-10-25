"""Historical accepted conversations remain answerable after direct-delivery migration."""

# ruff: noqa: F811
import pytest
from test_visible_dispatch_wait import archive_request, enqueue
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import ReceiverConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend


def test_full_conversation_only_allows_one_final_reply_per_accepted_request(visible):
    bridge, _ = visible
    bridge.config.messaging.max_conversation_messages = 2
    bridge.config.messaging.receivers["codex"] = ReceiverConfig(
        cwd=bridge.config.principals["codex"].roots[0], timeout=3
    )
    requests = []
    for n in range(2):
        requests.append(
            bridge.messages._send(
                "chatgpt",
                MessageSend(
                    recipient="codex",
                    conversation_id="bounded-replies",
                    idempotency_key=f"request-{n}",
                    kind="question",
                    dispatch=False,
                    body="Question",
                ),
                visible_internal=True,
            )
        )
    for n, request in enumerate(requests):
        reply = MessageSend(
            recipient="chatgpt",
            conversation_id="bounded-replies",
            idempotency_key=f"reply-{n}",
            kind="answer",
            dispatch=False,
            reply_to=request["id"],
            body="Answer",
        )
        result = bridge.messages._send("codex", reply, visible_internal=True)
        assert bridge.messages._send("codex", reply, visible_internal=True)["id"] == result["id"]
        with pytest.raises(BridgeError, match="message limit"):
            bridge.messages._send(
                "codex",
                reply.model_copy(update={"idempotency_key": f"extra-{n}"}),
                visible_internal=True,
            )
        with pytest.raises(BridgeError, match="message limit"):
            bridge.messages._send(
                "codex",
                reply.model_copy(update={"idempotency_key": f"note-{n}", "kind": "note"}),
                visible_internal=True,
            )
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
    with pytest.raises(BridgeError, match="message limit"):
        bridge.messages._send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id="bounded-replies",
                idempotency_key="new-work",
                kind="question",
                dispatch=False,
                body="More work",
            ),
            visible_internal=True,
        )


async def test_final_reply_at_limit_releases_the_visible_reservation(visible):
    from test_visible_preinput import LocalRecipientPool

    bridge, transport = visible
    bridge.config.messaging.max_conversation_messages = 2
    note = bridge.messages._send(
        "chatgpt",
        MessageSend(
            recipient="grok",
            conversation_id="full-visible",
            idempotency_key="initial-note",
            body="Earlier context",
            kind="note",
            dispatch=False,
        ),
        visible_internal=True,
    )
    delivered = bridge.messages.receive("grok")["messages"][0]
    bridge.messages.ack("grok", note["id"], delivered["receipt"])
    sent = enqueue(bridge, key="full-visible")
    message, run_id = bridge.message_receiver._claim(sent["id"])
    await bridge.message_receiver._process(LocalRecipientPool(bridge, "grok"), message, run_id)
    completed = bridge.messages.get("chatgpt", sent["id"])["processing"]
    assert completed["state"] == "completed" and completed["reply_id"]
    assert bridge.visible_handoffs.status("chatgpt", run_id)["state"] == "completed"
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert transport["calls"] == ["insert", "return"]


def test_accepted_request_leaves_capacity_for_its_answer(visible):
    bridge, _ = visible
    conversation = "audit-full-conversation"
    for position in range(bridge.config.messaging.max_conversation_messages - 1):
        bridge.messages._send(
            "chatgpt",
            MessageSend(
                recipient="codex",
                conversation_id=conversation,
                idempotency_key=f"audit-note-{position}",
                body="Synthetic note",
                kind="note",
                request_reply=False,
                dispatch=False,
            ),
            visible_internal=True,
        )
    sent = archive_request(bridge, target="codex", key=conversation)
    assert sent["request_reply"]
    incoming = bridge.messages.receive("codex", after=sent["seq"] - 1)["messages"][0]
    bridge.messages.ack("codex", sent["id"], incoming["receipt"])
    try:
        bridge.messages._send(
            "codex",
            MessageSend(
                recipient="chatgpt",
                conversation_id=conversation,
                idempotency_key="audit-final-answer",
                reply_to=sent["id"],
                body="The requested result",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
            visible_internal=True,
        )
    except BridgeError as exc:
        pytest.fail(
            f"Accepted request at position {sent['position']} cannot be answered: {exc.code}"
        )
