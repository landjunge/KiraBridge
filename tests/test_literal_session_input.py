"""Literal terminal input must not become an addressed agent work message."""

import hashlib
import json

import pytest
from conftest import request
from test_visible_handoff import callback, visible  # noqa: F401
from test_visible_selection import new_native_selection, new_row

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.session_manager import SessionManager


@pytest.fixture
async def literal_visible(visible, config, monkeypatch):  # noqa: F811
    bridge, transport = visible
    config.session_input_policy.enabled = False
    row = new_row()
    await new_native_selection(bridge, monkeypatch, row)
    transport.update(target="codex", text="› ", literal_calls=[])

    async def read(pane):
        return transport["text"]

    async def insert(pane, text, **guards):
        assert guards["identity_guard"][901].endswith("/bin/codex")
        assert guards["expected_screen"] == transport["text"]
        transport["literal_calls"].append(("paste", text))
        transport["text"] = transport.get("prelude", "") + "› " + text + transport.get("footer", "")

    async def press_return(pane, **guards):
        assert guards["expected_screen"] == transport["text"]
        assert guards["identity_guard"][901].endswith("/bin/codex")
        transport["literal_calls"].append(("return", None))
        # /resume opens a picker; it does not start an agent or clear to a prompt.
        transport["text"] = "Resume a previous session\n› saved session\nEnter to resume"

    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", press_return)

    async def no_geometry(*args, **kwargs):
        return None

    monkeypatch.setattr(bridge.sessions.terminal_app, "input_columns", no_geometry)
    monkeypatch.setattr(bridge.sessions, "insert", SessionManager.insert.__get__(bridge.sessions))
    monkeypatch.setattr(
        bridge.sessions, "press_return", SessionManager.press_return.__get__(bridge.sessions)
    )
    return bridge, transport, row


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_resume_is_literal_one_shot_input_without_agent_work_or_ack(literal_visible, sender):
    bridge, transport, row = literal_visible
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": "/resume"},
        task_id="literal-resume",
    )
    default_binding = bridge.config.visible_handoffs.bindings["codex"].model_dump()
    async with bridge:
        bridge.prepare(sender, value)
        task = await bridge.tasks.wait(sender, value.task_id, timeout=5)
        assert task["state"] == "completed", task
        assert task["result"]["submitted"] is True
        assert task["result"]["return_sent"] is True
        assert task["result"]["agent_confirmed"] is False
        assert task["result"]["execution_confirmed"] is False
        assert bridge.submit(sender, value, "")["state"] == "completed"
        assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
        assert not bridge.store.db.execute("SELECT 1 FROM visible_handoffs").fetchone()
    assert transport["literal_calls"] == [("paste", "/resume"), ("return", None)]
    assert "Resume a previous session" in transport["text"]
    assert bridge.config.visible_handoffs.bindings["codex"].model_dump() == default_binding


@pytest.mark.parametrize("location", ["prelude", "footer", "both"])
async def test_resume_submits_from_live_prompt_with_transcript_navigation(
    literal_visible, location
):
    bridge, transport, row = literal_visible
    transport["prelude"] = (
        "New activity · ↓ Back to bottom · esc\n\n" if location in {"prelude", "both"} else ""
    )
    transport["footer"] = (
        "\n\nGPT-6.1-Sol max · ~\n← for agents · ? for shortcuts\nNew activity · enter/esc latest\n"
        if location in {"footer", "both"}
        else ""
    )
    transport["text"] = transport["prelude"] + "› " + transport["footer"]
    result = await bridge.execute(
        {
            "id": "combined-resume-navigation",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": {"pane_id": row["pane_id"], "expected_pid": 900, "text": "/resume"},
        },
        callback,
        callback,
    )
    assert result["submitted"] and result["return_sent"]
    assert transport["literal_calls"] == [("paste", "/resume"), ("return", None)]


