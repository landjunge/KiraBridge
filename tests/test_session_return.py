"""One explicit Return to an observed view; no paste, replacement intent or replay."""

import hashlib

import pytest
from conftest import request
from pydantic import ValidationError
from test_literal_session_input import literal_visible  # noqa: F401
from test_plain_shell_paste import plain  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.session_manager import SessionInput, SessionManager

# Captured native Codex 0.166.0 picker footer; no shortened synthetic controls.
RESUME_MENU = (
    " Resume a previous session\n \n"
    " Filter:  Cwd  All    Status:  Active  Archived    Sort:  Updated  Created\n \n"
    " Type to search\n \n  No sessions yet\n\n"
    "──────────────────────────────────────── 0 / 0 · 100% ─\n"
    " enter resume   esc exit   ⌃c exit   tab focus sort/filter   ←/→ change option\n"
    " ⌃o comfortable view   ⌃t transcript   ⌃e expand   ↑/↓ browse\n\n"
)


def test_key_only_mode_is_explicit_and_normal_text_still_requires_payload():
    args = SessionInput(
        pane_id="terminal:100:ttys001",
        expected_pid=42,
        key="enter",
        expected_cursor="a" * 64,
        expected_agent_pid=43,
    )
    assert args.text == "" and args.submit is True
    assert args.key == "enter"
    assert SessionInput(pane_id=args.pane_id, expected_pid=42, text="text").key is None


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"text": ""},
        {"key": "enter"},
        {"key": "escape", "expected_cursor": "a" * 64},
        {"key": "enter", "text": "text", "expected_cursor": "a" * 64},
        {"key": "enter", "text": "\n", "expected_cursor": "a" * 64},
        {"key": "enter", "text": " ", "expected_cursor": "a" * 64},
        {"key": "enter", "submit": False, "expected_cursor": "a" * 64},
        {"key": "enter", "expected_cursor": "not-a-capture"},
        {"text": "text", "expected_cursor": "a" * 64},
        {"text": "text", "expected_agent_pid": 43},
    ],
)
def test_key_mode_conflicts_or_implicit_empty_input_are_rejected(fields):
    with pytest.raises(ValidationError):
        SessionInput(pane_id="terminal:100:ttys001", expected_pid=42, **fields)


@pytest.fixture
async def key_visible(literal_visible, monkeypatch):  # noqa: F811
    bridge, transport, row = literal_visible
    # Exercise the actual owner-scoped session read/capture path.
    monkeypatch.setattr(bridge.sessions, "read", SessionManager.read.__get__(bridge.sessions))

    async def observed(text):
        transport["text"] = text
        result = await bridge.sessions.read_observed("chatgpt", row["pane_id"], 900)
        return {
            "pane_id": row["pane_id"],
            "expected_pid": 900,
            "key": "enter",
            "expected_cursor": result["next_cursor"],
            "expected_agent_pid": result["input_readiness"]["binding"]["agent_pid"],
        }

    return bridge, transport, row, observed


@pytest.mark.parametrize("screen", ["› ", "› User's existing draft", RESUME_MENU])
async def test_explicit_return_sends_one_key_without_paste_or_agent_work(key_visible, screen):
    bridge, transport, _, observed = key_visible
    args = await observed(screen)
    value = request("session.input", args, task_id="one-return")
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        result = task["result"]
        assert result["return_sent"] and result["submitted"]
        assert result["paste_event_sent"] is False
        assert result["agent_confirmed"] is result["execution_confirmed"] is False
        assert bridge.submit("chatgpt", value, "")["result"] == result
        assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
        assert not bridge.store.db.execute("SELECT 1 FROM visible_handoffs").fetchone()
    assert transport["literal_calls"] == [("return", None)]


@pytest.mark.parametrize("size", [1014, 1078])
async def test_return_on_captured_collapsed_paste_with_standalone_warning(key_visible, size):
    bridge, transport, _, observed = key_visible
    screen = (
        f"› [Pasted Content {size} chars]\n \n  GPT-6.1-Sol xhigh · ~\n"
        + " " * 106
        + "⚠ 1 warning · f2 to view\n"
    )
    args = await observed(screen)
    result = await bridge.execute(
        {
            "id": "captured-hint-warning-return",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": args,
        },
        callback,
        callback,
    )
    assert result["return_sent"] and not result["paste_event_sent"]
    assert transport["literal_calls"] == [("return", None)]


