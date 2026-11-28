"""Captured Qwen Code 0.28.6 terminal shape and exact literal-input proof."""

from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.cli_adapters import adapter_for
from kirabridge.literal_session_input import insertion_observed
from kirabridge.visible_readiness import assess, input_view

BINDING = SimpleNamespace(ready_pattern="Type your request", busy_pattern="esc to cancel")
DIVIDER = "─" * 118
PLACEHOLDER = "  Type your request, or /usage"


def frame(field=PLACEHOLDER, *, previous="", prompt="> "):
    visible = field.replace("\n", "\n  ")
    return (
        f"{previous}{DIVIDER}\n{prompt}{visible}\n{DIVIDER}\n"
        "  ➜ qwen · qwen3.8-flash medium\n  Auto-Modus (Shift + Tab zum Wechseln)\n\n\n"
    )


def test_real_qwen_empty_widget_is_registered_and_ready():
    visible = frame(previous="  ●︎ Qwen Code-Update verfügbar! 0.28.6 → 0.29.0\n\n")
    result = assess("qwen", visible, BINDING)
    assert result["ready"] and result["input_empty"]
    assert result["allowed_actions"] == ["insert", "submit"]
    assert adapter_for("qwen").capabilities.text
    assert input_view("qwen", visible).startswith(DIVIDER)


@pytest.mark.parametrize(
    "raw",
    [
        frame("a visible draft"),
        frame("Type your request, or /usage"),  # Typed text without placeholder indentation.
        frame(prompt="! "),
        frame(prompt="* "),
        frame() + "Restart now? (y/N)\n",
        "\x1b[H" + frame(),
        frame().replace("Auto-Modus", "Shell-Modus"),
        frame().replace(f"\n{DIVIDER}\n  ➜", "\n  ➜"),
    ],
)
def test_qwen_drafts_dialogs_and_unrecognized_frames_are_not_ready(raw):
    result = assess("qwen", raw, BINDING)
    assert not result["ready"] and not result["input_empty"]


@pytest.mark.parametrize("activity", ["⠋ Working (1s)", " (Esc zum Abbrechen)"])
def test_qwen_busy_is_distinct_from_empty_widget(activity):
    result = assess("qwen", frame(previous=activity + "\n"), BINDING)
    assert result["input_empty"] and not result["ready"]
    assert result["state"] == "working"


def test_only_exact_current_input_counts_as_qwen_paste_evidence():
    original = frame(previous="a literal probe in history\n\n")
    payload = "a literal probe\n  zweite Zeile"
    after = frame(payload)
    assert insertion_observed("qwen", after, payload, original)
    assert not insertion_observed("qwen", original, "a literal probe", original)
    assert not insertion_observed("qwen", after, payload.replace("  zwei", " zwei"), original)
    assert not insertion_observed("qwen", after.replace("medium", "high"), payload, original)
    assert not insertion_observed("qwen", after, payload, frame("other draft"))
    assert not insertion_observed("qwen", frame(PLACEHOLDER), PLACEHOLDER, original)
    assert not insertion_observed("qwen", frame(payload, previous="⠋ Working\n"), payload, original)


@pytest.mark.parametrize("payload", ["x" * 1001, "x\n" * 10, "[Pasted Content 1001 chars]"])
async def test_hidden_qwen_payload_is_rejected_before_input(payload):
    adapter = adapter_for("qwen")
    with pytest.raises(BridgeError, match="cannot verify the exact payload"):
        await adapter.preflight_input(None, BINDING, payload, {"text": frame()})
    folded = frame("[Pasted Content 1001 chars]")
    assert not insertion_observed("qwen", folded, payload, frame())
    assert not adapter.return_readiness(folded, BINDING)["ready"]