@pytest.mark.parametrize(
    ("target", "screen", "payload", "expected"),
    [
        ("codex", "› Grüß dich 😀", "Grüß dich 😀", True),
        ("codex", "› First\n  Second", "First\nSecond", True),
        ("codex", "› [Pasted Content 12 chars]", "First\nSecond", True),
        ("codex", "› [Pasted Content 13 chars]", "First\nSecond", False),
        ("codex", "› /resume\nUNAUTHORIZED", "/resume", False),
        ("codex", "› /resume appended", "/resume", False),
        ("codex", "› /resume\n\nApprove dangerous action?", "/resume", False),
        ("codex", "› /resume\n\n› user's draft", "/resume", False),
        ("codex", "› /resume\x1b[2J", "/resume", False),
        ("codex", "» /resume", "/resume", False),
        ("grok", "╭\n│ ❯ /resume\n╰", "/resume", True),
        ("grok", "╭\n│ ❯ /resume  │\n╰─╯", "/resume", True),
        ("grok", "╭\n│ ❯ /resume appended\n╰", "/resume", False),
    ],
)
def test_literal_verification_requires_current_exact_payload(target, screen, payload, expected):
    from kirabridge.literal_session_input import insertion_observed

    before = "› " if target == "codex" else "╭\n│ ❯ │\n" + screen.splitlines()[-1]
    assert insertion_observed(target, screen, payload, before) is expected


@pytest.mark.parametrize("payload", ["/resume", "/resume\n"])
@pytest.mark.parametrize(
    "continuation",
    [
        "GPT-UNAUTHORIZED-CONTINUATION",
        "← for agents · ? for shortcuts",
        "New activity · enter/esc latest",
    ],
)
def test_footer_shaped_payload_edits_cannot_be_submitted(payload, continuation):
    from kirabridge.literal_session_input import insertion_observed

    footer = "\n\n  GPT-6.1-Sol max · ~\n  ← for agents · ? for shortcuts\n"
    before = "› " + footer
    assert insertion_observed("codex", "› " + payload + footer, payload, before)
    changed = "› " + payload + "\n  " + continuation + footer
    assert not insertion_observed("codex", changed, payload, before)


def test_native_resume_viewport_padding_does_not_hide_exact_payload():
    from kirabridge.literal_session_input import insertion_observed

    # Captured Codex 0.166.0 post-paste geometry; the controlled pre-state
    # varies only the empty composer and trailing viewport padding.
    footer = "\n \n  GPT-6.1-Sol max · /private/tmp/owned-resume/workspace\n"
    before = "› Ask Codex to do anything" + footer + "\n" * 17
    after = "› /resume  resume a saved chat\n \n› /resume" + footer + "\n" * 7
    assert insertion_observed("codex", after, "/resume", before)


@pytest.mark.parametrize("size", [1388, 1022])
def test_captured_collapsed_paste_hides_only_empty_composer_shortcut_row(size):
    from kirabridge.literal_session_input import insertion_observed

    # Captured terminal:6369 before 3a1d3b35 and after ff529772/041a8dc6.
    # Counts match the two failed task payloads; their footer hint disappears
    # while model, directory, thread title and workspace remain byte-identical.
    payload = ("Prüfe die Übergabe. " * size)[:size]
    footer = "\n \n  GPT-6.1-Sol high · ~ · Prüfe KiraBridge-Phasen 1 bis 3 · Main [default]"
    before = "› Ask Codex to do anything" + footer + "\n  ← for agents · ? for shortcuts\n"
    after = f"› [Pasted Content {size} chars]" + footer + "\n \n"
    assert insertion_observed("codex", after, payload, before)
    assert not insertion_observed("codex", after, payload + "X", before)


@pytest.mark.parametrize(
    "changed",
    [
        "\n \n  GPT-6.1-Sol high · MUTATED",
        "\n \n  GPT-6.1-Sol high · ~\n  UNAUTHORIZED",
        "\n  ← for agents · ? for shortcuts\n \n  GPT-6.1-Sol high · ~",
        "\n \n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts EXTRA",
        "\n \n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts\n  extra draft",
    ],
)
def test_hidden_composer_hint_does_not_discard_changed_footer_or_continuation(changed):
    from kirabridge.literal_session_input import insertion_observed

    before = "› \n \n  GPT-6.1-Sol high · ~\n  ← for agents · ? for shortcuts\n"
    assert not insertion_observed("codex", "› /resume" + changed, "/resume", before)


