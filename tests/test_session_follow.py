import asyncio
import re

import pytest
from pydantic import ValidationError

from kirabridge.mcp_gateway.server import inline_task_timeout
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.read_query import ReadQuery
from kirabridge.session_manager import SessionRead, follow_screen


def test_follow_reports_new_text_without_replacing_the_screen():
    assert follow_screen(None, "screen", since="") == {"follow": "full"}
    cursor = "ab" * 32
    assert follow_screen(None, "screen", since=cursor) == {"follow": "reset"}
    assert follow_screen("screen", "screen", since=cursor) == {
        "follow": "unchanged",
        "appended": "",
    }
    assert follow_screen("screen", "screen\nmore", since=cursor) == {
        "follow": "append",
        "appended": "\nmore",
    }
    assert follow_screen("other", "screen", since=cursor) == {"follow": "reset"}
    head = "stable head of the captured terminal screen"
    previous = head + "\nold prompt %"
    screen = head + "\necho more\nmore\nnew prompt %"
    followed = follow_screen(previous, screen, since=cursor)
    assert followed["follow"] == "append"
    assert followed["appended"].startswith("echo more")


def test_session_read_waits_longer_than_the_query_budget_and_other_work_does_not():
    assert inline_task_timeout("session.read") == 9
    assert inline_task_timeout("session.catalog") == 9
    assert inline_task_timeout("clipboard.read") == 2
    assert inline_task_timeout("threaddesk.read") == 2
    assert inline_task_timeout("session.input") == 1
    assert inline_task_timeout("terminal.execute") == 1


def test_since_is_only_a_session_read_cursor():
    SessionRead(pane_id="terminal:1:ttys001", expected_pid=1, since="ab" * 32)
    with pytest.raises(ValidationError):
        SessionRead(pane_id="terminal:1:ttys001", expected_pid=1, since="not-a-cursor")
    with pytest.raises(ValidationError):
        ReadQuery(operation="file.read", path="/tmp/example", since="ab" * 32)


async def test_terminal_read_source_does_not_focus_or_type(monkeypatch):
    transport = TerminalAppTransport(asyncio.Lock())
    calls = []

    async def native(source, *, mutation=False):
        calls.append((source, mutation))
        return "observed buffer tail"

    monkeypatch.setattr(transport, "native", native)
    assert await transport.read("terminal:9:ttys009") == "observed buffer tail"
    assert len(calls) == 1
    source, mutation = calls[0]
    assert mutation is False
    assert "tab.history()" in source and ".slice(-65536)" in source
    assert not re.search(r"\.selected\s*=", source)
    for action in ("frontmost", "activate()", "keyCode", "keystroke", "doScript", ".click()"):
        assert action not in source


async def test_cursor_follows_one_pane_and_does_not_reveal_another(bridge):
    screen = {"text": "one"}

    async def selected(principal, pane, pid):
        return {"pane_id": pane, "expected_pid": pid}

    async def read(principal, pane, pid, max_bytes=65536):
        return {
            "pane_id": pane,
            "expected_pid": pid,
            "text": screen["text"],
            "scope": "test transport snapshot",
        }

    bridge.sessions.selected = selected
    bridge.sessions.read = read
    first = await bridge.sessions.read_observed("local", "terminal:9:ttys009", 9)
    assert first["follow"] == "full" and first["text"] == "one"
    cursor = first["next_cursor"]
    assert (
        bridge.outputs.captured_text("local", "session_capture", "terminal:9:ttys009:9", cursor)
        == "one"
    )
    assert (
        bridge.outputs.captured_text("other", "session_capture", "terminal:9:ttys009:9", cursor)
        is None
    )
    screen["text"] = "one\ntwo"
    second = await bridge.sessions.read_observed("local", "terminal:9:ttys009", 9, since=cursor)
    assert second["follow"] == "append" and second["appended"] == "\ntwo"
    assert second["text"] == "one\ntwo"
    third = await bridge.sessions.read_observed(
        "local", "terminal:9:ttys009", 9, since=second["next_cursor"]
    )
    assert third["follow"] == "unchanged" and third["appended"] == ""
    foreign = await bridge.sessions.read_observed("local", "terminal:8:ttys008", 8, since=cursor)
    assert foreign["follow"] == "reset" and "appended" not in foreign
    assert foreign["text"] == "one\ntwo"
