"""Characterize the two RC38 UI refusals without native input."""

from types import SimpleNamespace

from kirabridge.session_return import return_readiness
from kirabridge.visible_readiness import assess

BINDING = SimpleNamespace(
    ready_pattern=r"(?m)^\s*›(?: Ask Codex to do anything)?\s*$",
    busy_pattern=r"Working…|esc to interrupt|Back to bottom|enter/esc latest",
)
COPY = (
    "› Ask Codex to do anything\n\n  GPT-6.1-Sol xhigh · ~\n"
    "  ⌃c copy · enter copy & follow · esc clear\n"
)
SCROLL = (
    "↓ Back to bottom · esc\n\n› Existing draft\n  continues here\n\n"
    "  GPT-6.1-Sol xhigh · ~\n  esc latest                            ⚠ 1 warning · f2 to view\n"
)


def test_copy_mode_is_distinct_from_an_unknown_dialog_and_not_return_ready():
    assert assess("codex", COPY, BINDING)["ui_state"] == "copy"
    assert not return_readiness("codex", COPY, BINDING)["ready"]


def test_known_scroll_requires_navigation_not_unconditional_return():
    result = return_readiness("codex", SCROLL, BINDING)
    assert not result["ready"]
    assert result["ui_state"] == "transcript"
    assert result["allowed_actions"] == ["return_to_input"]


def test_model_looking_payload_cannot_authorize_a_different_dialog_footer():
    raw = (
        "↓ Back to bottom · esc\n\n› draft\n  GPT-6.1-Sol xhigh · ~\n\n"
        "  Approval required\n  esc latest\n"
    )
    result = assess("codex", raw, BINDING)
    assert not result["ready"]
    assert "return_to_input" not in result.get("allowed_actions", [])


def test_known_model_picker_has_exit_only_not_a_submit_or_permission_action():
    from test_cli_navigation_m1 import MODEL_MENU

    from kirabridge.cli_adapters import adapter_for

    adapter = adapter_for("codex")
    result = adapter.observe(MODEL_MENU, BINDING)
    assert result["ui_state"] == "model_menu"
    assert result["allowed_actions"] == ["return_to_input"]
    assert not adapter.return_readiness(MODEL_MENU, BINDING)["ready"]
    for raw in (
        MODEL_MENU + "Approval required\n",
        MODEL_MENU.replace("esc back", "esc approve"),
        MODEL_MENU.replace("2. GPT-6-Astra", "2. Unknown-provider"),
        "• Working (2s • esc to interrupt)\n" + MODEL_MENU,
    ):
        assert "return_to_input" not in adapter.observe(raw, BINDING).get("allowed_actions", [])
    assert "return_to_input" not in adapter.observe(MODEL_MENU, BINDING, {"state": "working"}).get(
        "allowed_actions", []
    )


def test_status_evidence_requires_fresh_actual_cli_output_not_scroll_history():
    from kirabridge.cli_adapters import adapter_for

    adapter = adapter_for("codex")
    footer = "› Ask Codex to do anything\n\n  GPT-6.1-Sol xhigh · ~\n"
    transcript = (
        "/status\n\n  >_ OpenAI Codex (v0.166.0)\n"
        "  Model: GPT-6.1-Sol (reasoning xhigh)\n  Model provider: openai\n"
        "  Directory: ~/owned\n  Permissions: Read Only (never)\n  Session: fixture\n\n"
    )
    result = adapter.command_result("/status", footer, transcript + footer, BINDING)
    assert result["acceptance_evidence"] == "status_output" and result["ready_to_input"]
    assert not result["response_observed"]
    assert not adapter.command_result("/status", transcript + footer, transcript + footer, BINDING)[
        "acceptance_observed"
    ]
    assert not adapter.command_result(
        "/status", footer, transcript.replace("Permissions:", "Other:") + footer, BINDING
    )["acceptance_observed"]


def test_complete_wrapped_or_indented_slash_draft_cannot_bypass_adapter_rules():
    from kirabridge.cli_adapters import adapter_for

    adapter = adapter_for("codex")
    for raw in (
        "› /model\n  GPT-6-Astra\n\n  GPT-6.1-Sol xhigh · ~\n",
        "  › /permissions\n\n  GPT-6.1-Sol xhigh · ~\n",
        "› /status\n  --other\n\n  GPT-6.1-Sol xhigh · ~\n",
    ):
        assert not adapter.return_readiness(raw, BINDING)["ready"]
    grok = adapter_for("grok")
    assert grok.allows_text("/status", True) and grok.allows_text("/help", True)
    assert not grok.command_result("/status", "", "", BINDING)["acceptance_observed"]


def test_unknown_bound_protocol_never_authorizes_navigation():
    from test_cli_navigation_m1 import MODEL_MENU

    from kirabridge.cli_adapters import adapter_for

    adapter = adapter_for("codex")
    for protocol in ({}, {"state": "unknown"}, {"state": "working"}):
        for raw in (COPY, SCROLL, MODEL_MENU):
            result = adapter.observe(raw, BINDING, protocol)
            assert "return_to_input" not in result.get("allowed_actions", [])
