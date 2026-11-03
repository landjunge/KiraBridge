"""The current busy Codex composer must not be confused with submitted history."""

# Imported fixtures are used through pytest's dependency injection.
# ruff: noqa: F811

import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError


@pytest.mark.parametrize("pending", [False, True])
async def test_queue_widget_refuses_without_input_reservation_or_fallback(visible, pending):
    bridge, transport = visible
    transport["target"] = "codex"
    binding = bridge.config.visible_handoffs.bindings["codex"]
    binding.ready_pattern = r"(?m)^›(?: Ask Codex to do anything)?\s*$"
    transport["text"] = (
        "› old submitted request\n\n◦ Working (4s • esc to interrupt)\n\n» "
        + ("preserve pending input" if pending else "Ask Codex to do anything")
        + "\nGPT-6.1-Sol high · ~\n← for agents · ? for shortcuts\n"
    )
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.execute(
            {"id": "current-queue-widget", "principal": "chatgpt"},
            AgentInput(agent="codex", prompt="New work must not be queued", cwd="/tmp"),
            callback,
            callback,
        )
    assert error.value.code == ("visible_input_not_empty" if pending else "visible_target_working")
    assert not transport["calls"]
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 0
