"""Replay the exact RC39 transcript toolbar, including its shortcuts hint."""

from types import SimpleNamespace

import pytest

from kirabridge.cli_adapters import adapter_for

BINDING = SimpleNamespace(
    ready_pattern=r"(?m)^\s*›(?: Ask Codex to do anything)?\s*$",
    busy_pattern=r"esc to interrupt|Thinking…|Back to bottom|enter/esc latest",
)


def frame(footer):
    return (
        "New activity · ↓ Back to bottom · esc\n\n"
        "› Ask Codex to do anything\n \n"
        "  GPT-6.1-Sol xhigh · ~ · Example · Main [default]\n  " + footer + "\n"
    )


@pytest.mark.parametrize("badge", ["", "    ⚠ 1 warning · f2 to view"])
def test_exact_activity_shortcuts_allows_bound_idle_composer(badge):
    state = adapter_for("codex").observe(
        frame("New activity · enter/esc latest · ? shortcuts" + badge),
        BINDING,
        {"state": "idle"},
    )
    assert state["ready"] and state["input_empty"]


@pytest.mark.parametrize("protocol", [{"state": "working"}, {"state": "unknown"}])
def test_shortcuts_never_overrides_bound_activity(protocol):
    assert not adapter_for("codex").observe(
        frame("New activity · enter/esc latest · ? shortcuts"),
        BINDING,
        protocol,
    )["ready"]


@pytest.mark.parametrize("suffix", [" · approve", "\n  Approval required", " · ? shortcuts"])
def test_only_complete_known_toolbar_is_accepted(suffix):
    assert not adapter_for("codex").observe(
        frame("New activity · enter/esc latest · ? shortcuts" + suffix),
        BINDING,
        {"state": "idle"},
    )["ready"]