@pytest.mark.parametrize("changed_agent", [False, True], ids=["same-agent", "replaced-agent"])
async def test_saved_return_cursor_survives_bridge_reopen_but_rechecks_agent(
    key_visible, monkeypatch, changed_agent
):
    from test_visible_selection import new_native_selection

    from kirabridge.bridge_core.bridge import Bridge

    bridge, _, row, observed = key_visible
    screen = "› [Pasted Content 1014 chars]\n \n  GPT-6.1-Sol xhigh · ~\n"
    screen += " " * 106 + "⚠ 1 warning · f2 to view\n"
    args = await observed(screen)
    bridge.store.close()
    restarted = Bridge(bridge.config)
    posts = []
    try:
        if changed_agent:
            row["processes"][1]["pid"] += 1
        await new_native_selection(restarted, monkeypatch, row)

        async def read(pane):
            assert pane == row["pane_id"]
            return screen

        async def press_return(pane, **guards):
            assert pane == row["pane_id"] and guards["expected_screen"] == screen
            assert args["expected_agent_pid"] in guards["identity_guard"]
            posts.append("return")

        async def no_real_catalog(*args, **kwargs):
            raise AssertionError("Reopen fixture must never observe actual terminals")

        monkeypatch.setattr(restarted.sessions, "catalog", no_real_catalog)
        monkeypatch.setattr(restarted.sessions.terminal_app, "read", read)
        monkeypatch.setattr(restarted.sessions.terminal_app, "press_return", press_return)
        # A fresh client/chat retains its authenticated principal, not a chat ID.
        assert (
            restarted.outputs.captured_input_view(
                "chatgpt", args["pane_id"], args["expected_pid"], args["expected_cursor"]
            )
            == screen
        )
        task = {
            "id": "return-after-reopen",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": args,
        }
        if changed_agent:
            with pytest.raises(BridgeError) as failure:
                await restarted.execute(task, callback, callback)
            assert failure.value.code == "visible_target_changed"
            assert posts == []
        else:
            result = await restarted.execute(task, callback, callback)
            assert result["return_sent"] and not result["paste_event_sent"]
            assert posts == ["return"]
    finally:
        restarted.store.close()


@pytest.mark.parametrize(
    "failure", ["changed", "foreign", "agent", "missing", "corrupt", "truncated"]
)
async def test_stale_or_untrusted_return_capture_sends_no_key(key_visible, failure):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    if failure == "changed":
        transport["text"] = "› A different draft"
    elif failure == "foreign":
        bridge.store.db.execute("UPDATE output_snapshots SET principal='grok_app'")
    elif failure == "agent":
        args["expected_agent_pid"] = 902
    elif failure == "missing":
        bridge.store.db.execute("DELETE FROM output_snapshots")
    elif failure == "corrupt":
        bridge.store.db.execute("UPDATE output_snapshots SET payload=?", (b'{"text":"corrupt"}',))
    else:
        bridge.store.db.execute("UPDATE output_snapshots SET truncated=1")
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "refuse-return",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
    assert not transport["literal_calls"]


@pytest.mark.parametrize(
    "screen",
    [
        "» Queued draft",
        "• Working (12s • esc to interrupt)\n› Existing draft",
        "› Existing draft\nApprove an unexpected operation?",
        "Back to bottom\n› Existing draft",
        "Resume a previous session\nUnrecognized dialog controls",
        "› Existing draft\n  tab to queue message\n  GPT-6.1-Sol max · ~\n",
        "› Existing draft\n  Approval required\n  GPT-6.1-Sol max · ~\n",
        "› Existing draft\n  ⚠ 1 warning · f2 to view\n",
        "› Existing draft\n  GPT-6.1-Sol xhigh · ~\n  ⚠ 1 warning · f2 to view EXECUTE\n",
        "› Existing draft\n  GPT-6.1-Sol xhigh · ~\n"
        "  ⚠ 1 warning · f2 to view\n  ⚠ 1 warning · f2 to view\n",
        "› Existing draft\n  Approval required\n  GPT-6.1-Sol xhigh · ~\n"
        "  ⚠ 1 warning · f2 to view\n",
        "• Working (12s • esc to interrupt)\n" + RESUME_MENU,
    ],
)
async def test_busy_or_unknown_return_frames_send_no_key(key_visible, screen):
    bridge, transport, _, observed = key_visible
    args = await observed(screen)
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "unsafe-return",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
    assert not transport["literal_calls"]


