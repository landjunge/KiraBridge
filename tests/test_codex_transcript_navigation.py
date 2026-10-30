"""Transcript navigation must not turn a live composer into a scrolled target."""

# Imported fixtures are resolved by pytest's dependency injection.
# ruff: noqa: F811

import pytest
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError

FOOTER = "\n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts\n"
NAVIGATION = "New activity · ↓ Back to bottom · esc\n\n"
EMPTY = "› Ask Codex to do anything"


def codex_screen(bridge, transport, text):
    bridge.config.visible_handoffs.bindings[
        "codex"
    ].ready_pattern = r"(?m)^\s*›(?: Ask Codex to do anything)?\s*$"
    transport["target"] = "codex"
    transport["text"] = text
    return bridge.config.visible_handoffs.bindings["codex"]


async def test_exact_binding_preflight_allows_navigation_and_reads_do_not_send_input(visible):
    bridge, transport = visible
    binding = codex_screen(
        bridge,
        transport,
        NAVIGATION + EMPTY + FOOTER + "New activity · enter/esc latest\n",
    )
    observed = await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert observed["text"] == transport["text"]
    assert not transport["calls"]
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


@pytest.mark.parametrize(
    "text,code",
    [
        (NAVIGATION + "› my draft" + FOOTER, "visible_input_not_empty"),
        (
            "◦ Working (2s • esc to interrupt)\n" + NAVIGATION + EMPTY + FOOTER,
            "visible_target_working",
        ),
        (NAVIGATION + "» Ask Codex to do anything" + FOOTER, "visible_target_working"),
        (NAVIGATION + EMPTY + "\nApprove execution?\n", "visible_target_unknown"),
        ("Back to bottom\n\n" + EMPTY + FOOTER, "visible_target_scrolled"),
    ],
)
async def test_binding_preflight_preserves_activity_draft_and_ambiguous_view_guards(
    visible, text, code
):
    bridge, transport = visible
    binding = codex_screen(bridge, transport, text)
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert exc.value.code == code
    assert not transport["calls"]
