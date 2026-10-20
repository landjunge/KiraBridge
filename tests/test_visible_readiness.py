"""Readiness must use the current widget and separately trusted turn evidence."""

from types import SimpleNamespace

import pytest

from kirabridge.visible_readiness import assess

FOOTER = "\n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts\n"
EMPTY = "› Ask Codex to do anything"
WORKING = "◦ Working (14m 26s • esc to interrupt)"


@pytest.fixture
def binding():
    return SimpleNamespace(
        ready_pattern=r"(?m)^\s*›(?: Ask Codex to do anything)?\s*$",
        busy_pattern=(
            r"\[stop\]|esc to interrupt|Thinking…|Working…|Back to bottom|enter/esc latest"
        ),
    )


def checked(text, binding, protocol=None):
    value = assess("codex", text, binding, protocol)
    assert value["state"] in {"ready", "working", "input_not_empty", "scrolled", "unknown"}
    assert value["ready"] == (value["state"] == "ready")
    assert isinstance(value["input_empty"], bool)
    assert value["reason"]
    return value


@pytest.mark.parametrize("protocol", [None, {"state": "idle"}])
async def test_clean_finished_screen_and_known_current_footer_are_ready(binding, protocol):
    text = "• Die Antwort ist fertig.\n\n" + EMPTY + FOOTER
    result = checked(text, binding, protocol)
    assert result["state"] == "ready" and result["input_empty"]


@pytest.mark.parametrize(
    "history",
    [
        "• Working (2s • esc to interrupt)\n\n• Fertige Antwort.",
        "• Working…\n\n• Die Arbeit ist abgeschlossen.",
        '• Dokumentation: "esc to interrupt" ist ein Hinweis, kein Arbeitsauftrag.',
        "> ◦ Working (2s • esc to interrupt)\n\n• Dieses Zitat gehört zur Erklärung.",
        "• Der alte Test hieß Thinking… und [stop].\n\n• Fertig.",
    ],
)
def test_bound_idle_ignores_work_words_in_history_or_quotations(binding, history):
    result = checked(history + "\n\n" + EMPTY + FOOTER, binding, {"state": "idle"})
    assert result["state"] == "ready" and result["protocol_state"] == "idle"


@pytest.mark.parametrize("protocol", [None, {"state": "unknown"}])
def test_history_without_reliable_idle_evidence_does_not_prove_ready(binding, protocol):
    text = "• Working (2s • esc to interrupt)\n\n• Angeblich fertig.\n\n" + EMPTY + FOOTER
    assert checked(text, binding, protocol)["state"] == "unknown"


def test_real_working_turn_is_blocked_even_with_empty_visible_widget(binding):
    text = WORKING + "\n  └ Tip: Press ⌃t to open the full transcript.\n\n" + EMPTY + FOOTER
    result = checked(text, binding, {"state": "working"})
    assert result["state"] == "working" and result["input_empty"]
    assert result["protocol_state"] == "working"


def test_actual_progress_row_without_protocol_blocks_before_empty_widget(binding):
    result = checked(WORKING + "\n\n" + EMPTY + FOOTER, binding)
    assert result["state"] == "working"


def test_idle_record_cannot_override_a_current_rendered_progress_row(binding):
    # A fresh visible renderer and a recorded lifecycle disagree: fail closed.
    result = checked(WORKING + "\n\n" + EMPTY + FOOTER, binding, {"state": "idle"})
    assert result["state"] in {"working", "unknown"}


@pytest.mark.parametrize("protocol", [{"state": "idle"}, {"state": "working"}])
def test_existing_q_input_is_never_ready_or_overwritten(binding, protocol):
    result = checked(WORKING + "\n\n› q\n\n  tab to queue message\n", binding, protocol)
    assert result["state"] == "input_not_empty" and not result["input_empty"]


@pytest.mark.parametrize("protocol", [None, {"state": "idle"}])
def test_empty_field_with_current_queue_hint_remains_busy(binding, protocol):
    result = checked(EMPTY + "\n  tab to queue message\n", binding, protocol)
    assert result["state"] == "working"


def test_unknown_bound_turn_cannot_be_promoted_by_empty_prompt(binding):
    result = checked(EMPTY + FOOTER, binding, {"state": "unknown"})
    assert result["state"] == "unknown" and result["protocol_state"] == "unknown"


@pytest.mark.parametrize("hint", ["Back to bottom", "enter/esc latest"])
@pytest.mark.parametrize("placement", ["before", "after"])
def test_current_scroll_controls_block_even_with_idle_protocol(binding, hint, placement):
    text = hint + "\n\n" + EMPTY + FOOTER if placement == "before" else EMPTY + FOOTER + hint
    assert checked(text, binding, {"state": "idle"})["state"] == "scrolled"


def test_old_scroll_quotation_does_not_poison_current_idle_widget(binding):
    text = '• Früher stand hier "Back to bottom".\n\n• Fertige Antwort.\n\n' + EMPTY + FOOTER
    assert checked(text, binding, {"state": "idle"})["state"] == "ready"


@pytest.mark.parametrize(
    "dialog", ["Unrecognized dialog", "Approval required", "A different CLI is active"]
)
def test_unrecognized_dialog_after_prompt_is_unknown_not_ready(binding, dialog):
    assert checked("›\n" + dialog, binding, {"state": "idle"})["state"] == "unknown"


@pytest.mark.parametrize("text", ["›", "›\n", "› Ask Codex to do anything\n"])
def test_minimal_explicit_test_transport_widget_is_supported(binding, text):
    assert checked(text, binding)["state"] == "ready"


def test_sgr_osc_hyperlink_and_crlf_are_presentation_only(binding):
    text = (
        "\x1b]8;;https://example.invalid\x1b\\\x1b[90m›\x1b[0m"
        "\x1b]8;;\x07 Ask Codex to do anything" + FOOTER
    ).replace("\n", "\r\n")
    result = checked(text, binding, {"state": "idle"})
    assert result["state"] == "ready"


@pytest.mark.parametrize("control", ["\x1b[2J", "\x1b[1A", "\r", "\x00", "\x08", "\x7f"])
def test_unsupported_controls_fail_closed_instead_of_erasing_evidence(binding, control):
    result = checked(control + EMPTY + FOOTER, binding, {"state": "idle"})
    assert result["state"] == "unknown"


@pytest.mark.parametrize("text", ["\u200b›", "›\u200b", "\uff1e", "❯", "\u00a0›"])
def test_unicode_changes_do_not_create_a_supported_codex_prompt(binding, text):
    result = checked(text + FOOTER, binding, {"state": "idle"})
    assert result["state"] in {"unknown", "input_not_empty"}


def test_an_old_empty_prompt_does_not_override_the_last_nonempty_widget(binding):
    text = "›\n\n• Alte Ausgabe.\n\n› noch nicht abgeschickter Auftrag" + FOOTER
    assert checked(text, binding, {"state": "idle"})["state"] == "input_not_empty"


def test_completed_subagent_is_not_a_completed_main_turn(binding):
    text = "• Completed `/root/readiness_audit`\n\n" + WORKING + "\n\n" + EMPTY + FOOTER
    assert checked(text, binding, {"state": "working"})["state"] == "working"
