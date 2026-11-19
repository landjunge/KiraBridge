"""Claude Code visible composer (RC45 capture layout); no terminal, window or input."""

import asyncio
import json
import shutil
import subprocess

import pytest

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


def run_echo(text, before, after):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node required for isolated JavaScript echo replay")
    source = adapter_for("claude").paste_source(text)
    source += "process.stdout.write(JSON.stringify(observedPaste("
    source += json.dumps(before) + "," + json.dumps(after) + ")));"
    done = subprocess.run([node, "-"], input=source, capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def history_screen(rows, history):
    return "\n".join([*history, RULE + " Big Plan Koordination ─", *rows, RULE, "  ⏵⏵ auto mode"])


def test_same_text_earlier_in_history_is_still_confirmed():
    """'ok' sent twice: the older 'ok' above the composer must not hide the new paste."""
    history = ["❯ ok", "⏺ Alles klar, weiter.", "ok ok weiter"]
    before = history_screen(["❯ "], history)
    after = history_screen(["❯ ok"], history)
    assert run_echo("ok", before, after) is True
    assert adapter_for("claude").insertion_observed(after, "ok", before)
    assert run_echo("ok", before, before) is False
    # Pending input before the paste is never accepted as an echo.
    assert run_echo("ok", after, after) is False
    assert run_echo("ok", before, history_screen(["❯ okay then"], history)) is False


def test_long_multiline_paste_shown_folded_is_confirmed_only_for_matching_lines():
    adapter = adapter_for("claude")
    text = "\n".join(f"Zeile {number}" for number in range(1, 31))
    for count in (29, 30):  # newline count, or line count
        folded = screen([f"❯ [Pasted text #1 +{count} lines]"])
        assert run_echo(text, EMPTY, folded) is True
        assert adapter.insertion_observed(folded, text, EMPTY)
    wrong = screen(["❯ [Pasted text #1 +12 lines]"])
    assert run_echo(text, EMPTY, wrong) is False
    assert not adapter.insertion_observed(wrong, text, EMPTY)
    folded = screen(["❯ [Pasted text #1 +29 lines]"])
    # Not empty before, or other text beside the marker: never evidence.
    assert run_echo(text, screen(["❯ draft"]), folded) is False
    assert run_echo(text, EMPTY, screen(["❯ x [Pasted text #1 +29 lines]"])) is False
