"""Input routing cannot turn a command or Return into generic approval."""

import pytest
from test_literal_session_input import literal_visible  # noqa: F401
from test_session_return import RESUME_MENU, key_visible  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_input_router import execute, input_kind
from kirabridge.session_manager import SessionInput


@pytest.mark.parametrize(
    "text,kind",
    [
        ("normal prompt", "literal_text"),
        ("/resume", "slash_command"),
        ("/help more", "slash_command"),
        ("/approvals", "slash_command"),
        ("/tmp/file", "literal_text"),
        (" /resume", "literal_text"),
        ("A quoted /resume", "literal_text"),
    ],
)
def test_classification_preserves_literal_text_and_does_not_execute_commands(text, kind):
    args = SessionInput(pane_id="terminal:1:ttys001", expected_pid=42, text=text)
    assert input_kind(args) == kind


@pytest.mark.parametrize(
    "text,kind", [("normal prompt", "literal_text"), ("/resume", "slash_command")]
)
async def test_text_and_slash_use_the_same_exactly_once_guarded_transport(
    literal_visible,  # noqa: F811
    text,
    kind,
):
    bridge, transport, row = literal_visible
    target, binding = bridge.sessions.explicit_agent_binding(row)
    args = SessionInput(pane_id=row["pane_id"], expected_pid=900, text=text)
    result = await execute(
        bridge,
        {"id": "router-text", "principal": "chatgpt"},
        args,
        target,
        binding,
        callback,
        callback,
    )
    assert result["input_kind"] == kind and result["return_sent"] is True
    assert transport["literal_calls"] == [("paste", text), ("return", None)]
    assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
    assert not bridge.store.db.execute("SELECT 1 FROM approvals").fetchone()


async def test_known_menu_confirmation_routes_one_observed_key_without_paste(key_visible):  # noqa: F811
    bridge, transport, _, observed = key_visible
    args = SessionInput(**await observed(RESUME_MENU))
    result = await execute(
        bridge,
        {"id": "router-menu", "principal": "chatgpt"},
        args,
        None,
        None,
        callback,
        callback,
    )
    assert result["input_kind"] == "menu_confirmation"
    assert transport["literal_calls"] == [("return", None)]
    assert not bridge.store.db.execute("SELECT 1 FROM approvals").fetchone()


@pytest.mark.parametrize(
    "heading",
    [
        "Approval required",
        "Would you like to run the following command?",
        "Would you like to make the following edits?",
        "Do you want to allow this action?",
    ],
)
async def test_permission_confirmation_is_not_an_ordinary_draft_or_menu(
    key_visible,  # noqa: F811
    heading,
):
    bridge, transport, _, observed = key_visible
    # Even a dialog imitating a normal composer/footer cannot use this Return route.
    screen = heading + "\n› Yes, proceed\n  GPT-6.1-Sol max · ~\n"
    args = SessionInput(**await observed(screen))
    with pytest.raises(BridgeError):
        await execute(
            bridge,
            {"id": "router-deny-approval", "principal": "chatgpt"},
            args,
            None,
            None,
            callback,
            callback,
        )
    assert transport["literal_calls"] == []
    assert not bridge.store.db.execute("SELECT 1 FROM approvals").fetchone()