@pytest.mark.parametrize("hint", ["← for agents · ? for shortcuts EXTRA", "← for agents", "custom"])
def test_unknown_pre_paste_hint_cannot_disappear(hint):
    from kirabridge.literal_session_input import insertion_observed

    footer = "\n \n  GPT-6.1-Sol high · ~"
    before = "› " + footer + "\n  " + hint + "\n"
    assert not insertion_observed("codex", "› /resume" + footer, "/resume", before)


async def test_collapsed_paste_with_hidden_shortcuts_sends_exactly_one_return(
    literal_visible, monkeypatch
):
    bridge, transport, row = literal_visible
    footer = "\n \n  GPT-6.1-Sol high · ~"
    payload = "Prüfe diese tatsächliche Übergabe. " * 45
    transport["text"] = "› " + footer + "\n  ← for agents · ? for shortcuts\n"

    async def insert(pane, text, **guards):
        assert guards["expected_screen"] == transport["text"]
        transport["literal_calls"].append(("paste", text))
        transport["text"] = f"› [Pasted Content {len(text)} chars]" + footer + "\n \n"

    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": payload},
        task_id="collapsed-paste-shortcut-row",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        assert task["result"]["return_sent"] is True
        assert bridge.submit("chatgpt", value, "")["state"] == "completed"
        observations = [
            json.loads(event[0])
            for event in bridge.store.db.execute(
                "SELECT evidence FROM events WHERE task_id=?", (value.task_id,)
            )
        ]
        submitting = next(item for item in observations if item.get("phase") == "submitting")
        assert submitting["insertion_verified"] is True
        assert submitting["return_sent"] is False
        assert submitting["verification"] == {
            "verifier_version": "literal-widget-v3",
            "reason": "exact_widget_match",
            "before_screen_sha256": hashlib.sha256(
                ("› " + footer + "\n  ← for agents · ? for shortcuts\n").encode()
            ).hexdigest(),
            "after_screen_sha256": hashlib.sha256(
                (f"› [Pasted Content {len(payload)} chars]" + footer + "\n \n").encode()
            ).hexdigest(),
            "expected_payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "expected_payload_chars": len(payload),
        }
    assert transport["literal_calls"] == [("paste", payload), ("return", None)]


@pytest.mark.parametrize("continuation", ["\u00a0", "\u2003"])
def test_unicode_whitespace_continuation_is_not_viewport_padding(continuation):
    from kirabridge.literal_session_input import insertion_observed

    suffix = "\n \n  GPT-6.1-Sol max · owned workspace\n\n"
    before = "› " + suffix
    after = "› /resume" + suffix + continuation + "\n"
    assert not insertion_observed("codex", after, "/resume", before)


@pytest.mark.parametrize("badge", ["1 warning", "2 warnings"])
@pytest.mark.parametrize("display", ["hide", "show"])
def test_native_resume_warning_badge_can_change_on_the_same_model_footer(badge, display):
    from kirabridge.literal_session_input import insertion_observed

    # Exact inside-task Codex 0.166.0 before/after row geometry, with the owned
    # workspace path replaced. Slash completion hides the inline F2 badge.
    footer = "\n \n  GPT-6.1-Sol max · /private/tmp/owned-resume/workspace"
    badge_text = " " * 30 + "⚠ " + badge + " · f2 to view"
    before_badge, after_badge = (badge_text, "") if display == "hide" else ("", badge_text)
    before = "› Ask Codex to do anything" + footer + before_badge + "\n" * 14
    after = "› /resume  resume a saved chat\n \n› /resume" + footer + after_badge + "\n" * 13
    assert insertion_observed("codex", after, "/resume", before)


