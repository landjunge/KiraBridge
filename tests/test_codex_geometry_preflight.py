"""Refuse known unprovable cursor rows before handing any text to Terminal."""

# ruff: noqa: F811
from unittest.mock import AsyncMock

import pytest
from test_literal_session_input import literal_visible  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.literal_session_input import codex_wrapped_renderings, insertion_observed

SHORT_ROW = "abc " * 31 + "abc"
FULL_ROW = "abc " * 31 + "abcd"
LONG_LINE = "abc " * 95 + "abcd"
PAYLOAD = "Reply with MARKER.\n" + LONG_LINE
FOOTER = "\n \n  GPT-Test high · owned workspace\n"
BEFORE = "› " + FOOTER


@pytest.mark.parametrize("route", ["literal", "handoff"])
async def test_full_logical_row_is_refused_before_any_paste(literal_visible, monkeypatch, route):
    bridge, transport, row = literal_visible
    transport["text"] = BEFORE
    _, binding = bridge.sessions.explicit_agent_binding(row)
    bridge.config.visible_handoffs.bindings["codex"] = binding

    async def columns(pane, **guards):
        assert pane == row["pane_id"]
        assert guards["expected_screen"] == transport["text"]
        assert guards["identity_guard"][901].endswith("/bin/codex")
        return 131

    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    running = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        if route == "literal":
            await bridge.execute(
                {
                    "id": "refuse-full-literal",
                    "principal": "chatgpt",
                    "operation": "session.input",
                    "args": {
                        "pane_id": row["pane_id"],
                        "expected_pid": row["expected_pid"],
                        "text": PAYLOAD,
                    },
                },
                running,
                callback,
            )
        else:
            await bridge.visible_handoffs.execute(
                {"id": "refuse-full-handoff", "principal": "chatgpt"},
                AgentInput(agent="codex", prompt=PAYLOAD, cwd="/tmp", wait_for_reply=False),
                running,
                callback,
            )

    assert failure.value.code == "visible_input_geometry_ambiguous"
    assert not isinstance(failure.value, UncertainExecution)
    assert transport["literal_calls"] == []
    assert transport["text"] == BEFORE
    running.assert_not_awaited()
    assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
    assert not bridge.store.db.execute("SELECT 1 FROM visible_handoffs").fetchone()


@pytest.mark.parametrize("route", ["literal", "handoff"])
async def test_supported_geometry_preserves_one_exact_paste_and_return(
    literal_visible, monkeypatch, route
):
    bridge, transport, row = literal_visible
    transport["text"] = BEFORE
    _, binding = bridge.sessions.explicit_agent_binding(row)
    bridge.config.visible_handoffs.bindings["codex"] = binding

    async def columns(pane, **guards):
        assert guards["expected_screen"] == transport["text"]
        return 130

    async def insert(pane, text, **guards):
        transport["literal_calls"].append(("paste", text))
        transport["text"] = "› " + codex_wrapped_renderings(text, 130)[0] + FOOTER

    async def press_return(pane, **guards):
        assert guards["expected_screen"] == transport["text"]
        transport["literal_calls"].append(("return", None))
        transport["text"] = BEFORE

    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", press_return)
    if route == "literal":
        result = await bridge.execute(
            {
                "id": "safe-geometry-literal",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": {
                    "pane_id": row["pane_id"],
                    "expected_pid": row["expected_pid"],
                    "text": PAYLOAD,
                },
            },
            callback,
            callback,
        )
        assert result["return_sent"] is True
    else:
        result = await bridge.visible_handoffs.execute(
            {"id": "safe-geometry-handoff", "principal": "chatgpt"},
            AgentInput(agent="codex", prompt=PAYLOAD, cwd="/tmp", wait_for_reply=False),
            callback,
            callback,
        )
        assert result["success"] is True
    assert transport["literal_calls"] == [("paste", PAYLOAD), ("return", None)]


@pytest.mark.parametrize("route", ["literal", "handoff"])
async def test_collapsed_paste_keeps_its_existing_verifier(literal_visible, monkeypatch, route):
    bridge, transport, row = literal_visible
    transport["text"] = BEFORE
    payload = "abc " * 300 + "tail"
    _, binding = bridge.sessions.explicit_agent_binding(row)
    bridge.config.visible_handoffs.bindings["codex"] = binding
    columns = AsyncMock(side_effect=AssertionError("Collapsed paste needs no wrap geometry"))

    async def insert(pane, text, **guards):
        transport["literal_calls"].append(("paste", text))
        transport["text"] = f"› [Pasted Content {len(text)} chars]" + FOOTER

    async def press_return(pane, **guards):
        transport["literal_calls"].append(("return", None))
        transport["text"] = BEFORE

    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", press_return)
    if route == "literal":
        result = await bridge.execute(
            {
                "id": "collapsed-literal",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": {
                    "pane_id": row["pane_id"],
                    "expected_pid": row["expected_pid"],
                    "text": payload,
                },
            },
            callback,
            callback,
        )
        assert result["return_sent"] is True
    else:
        result = await bridge.visible_handoffs.execute(
            {"id": "collapsed-handoff", "principal": "chatgpt"},
            AgentInput(agent="codex", prompt=payload, cwd="/tmp", wait_for_reply=False),
            callback,
            callback,
        )
        assert result["success"] is True
    columns.assert_not_awaited()
    assert transport["literal_calls"] == [("paste", payload), ("return", None)]


async def test_explicit_paste_without_return_keeps_its_existing_contract(
    literal_visible, monkeypatch
):
    bridge, transport, row = literal_visible
    transport["text"] = BEFORE
    columns = AsyncMock(side_effect=AssertionError("No automatic Return to preflight"))
    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    result = await bridge.execute(
        {
            "id": "draft-only",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": {
                "pane_id": row["pane_id"],
                "expected_pid": row["expected_pid"],
                "text": PAYLOAD,
                "submit": False,
            },
        },
        callback,
        callback,
    )
    columns.assert_not_awaited()
    assert result["return_sent"] is False
    assert transport["literal_calls"] == [("paste", PAYLOAD)]


@pytest.mark.parametrize(
    "text,columns,expected",
    [
        (PAYLOAD, 131, (128,)),
        (PAYLOAD, 130, ()),
        ("Reply.\n" + "abc " * 95 + "abc", 131, (127,)),
        (FULL_ROW, 131, (128,)),
        (FULL_ROW + "\ntail", 131, (128,)),
        (FULL_ROW + "\n", 131, (128,)),
        ("x" * 128, 131, (128,)),
        ("x" * 1001, 131, ()),
        ("a\tb", 131, ()),
        ("a—b\n" + FULL_ROW, 131, ()),
        ("alpha-beta\n" + FULL_ROW, 131, ()),
        (PAYLOAD, None, ()),
        (PAYLOAD, True, ()),
    ],
)
def test_preflight_marks_only_supported_full_logical_line_ends(text, columns, expected):
    from kirabridge.literal_session_input import codex_full_row_widths

    assert codex_full_row_widths(text, columns) == expected


@pytest.mark.parametrize("extra", ["", " ", "\n ", "\n  "])
def test_cursor_row_and_additional_spaces_or_newlines_do_not_gain_verification(extra):
    painted = "Reply with MARKER.\n  " + SHORT_ROW + "\n  " + SHORT_ROW + "\n  " + FULL_ROW
    assert not insertion_observed(
        "codex", "› " + painted + "\n " + extra + FOOTER, PAYLOAD, BEFORE, columns=131
    )
