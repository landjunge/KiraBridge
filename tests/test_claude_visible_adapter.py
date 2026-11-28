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


def screen_with_standing_footer_hint(rows, status="✻ Waiting for 3 background agents to finish"):
    """Current Claude Code releases show a standing "esc to interrupt" keybinding
    hint in the footer at ALL times (idle or not) -- unlike the RC45-era `screen()`
    fixture above, whose footer never carried that phrase. Live-found 2026-11-28:
    matching binding.busy_pattern (default includes "esc to interrupt") against
    this footer made KiraBridge see every idle, empty composer as "working"
    forever, so a message addressed to this session was never delivered."""
    return "\n".join(
        [
            "⏺ Earlier answer.",
            "",
            status,
            RULE,
            *rows,
            RULE,
            "  ⏵⏵ auto mode on · 1 shell · esc to interrupt · ← 2 agents · ↓ to manage",
        ]
    )


def test_ready_on_empty_composer_despite_standing_esc_to_interrupt_footer_hint():
    """Regression test for the 2026-11-28 message-wakeup finding: a standing
    footer hint must never be read as "busy" on its own. Busy is decided only
    by the actual live spinner/elapsed-time line, which this idle fixture has
    none of."""
    adapter = adapter_for("claude")
    idle = screen_with_standing_footer_hint(["❯ " + " " * 40])
    state = adapter.observe(idle, BINDING)
    assert state["ready"] and state["state"] == "ready"
    assert state["reason"] == "current_empty_widget"


def test_still_working_with_standing_footer_hint_when_the_live_spinner_is_present():
    """The footer-exclusion fix must not weaken real busy detection: an actual
    live spinner line still means "working", footer hint or not."""
    adapter = adapter_for("claude")
    working = screen_with_standing_footer_hint(["❯ "], status="✳ Galloping… (45s · ↓ 3.0k tokens)")
    assert adapter.observe(working, BINDING)["state"] == "working"


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


def test_spinner_with_todo_list_and_hints_before_the_input_is_still_working():
    adapter = adapter_for("claude")
    rows = [
        "✻ Pondering… (34s · ↓ 1.2k tokens)",
        "  ⎿ ☐ Erste Aufgabe",
        "    ☐ Zweite Aufgabe",
        "    ☒ Dritte Aufgabe",
        "",
        "❯ ",
    ]
    text = "\n".join(
        ["⏺ Earlier answer", "", *rows[:-2], "", RULE + " Big Plan ─", rows[-1], RULE, "  ⏵⏵ auto"]
    )
    state = adapter.observe(text, BINDING)
    assert state["state"] == "working" and not state["ready"]
    # The same layout without a live spinner (finished todo list) is ready.
    idle = text.replace("✻ Pondering… (34s · ↓ 1.2k tokens)", "  Klar")
    assert adapter.observe(idle, BINDING)["ready"]


def test_local_alias_resolves_to_claude_adapter_everywhere():
    """The coordinator principal `local` drives the Claude TUI (same table as process_is)."""
    from kirabridge.session_manager import PROCESS_ALIASES, process_is
    from kirabridge.visible_readiness import assess, input_view

    assert adapter_for("local") is adapter_for("claude")
    assert process_is({"name": "claude"}, "local")
    assert PROCESS_ALIASES["local"] == "claude"
    state = assess("local", EMPTY, BINDING)  # visible_readiness.py:18
    assert state["ready"] and state["reason"] == "current_empty_widget"
    assert input_view("local", EMPTY) == input_view("claude", EMPTY)
    # visible_handoff.py:849 uses adapter_for(target).protocol_state(binding, observer)
    assert asyncio.run(adapter_for("local").protocol_state(BINDING, None)) is None
    assert adapter_for("nope").observe("", BINDING)["reason"] == "unsupported_cli_program"
