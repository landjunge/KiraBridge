"""Codex readiness without a bound protocol: history is not activity, placeholders are empty."""

import pytest

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.cli_adapters import adapter_for

BINDING = VisibleTerminalBinding(
    pane_id="terminal:1:ttys001",
    expected_pid=1,
    agent_pid=2,
    ready_pattern=r"^\s*›(?: Ask Codex to do anything)?\s*$",
    busy_pattern=r"\[stop\]|esc to interrupt|Thinking…",
)
FOOTER = "GPT-6.1-Sol high · ~\n← for agents · ? for shortcuts\n"


def observe(text):
    return adapter_for("codex").observe(text, BINDING)


def test_old_busy_words_far_above_an_empty_input_do_not_block_forever():
    old = "• Explanation: press esc to interrupt, [stop] or Thinking… as shown\n"
    history = old + "\n" + "\n".join(f"line {number}" for number in range(50)) + "\n\n"
    state = observe(history + "›\n" + FOOTER)
    assert state["ready"] and state["reason"] == "current_empty_widget"


def test_busy_words_in_the_block_directly_above_the_input_still_block():
    state = observe("old\n\nThinking… about it\n\n›\n" + FOOTER)
    assert not state["ready"] and state["reason"] == "unbound_ambiguous_activity_text"
    state = observe("old\n\n› \n" + FOOTER)
    assert state["ready"]


@pytest.mark.parametrize(
    "placeholder",
    [
        "Explain this codebase",
        "Find and fix a bug in @filename",
        "Write tests for @filename",
        "Summarize recent commits",
        "Implement {feature}",
        "Ask Codex to do anything",
    ],
)
def test_known_rotating_placeholder_counts_as_empty_input(placeholder):
    state = observe("• Done.\n\n› " + placeholder + "\n" + FOOTER)
    assert state["input_empty"] and state["ready"], state


@pytest.mark.parametrize("draft", ["Explain this codebase now", "Explain this", "Fix the bug"])
def test_unknown_or_extended_text_is_still_a_draft(draft):
    state = observe("• Done.\n\n› " + draft + "\n" + FOOTER)
    assert state["state"] == "input_not_empty" and not state["ready"]
