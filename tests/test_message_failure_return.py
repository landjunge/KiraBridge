import asyncio

import pytest
from test_grok_conversation import configure

from kirabridge.grok_connector.conversation import message_for_conversation
from kirabridge.message_manager import MessageSend


@pytest.mark.parametrize("state", ["failed", "unknown", "blocked", "cancelled"])
async def test_terminal_message_failure_finishes_without_polling_or_an_agent_reply(
    bridge, config, monkeypatch, state
):
    configure(config, monkeypatch)
    policy = config.principals["grok_app"]
    policy.capabilities += ["message.send", "message.read", "message.ack"]
    policy.message_peers = ["codex"]
    config.principals["codex"] = policy.model_copy(deep=True)
    config.principals["codex"].message_peers = ["grok_app"]
    message = bridge.messages.send(
        "grok_app",
        MessageSend(
            recipient="codex",
            conversation_id="terminal-error",
            idempotency_key="once",
            body="A failed transport is not an agent answer",
            request_reply=True,
            dispatch=False,
        ),
    )
    with bridge.store.transaction():
        bridge.store.db.execute(
            "INSERT INTO message_jobs(message_id,state) VALUES(?,'queued')", (message["id"],)
        )
        bridge.message_receiver._finish(
            message["id"],
            state,
            {"no_input_replayed": True},
            error="delivery_retired_unresolved" if state == "blocked" else "test_transport_failure",
        )
    # The old blocked/cancelled branch waited 18 seconds and then falsely
    # returned non-final. No actual agent or terminal transport is invoked here.
    async with asyncio.timeout(0.2):
        result = await message_for_conversation(
            bridge, "grok_app", bridge.messages.get("grok_app", message["id"])
        )
    returned = result["conversation_return"]
    assert returned["final"] and not returned["continue_required"]
    assert returned["scope"] == "message_processing" and returned["next_call"] is None
    assert returned["audio_playback"] == "not_observed_by_bridge"
    assert result["reply_message"] is None and result["acknowledged"] is None
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    if state == "blocked":
        assert "früherer Ausgang bleibt unbestätigt" in returned["text"]
