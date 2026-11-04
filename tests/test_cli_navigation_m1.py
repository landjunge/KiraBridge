"""Actual coordinator paths with simulated Terminal only; never native input."""

import pytest
from conftest import request
from test_literal_session_input import literal_visible  # noqa: F401
from test_session_return import key_visible as key_visible
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError

FOOTER = "\n\n  GPT-6.1-Sol xhigh · ~\n"
COPY = "› " + FOOTER + "  ⌃c copy · enter copy & follow · esc clear\n"
SCROLL = (
    "↓ Back to bottom · esc\n\n› Existing draft\n  continues here"
    + FOOTER
    + "  esc latest             ⚠ 1 warning · f2 to view\n"
)
DRAFT = "› Existing draft\n  continues here" + FOOTER + "  ⚠ 1 warning · f2 to view\n"


async def install_escape(bridge, transport, after):
    async def press(pane, key, **guards):
        assert key == "escape" and guards["expected_screen"] == transport["text"]
        assert guards["identity_guard"]
        transport["literal_calls"].append(("escape", None))
        transport["text"] = after

    bridge.sessions.terminal_app.press_key = press


async def test_copy_return_is_not_misreported_as_prompt_submission(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(COPY)
    with pytest.raises(BridgeError) as failure:
        await bridge.execute(
            {
                "id": "copy-is-not-submit",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert failure.value.code == "visible_navigation_required"
    assert transport["literal_calls"] == []


async def noop(*args):
    pass


async def test_explicit_copy_exit_posts_one_escape_no_return_and_replay_posts_nothing(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(COPY)
    args["key"] = "escape"
    await install_escape(bridge, transport, "› " + FOOTER)
    value = request("session.input", args, task_id="copy-exit-once")
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        assert task["result"]["navigation_observed"] and not task["result"]["return_sent"]
        assert bridge.submit("chatgpt", value, "")["state"] == "completed"
    assert transport["literal_calls"] == [("escape", None)]


async def test_scroll_enter_retains_draft_then_sends_one_return(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(SCROLL)
    await install_escape(bridge, transport, DRAFT)
    result = await bridge.execute(
        {
            "id": "scroll-draft-once",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": args,
        },
        noop,
        noop,
    )
    assert result["return_sent"] and not result["paste_event_sent"]
    assert transport["literal_calls"] == [("escape", None), ("return", None)]


async def test_navigation_losing_draft_never_pastes_or_returns(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(SCROLL)
    await install_escape(bridge, transport, "› changed draft" + FOOTER)
    with pytest.raises(BridgeError) as failure:
        await bridge.execute(
            {
                "id": "lost-draft",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert failure.value.code == "visible_navigation_unknown"
    assert transport["literal_calls"] == [("escape", None)]


@pytest.mark.parametrize("failure", ["cursor", "agent", "working", "dialog", "foreign_draft"])
async def test_unsafe_navigation_sends_no_key(key_visible, failure):
    bridge, transport, _, observed = key_visible
    screen = COPY
    if failure == "working":
        screen = "• Working (2s • esc to interrupt)\n" + screen
    if failure == "dialog":
        screen = "Approval required\n" + screen
    if failure == "foreign_draft":
        screen = COPY.replace("› ", "› foreign draft", 1)
    args = await observed(screen)
    args["key"] = "escape"
    if failure == "cursor":
        transport["text"] += "changed"
    if failure == "agent":
        args["expected_agent_pid"] += 1
    await install_escape(bridge, transport, "› " + FOOTER)
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "unsafe-nav",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert transport["literal_calls"] == []


async def test_submit_true_exits_empty_copy_before_paste_and_returns_once(key_visible):
    bridge, transport, row, observed = key_visible
    await observed(COPY)
    await install_escape(bridge, transport, "› " + FOOTER)
    transport["footer"] = FOOTER
    args = {
        "pane_id": row["pane_id"],
        "expected_pid": 900,
        "text": "new harmless payload",
        "submit": True,
    }
    result = await bridge.execute(
        {
            "id": "copy-to-message",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": args,
        },
        noop,
        noop,
    )
    assert result["submitted"] and result["return_sent"]
    assert transport["literal_calls"] == [
        ("escape", None),
        ("paste", "new harmless payload"),
        ("return", None),
    ]


async def test_changed_post_navigation_identity_never_claims_observed_success(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(COPY)
    args["key"] = "escape"
    await install_escape(bridge, transport, "› " + FOOTER)
    original = bridge.visible_handoffs.binding_readiness

    async def state(*a, **kw):
        if transport["literal_calls"]:
            return {
                "state": "target_changed",
                "ready": False,
                "reason": "bound_agent_pid_not_present",
            }
        return await original(*a, **kw)

    bridge.visible_handoffs.binding_readiness = state
    with pytest.raises(BridgeError) as failure:
        await bridge.execute(
            {
                "id": "changed-nav-agent",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert failure.value.code == "visible_navigation_unknown"
    assert transport["literal_calls"] == [("escape", None)]


MODEL_MENU = (
    "Select Model and Effort\n\n"
    "› 1. GPT-6.1-Sol (current)  Latest workhorse model for coding and everyday work.\n"
    "  2. GPT-6-Astra            Frontier intelligence for the most demanding work.\n\n"
    "  enter select · esc back\n"
)


async def test_model_menu_enter_is_never_a_prompt_submission(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed(MODEL_MENU)
    with pytest.raises(BridgeError) as failure:
        await bridge.execute(
            {
                "id": "model-no-select",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert failure.value.code == "visible_navigation_required"
    assert transport["literal_calls"] == []


async def test_model_menu_escape_then_normal_text_uses_same_guarded_path(key_visible):
    bridge, transport, row, observed = key_visible
    args = await observed(MODEL_MENU)
    args["key"] = "escape"
    await install_escape(bridge, transport, "› " + FOOTER)
    result = await bridge.execute(
        {"id": "model-exit", "principal": "chatgpt", "operation": "session.input", "args": args},
        noop,
        noop,
    )
    assert result["navigation_observed"] and not result["return_sent"]
    transport["footer"] = FOOTER
    result = await bridge.execute(
        {
            "id": "after-model",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": {
                "pane_id": row["pane_id"],
                "expected_pid": 900,
                "text": "normal text after menu",
                "submit": True,
            },
        },
        noop,
        noop,
    )
    assert result["return_sent"] and result["insertion_verified"]
    assert not result["acceptance_observed"] and not result["response_observed"]
    assert transport["literal_calls"] == [
        ("escape", None),
        ("paste", "normal text after menu"),
        ("return", None),
    ]


@pytest.mark.parametrize("text", ["/permissions", "/model GPT-6-Astra", "/status --unexpected"])
async def test_unsupported_slash_never_sends_return(key_visible, text):
    bridge, transport, _, observed = key_visible
    args = await observed("› " + text + FOOTER)
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "no-other-slash",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            noop,
            noop,
        )
    assert transport["literal_calls"] == []


@pytest.mark.parametrize(
    "initial,text", [(COPY, "new harmless payload go-go-go"), ("› " + FOOTER, "/status go-go-go")]
)
async def test_released_buffer_dispatches_original_intent_once_before_navigation_or_slash(
    key_visible, initial, text
):
    bridge, transport, row, observed = key_visible
    await observed(initial)
    bridge.config.session_input_policy.enabled = True
    bridge.config.session_input_policy.principals = ["chatgpt"]
    await install_escape(bridge, transport, "› " + FOOTER)
    transport["footer"] = FOOTER
    calls = []
    original = bridge.tasks.input_policy.dispatch

    def dispatch(principal, args, task_id):
        calls.append(args.model_dump())
        return original(principal, args, task_id)

    bridge.tasks.input_policy.dispatch = dispatch
    value = request(
        "session.input",
        {
            "pane_id": row["pane_id"],
            "expected_pid": 900,
            "text": text,
            "submit": True,
        },
        task_id="buffered-once",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        assert task["input_buffer"]["state"] == "sent"
        assert bridge.submit("chatgpt", value, "")["state"] == "completed"
    assert len(calls) == 1 and calls[0]["text"] == text and calls[0]["key"] is None
    expected = text.removesuffix(" go-go-go")
    assert transport["literal_calls"] == (
        ([("escape", None)] if initial == COPY else []) + [("paste", expected), ("return", None)]
    )


async def test_lost_escape_reply_is_unknown_and_replay_never_repeats_or_sends_text(key_visible):
    from kirabridge.bridge_core.models import UncertainExecution

    bridge, transport, _, observed = key_visible
    args = await observed(COPY)
    args["key"] = "escape"

    async def lost(pane, key, **guards):
        transport["literal_calls"].append(("escape", None))
        transport["text"] = "› " + FOOTER
        raise UncertainExecution("native_reply_lost", "simulated lost result after native key")

    bridge.sessions.terminal_app.press_key = lost
    value = request("session.input", args, task_id="lost-escape-once")
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "unknown", task
        assert bridge.submit("chatgpt", value, "")["state"] == "unknown"
    assert transport["literal_calls"] == [("escape", None)]
