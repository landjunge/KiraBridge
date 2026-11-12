"""OpenCode 1.4.4 composer semantics; captured text only, no native UI."""

from types import SimpleNamespace

import pytest

from kirabridge.cli_adapters import adapter_for
from kirabridge.cli_adapters.opencode import OpenCodeAdapter, composer

BINDING = SimpleNamespace(busy_pattern=r"\[stop\]|esc to interrupt|Thinking…|Working…")
PROMPT = 'Ask anything... "What is the tech stack of this project?"'


def frame(content):
    """The left-bordered composer captured from OpenCode 1.4.4 on 12.11.2026."""
    return (
        "previous conversation\n"
        "                       ┃\n"
        "                       ┃  " + content + "\n"
        "                       ┃\n"
        "                       ┃  Build  Big Pickle OpenCode\n"
        "                       ╹" + "▀" * 76 + "\n"
        "                                          tab agents  ctrl+p commands\n"
    )


EMPTY = frame(PROMPT)
TYPED = frame("hello probe")


def observe(raw, binding=BINDING):
    return adapter_for("opencode").observe(raw, binding)


def test_registry_contains_opencode_program_semantics():
    adapter = adapter_for("opencode")
    assert isinstance(adapter, OpenCodeAdapter)
    assert adapter.capabilities.text


def test_captured_empty_placeholder_is_ready_and_typed_text_blocks():
    empty = observe(EMPTY)
    assert empty["state"] == "ready" and empty["input_empty"] and empty["ready"]
    typed = observe(TYPED)
    assert typed["state"] == "input_not_empty" and not typed["input_empty"]
    assert typed["reason"] == "existing_input_must_not_be_overwritten"


@pytest.mark.parametrize(
    "placeholder",
    [
        "Ask anything...",
        'Ask anything... "Fix broken tests"',
        'Ask anything... "Explain how authentication works"',
        'Ask anything... "How do environment variables work here?"',
    ],
)
def test_documented_empty_placeholders_are_recognized(placeholder):
    result = observe(frame(placeholder))
    assert result["state"] == "ready" and result["input_empty"]


@pytest.mark.parametrize(
    "typed",
    [
        'Ask anything... "a user typed this exact sentence"',
        "Ask anything... trailing",
        "hello probe",
    ],
)
def test_unknown_or_real_text_is_never_accepted_as_empty(typed):
    result = observe(frame(typed))
    assert result["state"] == "input_not_empty"
    assert not result["input_empty"]


def test_shell_mode_is_unknown_not_an_empty_prompt_composer():
    result = observe(frame('Run a command... "ls -la"'))
    assert result["state"] == "unknown" and not result["input_empty"]
    assert result["reason"] == "opencode_shell_mode"


def test_incomplete_or_ambiguous_frame_stays_unknown():
    for raw in (
        "no composer here",
        '┃  Ask anything... "Fix broken tests"\n',
        '┃\n┃  Ask anything... "Fix broken tests"\n┃\n',
    ):
        result = observe(raw)
        assert result["state"] == "unknown" and not result["input_empty"]
        assert result["reason"] == "prompt_not_found"


def test_input_view_is_only_the_last_composer():
    view = adapter_for("opencode").input_view(EMPTY)
    assert view.lstrip().startswith("┃")
    assert PROMPT in view and "previous conversation" not in view
    assert composer(EMPTY) is not None


def test_exact_insertion_is_observed_and_a_changed_draft_is_not():
    adapter = adapter_for("opencode")
    assert adapter.insertion_observed(TYPED, "hello probe", EMPTY)
    assert not adapter.insertion_observed(TYPED, "hello probe!", EMPTY)
    assert not adapter.insertion_observed(frame("hello probe"), "hello probe", TYPED)


def test_return_is_ready_only_for_a_current_nonempty_composer():
    adapter = adapter_for("opencode")
    ready = adapter.return_readiness(TYPED, BINDING)
    assert ready["ready"] and ready["reason"] == "current_nonempty_composer"
    assert not adapter.return_readiness(EMPTY, BINDING)["ready"]
    assert adapter.return_readiness("no composer", BINDING)["reason"] == "prompt_not_found"


def test_busy_status_row_blocks_an_empty_composer():
    raw = frame(PROMPT).replace(
        "previous conversation\n",
        "previous conversation\n⠋ Working… esc to interrupt\n",
    )
    result = observe(raw)
    assert result["state"] == "working" and not result["ready"]
