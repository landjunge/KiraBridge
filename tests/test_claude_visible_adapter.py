"""Claude Code visible composer (RC45 capture layout); no terminal, window or input."""

import asyncio

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.cli_adapters import adapter_for
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

BINDING = VisibleTerminalBinding(
    pane_id="terminal:8514:ttys000",
    expected_pid=850,
    agent_pid=891,
    ready_pattern="❯",
    busy_pattern="esc to interrupt",
)
RULE = "─" * 60


def screen(rows, status="✻ Waiting for 3 background agents to finish"):
    return "\n".join(
        [
            "⏺ Earlier answer mentioning esc to interrupt in quoted output.",
            "",
            status,
            "                                  ✔ Update installed · Restart to update",
            RULE + " Big Plan Koordination ─",
            *rows,
            RULE,
            "  ⏵⏵ auto mode on · PR #123 · 2 shells · ↓ to manage",
        ]
    )


EMPTY = screen(["❯ " + " " * 40])


def test_registered_and_ready_on_empty_composer():
    adapter = adapter_for("claude")
    assert adapter.capabilities.text and adapter.allows_text("hello", True)
    state = adapter.observe(EMPTY, BINDING)
    assert state["ready"] and state["reason"] == "current_empty_widget"
    assert state["allowed_actions"] == ["insert", "submit"]


def test_working_pending_input_and_unknown_frames_fail_closed():
    adapter = adapter_for("claude")
    working = screen(["❯ "], status="✻ Thinking… (12s · esc to interrupt)")
    assert adapter.observe(working, BINDING)["state"] == "working"
    pending = adapter.observe(screen(["❯ draft"]), BINDING)
    assert pending["state"] == "input_not_empty" and not pending["ready"]
    assert adapter.observe("plain shell $ ", BINDING)["reason"] == "prompt_not_found"
    assert adapter.observe(EMPTY + "\x07", BINDING)["reason"] == "unsupported_control_sequence"


def test_wrapped_insertion_verified_without_whitespace_and_collapsed_paste_refused():
    adapter = adapter_for("claude")
    text = "P2 Abnahme: TextEdit neues Dokument und Terminal-Uebergabe bitte bestaetigen."
    wrapped = screen(
        ["❯ P2 Abnahme: TextEdit neues Dokument und", "  Terminal-Uebergabe bitte bestaetigen."]
    )
    assert adapter.insertion_observed(wrapped, text, EMPTY)
    assert not adapter.insertion_observed(wrapped, text + " extra", EMPTY)
    assert not adapter.insertion_observed(wrapped, text, wrapped)  # not empty before
    collapsed = screen(["❯ [Pasted text #1 +12 lines]"])
    assert not adapter.insertion_observed(collapsed, text, EMPTY)


def test_native_echo_check_uses_whitespace_free_claude_source():
    source = TerminalAppTransport.native_paste_observation("a b", target="claude")
    assert "observedPaste" in source and "\\u00a0" in source
    assert asyncio.run(adapter_for("claude").preflight_input(None, BINDING, "x", {})) is None