@pytest.mark.parametrize(
    "changed",
    [
        "\n \n  GPT-6.1-Sol max · MUTATED workspace",
        "\n \n  GPT-6.1-Sol max · owned workspace\n  ⚠ 1 warning · f2 to view",
        "\n \n  GPT-UNAUTHORIZED-CONTINUATION\n  GPT-6.1-Sol max · owned workspace",
        "\n \n  GPT-6.1-Sol max · owned workspace  ⚠ 1 warning · f2 to view EXECUTE",
        (
            "\n \n  GPT-6.1-Sol max · owned workspace"
            "  ⚠ 1 warning · f2 to view  ⚠ 2 warnings · f2 to view"
        ),
        "\n \n  GPT-6.1-Sol max · owned workspace\u00a0⚠ 1 warning · f2 to view",
        "\n \n  GPT-6.1-Sol max · owned workspace  ⚠ ١ warning · f2 to view",
    ],
)
def test_renderer_warning_normalization_preserves_changed_footer_or_payload(changed):
    from kirabridge.literal_session_input import insertion_observed

    before = "› \n \n  GPT-6.1-Sol max · owned workspace  ⚠ 1 warning · f2 to view\n\n"
    assert not insertion_observed("codex", "› /resume" + changed + "\n\n", "/resume", before)


@pytest.mark.parametrize("failure", ["changed", "paste", "return"])
async def test_literal_input_uncertainty_never_repeats_paste_or_return(
    literal_visible, monkeypatch, failure
):
    bridge, transport, row = literal_visible
    original_insert = bridge.sessions.terminal_app.insert
    original_return = bridge.sessions.terminal_app.press_return

    async def paste(pane, text, **guards):
        await original_insert(pane, text, **guards)
        if failure == "paste":
            raise UncertainExecution("visible_insert_unknown", "Paste outcome uncertain")
        if failure == "changed":
            transport["text"] += " UNAUTHORIZED"

    async def press_return(pane, **guards):
        await original_return(pane, **guards)
        raise UncertainExecution("visible_submit_unknown", "Return outcome uncertain")

    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", paste)
    if failure == "return":
        monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", press_return)
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": "/resume"},
        task_id="literal-uncertain",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "unknown", task
        assert task["evidence"]["safe_to_retry"] is False
        if failure == "changed":
            observation = task["evidence"]["last_observation"]
            assert observation["phase"] == "insertion_unverified"
            assert observation["insertion_verified"] is False
            assert observation["return_sent"] is False
            assert observation["verification"] == {
                "verifier_version": "codex-slash-widget-v1",
                "reason": "exact_widget_mismatch",
                "before_screen_sha256": hashlib.sha256("› ".encode()).hexdigest(),
                "after_screen_sha256": hashlib.sha256(
                    "› /resume UNAUTHORIZED".encode()
                ).hexdigest(),
                "expected_payload_sha256": hashlib.sha256(b"/resume").hexdigest(),
                "expected_payload_chars": len("/resume"),
            }
            serialized = json.dumps(observation["verification"])
            assert "/resume" not in serialized and "UNAUTHORIZED" not in serialized
        assert bridge.submit("chatgpt", value, "")["state"] == "unknown"
        assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
    from kirabridge.bridge_core.bridge import Bridge

    restarted = Bridge(bridge.config)
    try:
        restarted.store.recover()
        assert restarted.submit("chatgpt", value, "")["state"] == "unknown"
    finally:
        restarted.store.close()
    assert transport["literal_calls"] == [("paste", "/resume")] + (
        [("return", None)] if failure == "return" else []
    )


async def test_literal_input_refuses_existing_input_before_paste(literal_visible):
    bridge, transport, row = literal_visible
    transport["text"] = "› User's unsent draft"
    with pytest.raises(BridgeError) as error:
        await bridge.execute(
            {
                "id": "do-not-overwrite",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": {"pane_id": row["pane_id"], "expected_pid": 900, "text": "/resume"},
            },
            callback,
            callback,
        )
    assert error.value.code == "visible_input_not_empty"
    assert not transport["literal_calls"]