async def test_return_attempt_is_persisted_before_transport_and_never_replayed(
    key_visible, monkeypatch
):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    value = request("session.input", args, task_id="uncertain-return")

    async def uncertain(pane, **guards):
        task = bridge.store.get(value.task_id, "chatgpt")
        assert task["state"] == "running"
        assert task["evidence"]["terminal_input_attempted"] is True
        assert task["evidence"]["return_sent"] is False
        assert task["evidence"]["paste_event_sent"] is False
        transport["literal_calls"].append(("return-attempt", None))
        raise UncertainExecution("session_input_unknown", "Return may have been delivered")

    monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", uncertain)
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "unknown" and task["evidence"]["safe_to_retry"] is False
        assert bridge.submit("chatgpt", value, "")["state"] == "unknown"
    from kirabridge.bridge_core.bridge import Bridge

    restarted = Bridge(bridge.config)
    try:
        restarted.store.recover()
        assert restarted.submit("chatgpt", value, "")["state"] == "unknown"
    finally:
        restarted.store.close()
    assert transport["literal_calls"] == [("return-attempt", None)]


@pytest.mark.parametrize("failure", ["expired", "kind", "pane", "pid", "raw-sha", "missing-agent"])
async def test_cursor_must_be_a_live_scoped_canonical_read(key_visible, failure):
    bridge, transport, row, observed = key_visible
    screen = "› Existing draft"
    args = await observed(screen)
    assert args["expected_cursor"] != hashlib.sha256(screen.encode()).hexdigest()
    if failure == "expired":
        bridge.store.db.execute("UPDATE output_snapshots SET expires=0")
    elif failure == "kind":
        bridge.store.db.execute("UPDATE output_snapshots SET kind='execution_output'")
    elif failure == "pane":
        bridge.store.db.execute("UPDATE output_snapshots SET source_key='terminal:999:ttys009:900'")
    elif failure == "pid":
        bridge.store.db.execute(
            "UPDATE output_snapshots SET source_key=?", (row["pane_id"] + ":901",)
        )
    elif failure == "raw-sha":
        args["expected_cursor"] = hashlib.sha256(screen.encode()).hexdigest()
    else:
        args.pop("expected_agent_pid")
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "scope-return",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
    assert not transport["literal_calls"]


