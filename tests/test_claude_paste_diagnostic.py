"""Content-free diagnostic for an unconfirmed Claude paste (M4 long-message case).

The live run had visible_paste_unconfirmed before Return and no post-paste frame.
The verdict logic is unchanged; only lengths/booleans of the last evaluation are
kept so the next failure is classifiable (absent frame, empty, partial, mismatch,
folded marker) without anyone reading the terminal. No text is ever recorded.
"""

# ruff: noqa: F811
import json
import shutil
import subprocess

import pytest
from test_claude_visible_adapter import EMPTY, screen
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.cli_adapters import adapter_for
from kirabridge.platform_adapters.terminal_app import paste_observation

TEXT = "P2 Abnahme: TextEdit neues Dokument und Terminal-Uebergabe bitte bestaetigen."
FULL = screen(
    ["❯ P2 Abnahme: TextEdit neues Dokument und", "  Terminal-Uebergabe bitte bestaetigen."]
)
PARTIAL = screen(["❯ P2 Abnahme: TextEdit neues"])


def replay(text, before, after):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node required for isolated JavaScript echo replay")
    source = adapter_for("claude").paste_source(text)
    source += "const verdict=observedPaste(" + json.dumps(before) + "," + json.dumps(after) + ");"
    source += "process.stdout.write(JSON.stringify([verdict,__pasteDiag]));"
    done = subprocess.run([node, "-"], input=source, capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_confirmed_echo_verdict_is_unchanged_and_diag_shows_full_match():
    verdict, diag = replay(TEXT, EMPTY, FULL)
    assert verdict is True
    assert diag["before_field"] == 0 and diag["common_prefix"] == diag["expected"]
    assert diag["after_rows"] == 2 and diag["tail_changed"] is True


@pytest.mark.parametrize(
    ("after", "expect"),
    [
        (EMPTY, {"after_field": 0, "tail_changed": False}),  # paste never rendered
        ("plain shell $ ", {"after_field": -1}),  # composer frame not recognized
        (PARTIAL, {"marker": False}),  # rendered only partly within the window
        (screen(["❯ [Pasted text #1 +3 lines]"]), {"marker": True}),  # wrong fold count
    ],
)
def test_unconfirmed_shapes_are_distinguishable_without_text(after, expect):
    verdict, diag = replay(TEXT, EMPTY, after)
    assert verdict is False
    for key, value in expect.items():
        assert diag[key] == value
    if after == PARTIAL:
        assert 0 < diag["common_prefix"] == diag["after_field"] < diag["expected"]
    rendered = json.dumps(diag)
    assert "Abnahme" not in rendered and "Terminal" not in rendered  # never content


def test_existing_draft_still_refuses_and_is_reported():
    verdict, diag = replay(TEXT, screen(["❯ user draft"]), FULL)
    assert verdict is False and diag["before_field"] > 0


def valid():
    return {
        "before_field": 0,
        "after_field": 12,
        "expected": 70,
        "common_prefix": 12,
        "after_rows": 1,
        "tail_delta": 14,
        "tail_changed": True,
        "marker": False,
    }


def test_parser_keeps_only_exact_numeric_facts():
    detail = "execution error: Error: Paste not observed; no Return sent; diag=%s (-2700)"
    assert paste_observation(detail % json.dumps(valid())) == valid()
    assert paste_observation("Error: Paste not observed; no Return sent (-2700)") is None
    for broken in (
        {**valid(), "after_field": "secret text"},
        {**valid(), "extra": 1},
        {k: v for k, v in valid().items() if k != "marker"},
        {**valid(), "marker": 1},
        {**valid(), "tail_delta": True},
    ):
        assert paste_observation(detail % json.dumps(broken)) is None


async def test_unconfirmed_paste_stays_unknown_with_observation_and_no_return(visible, monkeypatch):
    bridge, transport = visible

    async def unconfirmed(principal, args, *, before_transport=None):
        await before_transport()  # the effect boundary was crossed (AXPress sent)
        error = BridgeError("visible_paste_unconfirmed", "Paste not observed; no Return sent")
        error.provider_error = {"paste_observation": valid()}
        raise error

    monkeypatch.setattr(bridge.sessions, "insert", unconfirmed)
    task = {"id": "long-unconfirmed", "principal": "chatgpt"}
    args = AgentInput(agent="grok", prompt="A longer body " * 20, cwd="/tmp")
    with pytest.raises(UncertainExecution) as error:
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert error.value.code == "visible_handoff_unknown"
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert status["state"] == "unknown"
    assert status["evidence"]["reason"] == "visible_paste_unconfirmed"
    assert status["evidence"]["paste_observation"] == valid()
    assert status["evidence"]["automatic_retry"] is False
    assert "return" not in transport["calls"]
    # Never replayed: the same task stays uncertain without new input.
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert "return" not in transport["calls"]
