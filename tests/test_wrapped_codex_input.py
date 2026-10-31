"""Wrapped single logical lines keep exact words, geometry and Return ownership."""

# ruff: noqa: F811
import json
import shutil
import subprocess

import pytest
from conftest import request
from test_literal_session_input import literal_visible  # noqa: F401
from test_session_return import key_visible  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.literal_session_input import insertion_observed, single_line_renderings
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

PAYLOAD = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
WRAPPED = "alpha beta gamma delta\n  epsilon zeta eta theta iota\n  kappa lambda mu"
FOOTER = "\n \n  GPT-6.1-Sol high · ~\n"
BEFORE = "› Ask Codex to do anything" + FOOTER + "  ← for agents · ? for shortcuts\n"
AFTER = "› " + WRAPPED + FOOTER


def test_whole_current_wrapped_widget_requires_bound_columns():
    assert not insertion_observed("codex", AFTER, PAYLOAD, BEFORE)
    assert insertion_observed("codex", AFTER, PAYLOAD, BEFORE, columns=31)
    assert not insertion_observed("codex", AFTER, PAYLOAD, BEFORE, columns=80)


def test_exact_blank_payload_row_uses_only_the_known_terminal_padding_cell():
    payload = "first\n\nlastword"
    after = "› first\n \n  lastword" + FOOTER
    assert insertion_observed("codex", after, payload, BEFORE)
    assert not insertion_observed("codex", after, "first\n \nlastword", BEFORE)
    assert not insertion_observed("codex", after.replace("\n \n", "\n \n \n", 1), payload, BEFORE)


@pytest.mark.parametrize(
    "altered",
    [
        AFTER.replace("lambda", "LAMbda"),
        AFTER.replace("beta gamma", "beta  gamma"),
        AFTER.replace("delta\n  epsilon", "del\n  ta epsilon"),
        AFTER.replace("lambda mu", "lambda"),
        AFTER.replace("lambda mu", "lambda mu EXTRA"),
        AFTER + "Approval required\n",
        AFTER.replace("GPT-6.1-Sol", "GPT-other"),
        "› " + PAYLOAD + "\n› unrelated" + FOOTER,
    ],
)
def test_changed_payload_chrome_or_history_never_passes(altered):
    assert not insertion_observed("codex", altered, PAYLOAD, BEFORE, columns=31)


@pytest.mark.parametrize(
    "payload",
    [
        "a\nb",
        "a\tb",
        "a  b",
        " a b",
        "a b ",
        "a 😀 b",
        "a e\u0301 b",
        "a\u200bb",
        "x" * 80,
        "a " * 501,
    ],
)
def test_ambiguous_or_unsupported_text_is_not_whitespace_normalized(payload):
    assert single_line_renderings(payload, 31) == []


@pytest.mark.parametrize("target,expected", [(None, False), ("codex", True)])
def test_native_echo_can_observe_codex_wrap_but_shell_stays_strict(target, expected):
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    source = TerminalAppTransport.native_paste_observation(PAYLOAD, target=target)
    source += "process.stdout.write(JSON.stringify([observedPaste(" + json.dumps(BEFORE)
    source += "," + json.dumps(AFTER) + "),observedPaste(" + json.dumps(AFTER)
    source += "," + json.dumps(AFTER) + ")]));"
    result = subprocess.run([node, "-e", source], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [expected, False]


def test_native_echo_keeps_a_final_word_shared_with_the_old_placeholder():
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    source = TerminalAppTransport.native_paste_observation(
        "Please explain anything", target="codex"
    )
    before = "› Ask Codex to do anything\n\nGPT-model"
    after = "› Please explain anything\n\nGPT-model"
    historical = "› Please explain anything\n\nold output\n› wrong\n\nGPT-model"
    source += "process.stdout.write(JSON.stringify([observedPaste(" + json.dumps(before)
    source += "," + json.dumps(after) + "),observedPaste(" + json.dumps(before)
    source += "," + json.dumps(historical) + ")]));"
    result = subprocess.run([node, "-e", source], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [True, False]


def test_native_echo_preserves_blank_payload_lines_and_ignores_model_footer():
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    source = TerminalAppTransport.native_paste_observation("first\n\nlastword", target="codex")
    before = "› \n\nGPT-model"
    after = "› first\n  \n  lastword\n\nGPT-model"
    wrong = "› wrong\n\nGPT-model · lastword"
    source += "process.stdout.write(JSON.stringify([observedPaste(" + json.dumps(before)
    source += "," + json.dumps(after) + "),observedPaste(" + json.dumps(before)
    source += "," + json.dumps(wrong) + ")]));"
    result = subprocess.run([node, "-e", source], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [True, False]


@pytest.mark.parametrize("wrong", [False, True])
async def test_literal_wrapped_input_sends_exactly_one_return_only_for_full_match(
    literal_visible, monkeypatch, wrong
):
    bridge, transport, row = literal_visible
    transport["text"] = "› " + FOOTER + "  ← for agents · ? for shortcuts\n"

    async def insert(pane, text, **guards):
        assert text == PAYLOAD and guards["agent_target"] == "codex"
        transport["literal_calls"].append(("paste", text))
        transport["text"] = AFTER.replace("lambda", "wrong") if wrong else AFTER

    async def columns(pane, **guards):
        assert guards["expected_screen"] == transport["text"]
        assert guards["identity_guard"][901].endswith("/bin/codex")
        return 31

    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", columns)
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": PAYLOAD},
        task_id="wrapped-literal",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        if wrong:
            assert task["state"] == "unknown"
            assert transport["literal_calls"] == [("paste", PAYLOAD)]
        else:
            assert task["state"] == "completed", task
            assert task["result"]["return_sent"] is True
            assert transport["literal_calls"] == [("paste", PAYLOAD), ("return", None)]
            assert bridge.submit("chatgpt", value, "")["result"] == task["result"]
        assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()


@pytest.mark.parametrize(
    "screen,safe",
    [
        (AFTER, True),
        ("› first\n \n  lastword" + FOOTER, True),
        ("› draft\n  Approval required\n \n  detail" + FOOTER, False),
        ("› draft\n  • Working (2s • esc to interrupt)\n \n  detail" + FOOTER, False),
        ("› draft\n  tab to queue message\n \n  detail" + FOOTER, False),
        (AFTER.replace("  epsilon", "epsilon"), False),
        (AFTER.replace(" \n  GPT", "\nUnknown dialog\n  GPT"), False),
        (AFTER.replace("  kappa lambda mu", "  Approval required"), False),
        ("• Working (12s • esc to interrupt)\n" + AFTER, False),
    ],
)
async def test_explicit_return_for_observed_wrapped_draft_keeps_busy_and_dialog_guards(
    key_visible, screen, safe
):
    bridge, transport, _, observed = key_visible
    args = await observed(screen)
    if safe:
        result = await bridge.execute(
            {
                "id": "wrapped-enter",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
        assert result["return_sent"] and not result["paste_event_sent"]
        assert transport["literal_calls"] == [("return", None)]
    else:
        from kirabridge.bridge_core.models import BridgeError

        with pytest.raises(BridgeError):
            await bridge.execute(
                {
                    "id": "unsafe-wrapped-enter",
                    "principal": "chatgpt",
                    "operation": "session.input",
                    "args": args,
                },
                callback,
                callback,
            )
        assert not transport["literal_calls"]