@pytest.mark.parametrize("denial", ["agent", "input", "terminal", "inspect"])
async def test_return_does_not_expand_existing_permissions(key_visible, denial):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    policy = bridge.config.principals["chatgpt"]
    if denial == "agent":
        policy.agents = []
    else:
        capability = {
            "input": "session.input",
            "terminal": "terminal.execute",
            "inspect": "session.inspect",
        }[denial]
        policy.capabilities = [item for item in policy.capabilities if item != capability]
    with pytest.raises(BridgeError):
        await bridge.execute(
            {
                "id": "denied-return",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
    assert not transport["literal_calls"]


@pytest.mark.parametrize(
    "reservation",
    ["independent", "same-pane", "same-window", "same-tty", "pid", "active", "same-task"],
)
async def test_return_preserves_only_independent_historical_unknown_resources(
    key_visible, reservation
):
    from kirabridge.bridge_core.models import canonical
    from kirabridge.message_manager import MessageSend

    bridge, transport, row, observed = key_visible
    args = await observed(RESUME_MENU)
    old = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    if reservation == "same-pane":
        old.pane_id = row["pane_id"]
    elif reservation == "same-window":
        old.pane_id = "terminal:202:ttys002"
    elif reservation == "same-tty":
        old.pane_id = "terminal:101:ttys006"
    elif reservation == "pid":
        old.agent_pid = 901
    identifier = "new-return" if reservation == "same-task" else "old-unknown"
    message = bridge.messages._send(
        "chatgpt",
        MessageSend(
            conversation_id="old-return-resource",
            recipient="codex",
            body="Old work",
            idempotency_key="old-return-resource",
            dispatch=False,
        ),
        visible_internal=True,
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            "chatgpt",
            "codex",
            "old-hash",
            canonical(old.model_dump()),
            message["id"],
            "sent" if reservation == "active" else "unknown",
            1,
            1,
            "{}",
        ),
    )
    before = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    task = {"id": "new-return", "principal": "chatgpt", "operation": "session.input", "args": args}
    if reservation == "independent":
        result = await bridge.execute(task, callback, callback)
        assert result["return_sent"] and transport["literal_calls"] == [("return", None)]
    else:
        with pytest.raises(BridgeError) as error:
            await bridge.execute(task, callback, callback)
        assert error.value.code == "visible_target_busy" and not transport["literal_calls"]
    after = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    assert after == before
    assert not bridge.store.db.execute("SELECT 1 FROM visible_handoff_events").fetchone()
    assert bridge.messages.get("chatgpt", message["id"])["acknowledged"] is None


async def test_return_without_text_preserves_the_optional_confirmation_buffer(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    assert "text" not in args
    bridge.config.session_input_policy.enabled = True
    bridge.config.session_input_policy.principals = ["chatgpt"]
    value = request("session.input", args, task_id="buffered-return")
    async with bridge:
        waiting = bridge.prepare("chatgpt", value)
        assert waiting["state"] == "created" and waiting["input_buffer"]["state"] == "waiting"
        assert not transport["literal_calls"]
        token = bridge.security.grant("chatgpt", value)
        bridge.submit("chatgpt", value, token)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        assert task["input_buffer"]["state"] == "sent"
        assert task["args"] == args
    assert transport["literal_calls"] == [("return", None)]


async def test_return_journal_failure_prevents_native_key(key_visible, monkeypatch):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    transition = bridge.store.transition

    def failed_marker(task_id, state, evidence=None, **kwargs):
        if state == "running" and (evidence or {}).get("terminal_input_attempted"):
            raise BridgeError("evidence_unavailable", "Cannot persist Return attempt")
        return transition(task_id, state, evidence, **kwargs)

    monkeypatch.setattr(bridge.store, "transition", failed_marker)
    value = request("session.input", args, task_id="failed-return-journal")
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "unknown" and task["error"]["code"] == "evidence_unavailable"
    assert not transport["literal_calls"]


@pytest.mark.parametrize("condition", ["idle", "busy", "draft", "changed-process"])
async def test_shell_return_uses_native_empty_shell_identity_and_screen_guards(
    plain,  # noqa: F811
    bridge,
    condition,
):
    sessions, row, snapshot, native = plain
    native.return_value = {"return_sent": True}
    read = await sessions.read_observed("local", row["pane_id"], 900)
    args = {
        "pane_id": row["pane_id"],
        "expected_pid": 900,
        "key": "enter",
        "expected_cursor": read["next_cursor"],
    }
    if condition == "busy":
        row["busy"] = True
    elif condition == "draft":
        sessions.terminal_app.read.return_value = "KiraBridge fixture % existing draft"
    elif condition == "changed-process":
        snapshot["rows"] = [line.replace("/bin/zsh", "/bin/bash") for line in snapshot["rows"]]
    task = {"id": "shell-return", "principal": "local", "operation": "session.input", "args": args}
    if condition == "idle":
        result = await bridge.execute(task, callback, callback)
        assert result["return_sent"] and result["paste_event_sent"] is False
        native.assert_awaited_once()
        source = native.call_args.args[0]
        assert source.count("se.keyCode(36)") == 1
        assert "paste.actions" not in source and "checkClipboard" not in source
        assert "app.doScript" not in source and "Selected terminal input changed" in source
        assert "checkTargetIdentity" in source and "const shellRows" in source
        assert source.index("const shellRows") < source.index("se.keyCode(36)")
        assert source.index("if(tab.busy())") < source.index("se.keyCode(36)")
    else:
        with pytest.raises(BridgeError):
            await bridge.execute(task, callback, callback)
        native.assert_not_awaited()


async def test_return_scope_capture_json_corruption_fails_closed(key_visible):
    bridge, transport, _, observed = key_visible
    args = await observed("› Existing draft")
    # A corrupt repository row must not be treated as a new legitimate read.
    invalid = b"not JSON"
    fingerprint = hashlib.sha256(invalid).hexdigest()
    bridge.store.db.execute(
        "UPDATE output_snapshots SET payload=?,sha256=?,bytes=?,original_bytes=?",
        (invalid, fingerprint, len(invalid), len(invalid)),
    )
    args["expected_cursor"] = fingerprint
    with pytest.raises(BridgeError) as error:
        await bridge.execute(
            {
                "id": "corrupt-return",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": args,
            },
            callback,
            callback,
        )
    assert error.value.code == "visible_capture_unavailable"
    assert not transport["literal_calls"]


async def test_shell_return_native_script_compiles_without_executing_ui(
    plain,  # noqa: F811
    bridge,
    tmp_path,
):
    import asyncio
    import shutil
    import subprocess

    sessions, row, _, native = plain
    read = await sessions.read_observed("local", row["pane_id"], 900)
    await bridge.execute(
        {
            "id": "compile-return",
            "principal": "local",
            "operation": "session.input",
            "args": {
                "pane_id": row["pane_id"],
                "expected_pid": 900,
                "key": "enter",
                "expected_cursor": read["next_cursor"],
            },
        },
        callback,
        callback,
    )
    compiler = shutil.which("osacompile") or shutil.which("node")
    if compiler is None:
        pytest.skip("No JavaScript syntax compiler available")
    source = tmp_path / "native-return.js"
    source.write_text(native.call_args.args[0])
    command = [compiler, "-l", "JavaScript", "-o", str(tmp_path / "return.scpt"), str(source)]
    if compiler.endswith("node"):
        command = [compiler, "--check", str(source)]
    result = await asyncio.to_thread(
        subprocess.run, command, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
