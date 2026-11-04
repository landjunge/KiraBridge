"""Pure parser replay of the reported RC39 footer; never post native input."""

from types import SimpleNamespace

import pytest

from kirabridge.cli_adapters import adapter_for
from kirabridge.visible_readiness import codex_input_footer

BINDING = SimpleNamespace(
    ready_pattern=r"(?m)^\s*›(?: Ask Codex to do anything)?\s*$",
    busy_pattern=r"Working…|esc to interrupt|Back to bottom|enter/esc latest",
)
COPY = "⌃c copy · enter copy & follow · esc clear"
ACTIVITY_COPY = "New activity · " + COPY


def frame(toolbar, prompt="› Ask Codex to do anything"):
    return prompt + "\n\n  GPT-6.1-Sol xhigh · ~\n  " + toolbar + "\n"


@pytest.mark.parametrize("toolbar", [COPY, ACTIVITY_COPY])
def test_complete_copy_toolbar_is_navigation_only_in_empty_composer(toolbar):
    adapter = adapter_for("codex")
    raw = frame(toolbar)
    state = adapter.observe(raw, BINDING)
    assert state["ui_state"] == "copy", state
    assert state["input_empty"] is True and state["ready"] is False
    assert state["work_state"] == "unknown"
    assert state["allowed_actions"] == ["return_to_input"]
    assert adapter.return_readiness(raw, BINDING) == state
    # The common footer parser must never accept Return's copy/follow controls.
    assert not codex_input_footer(toolbar)


@pytest.mark.parametrize("protocol", [{}, {"state": "working"}, {"state": "unknown"}])
def test_copy_activity_never_overrides_unknown_or_active_bound_work(protocol):
    state = adapter_for("codex").observe(frame(ACTIVITY_COPY), BINDING, protocol)
    assert "return_to_input" not in state.get("allowed_actions", [])


@pytest.mark.parametrize(
    "raw",
    [
        frame(ACTIVITY_COPY, "› somebody else's draft"),
        frame(ACTIVITY_COPY, "» Ask Codex to do anything"),
        "• Working (2s • esc to interrupt)\n\n" + frame(ACTIVITY_COPY),
        "Approval required\n\n" + frame(ACTIVITY_COPY),
        frame("Approval required\n  " + ACTIVITY_COPY),
        frame("Some warning · " + COPY),
        frame("New activity · " + COPY + " · approve"),
        frame("New activity  · " + COPY),
        frame("New activity · enter approve · esc clear"),
        frame(ACTIVITY_COPY + "\n  Unknown dialog"),
    ],
)
def test_copy_activity_keeps_draft_work_dialog_and_exact_toolbar_guards(raw):
    state = adapter_for("codex").observe(raw, BINDING)
    assert not state["ready"]
    assert "return_to_input" not in state.get("allowed_actions", [])
