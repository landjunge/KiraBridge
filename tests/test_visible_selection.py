"""Current explicit selection is per task; old uncertainty is never rebound/replayed."""

import asyncio
import os
from copy import deepcopy

import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical, digest
from kirabridge.session_manager import SessionInput


@pytest.mark.parametrize("ready", [True, False], ids=["idle-agent", "working-agent"])
async def test_require_idle_checks_current_agent_readiness_before_literal_paste(
    visible,  # noqa: F811
    monkeypatch,
    ready,
):
    from kirabridge.session_manager import SessionManager

    bridge, _ = visible
    row = new_row()
    row["transport"] = "terminal_app"
    await new_selection(bridge, monkeypatch, row)
    _, binding = bridge.sessions.explicit_agent_binding(row)
    calls, observations = [], []

    async def identity(pid, **kwargs):
        return (
            f"{os.getuid()} ttys006 Sat Oct 24 12:00:00 2026 "
            f"{899 if pid == 900 else 900} /bin/{'zsh' if pid == 900 else 'codex'}"
        )

    async def read(pane):
        return "owned-current-widget"

    async def assess(principal, output):
        observations.append(output)
        return {"ready": ready, "state": "ready" if ready else "working"}

    async def insert(pane, text, **guards):
        calls.append((pane, text, guards))

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions, "readiness", assess)
    args = SessionInput(
        pane_id=row["pane_id"], expected_pid=900, text="literal", submit=False, require_idle=True
    )
    async with bridge.sessions.agent_selection("chatgpt", "codex", binding):
        if ready:
            result = await SessionManager.insert(bridge.sessions, "chatgpt", args)
            assert result == {
                "paste_event_sent": True,
                "return_sent": False,
                "agent_confirmed": False,
            }
        else:
            with pytest.raises(BridgeError) as failure:
                await SessionManager.insert(bridge.sessions, "chatgpt", args)
            assert failure.value.code == "visible_target_not_ready"
    assert len(observations) == 1 and observations[0]["text"] == "owned-current-widget"
    assert len(calls) == int(ready)
    if ready:
        assert calls[0][0:2] == (row["pane_id"], "literal")
        assert calls[0][2]["identity_guard"][901].endswith("/bin/codex")
        assert calls[0][2]["expected_screen"] == "owned-current-widget"


def new_row():
    return {
        "pane_id": "terminal:202:ttys006",
        "expected_pid": 900,
        "tty": "/dev/ttys006",
        "transport": "test",
        "processes": [
            {"pid": 900, "ppid": 899, "name": "zsh", "image": "/bin/zsh"},
            {"pid": 901, "ppid": 900, "name": "codex", "image": "/bin/codex"},
        ],
        "busy": True,
    }


@pytest.mark.parametrize(
    "reservation",
    [
        "independent",
        "same-window",
        "same-tty",
        "same-window-id",
        "pid-overlap",
        "active",
        "same-task",
    ],
)
async def test_explicit_literal_paste_preserves_unrelated_unknown_handoff(
    visible,  # noqa: F811
    config,
    monkeypatch,
    reservation,
):
    from kirabridge.message_manager import MessageSend
    from kirabridge.session_manager import SessionManager

    bridge, transport = visible
    transport.update(target="codex", text="› ")
    config.session_input_policy.enabled = False
    row = new_row()
    row["transport"] = "terminal_app"
    await new_selection(bridge, monkeypatch, row)
    old_binding = config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    if reservation == "same-window":
        old_binding.pane_id = row["pane_id"]
    elif reservation == "same-tty":
        old_binding.pane_id = "terminal:101:ttys006"
    elif reservation == "same-window-id":
        old_binding.pane_id = "terminal:202:ttys002"
    elif reservation == "pid-overlap":
        old_binding.agent_pid = 901
    identifier = "fresh-literal" if reservation == "same-task" else "old-unknown"
    message = bridge.messages._send(
        "chatgpt",
        MessageSend(
            conversation_id="uncertain-original-test",
            recipient="codex",
            body="Original uncertain work; never replay",
            idempotency_key="original-uncertainty",
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
            canonical(old_binding.model_dump()),
            message["id"],
            "sent" if reservation == "active" else "unknown",
            1,
            1,
            canonical({"terminal_input_attempted": True}),
        ),
    )
    before = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    pasted = []

    async def identity(pid, **kwargs):
        return (
            f"{os.getuid()} ttys006 Sat Oct 24 12:00:00 2026 "
            f"{899 if pid == 900 else 900} /bin/{'zsh' if pid == 900 else 'codex'}"
        )

    async def read(pane):
        return "› "

    async def insert(pane, text, **guards):
        pasted.append((pane, text, guards))

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions, "insert", SessionManager.insert.__get__(bridge.sessions))
    task = {
        "id": "fresh-literal",
        "principal": "chatgpt",
        "operation": "session.input",
        "args": {
            "pane_id": row["pane_id"],
            "expected_pid": 900,
            "text": "literal",
            "submit": False,
            "require_idle": True,
        },
    }
    if reservation == "independent":
        result = await bridge.execute(task, callback, callback)
        assert result["submitted"] is False and result["execution_confirmed"] is False
        assert len(pasted) == 1 and pasted[0][0:2] == (row["pane_id"], "literal")
        assert pasted[0][2]["identity_guard"] and pasted[0][2]["expected_screen"] == "› "
    else:
        with pytest.raises(BridgeError) as failure:
            await bridge.execute(task, callback, callback)
        assert failure.value.code == "visible_target_busy" and not pasted
    after = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    assert after == before
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1
    assert not bridge.store.db.execute("SELECT 1 FROM visible_handoff_events").fetchone()


async def new_selection(bridge, monkeypatch, row):
    original = bridge.sessions.selected

    async def selected(principal, pane, pid):
        if pane == row["pane_id"] and pid == row["expected_pid"]:
            return deepcopy(row)
        return await original(principal, pane, pid)

    monkeypatch.setattr(bridge.sessions, "selected", selected)


async def new_native_selection(bridge, monkeypatch, row):
    row["transport"] = "terminal_app"
    await new_selection(bridge, monkeypatch, row)

    async def identity(pid, **kwargs):
        process = next(p for p in row["processes"] if p["pid"] == pid)
        return (
            f"{os.getuid()} ttys006 Sat Oct 24 12:00:00 2026 {process['ppid']} {process['image']}"
        )

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)


async def test_explicit_current_agent_handle_enters_current_window_without_mutating_default(
    visible,  # noqa: F811
    config,
    monkeypatch,
):
    bridge, transport = visible
    transport.update(target="codex", text="› ")
    row = new_row()
    await new_selection(bridge, monkeypatch, row)
    before = config.visible_handoffs.bindings["codex"].model_dump()
    result = await bridge.execute(
        {
            "id": "fresh-explicit",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": {
                "pane_id": row["pane_id"],
                "expected_pid": row["expected_pid"],
                "text": "explicit current request",
            },
        },
        callback,
        callback,
    )
    assert result["success"] and transport["calls"] == ["insert", "return"]
    stored = bridge.visible_handoffs.status("chatgpt", "fresh-explicit")
    assert stored["binding"]["pane_id"] == row["pane_id"]
    assert stored["binding"]["agent_pid"] == 901
    assert config.visible_handoffs.bindings["codex"].model_dump() == before
    assert bridge.sessions._selection.get() is None
    # Automatic/default delivery still uses the old assignment; it never silently follows.
    with pytest.raises(BridgeError, match="assigned original"):
        bridge.sessions.assigned_agent(row)


def test_new_agent_generation_drops_old_codex_turn_protocol(visible, config):  # noqa: F811
    bridge, _ = visible
    original = config.visible_handoffs.bindings["codex"]
    original.codex_thread_id = "11111111-1111-1111-1111-111111111111"
    original.codex_rollout_path = "/explicitly-configured/old-rollout.jsonl"
    target, selected = bridge.sessions.explicit_agent_binding(new_row())
    assert target == "codex" and selected.agent_pid == 901
    assert selected.codex_thread_id is None and selected.codex_rollout_path is None
    assert original.codex_thread_id is not None


async def test_unknown_old_task_cannot_be_rebound_to_a_new_window(visible, monkeypatch):  # noqa: F811
    bridge, transport = visible
    transport.update(target="codex", text="› ")
    row = new_row()
    await new_selection(bridge, monkeypatch, row)
    target, binding = bridge.sessions.explicit_agent_binding(row)
    args = AgentInput(agent=target, prompt="old request", cwd="/tmp")
    old = bridge.config.visible_handoffs.bindings[target]
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "old-unknown",
            "chatgpt",
            target,
            digest({"principal": "chatgpt", "args": args.model_dump()}),
            canonical(old.model_dump()),
            "unrelated-original-message",
            "unknown",
            1,
            1,
            "{}",
        ),
    )
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.execute(
            {"id": "old-unknown", "principal": "chatgpt"},
            args,
            callback,
            callback,
            binding_override=binding,
        )
    assert exc.value.code == "handoff_conflict"
    assert not transport["calls"]
    assert (
        bridge.store.db.execute(
            "SELECT state FROM visible_handoffs WHERE id='old-unknown'"
        ).fetchone()[0]
        == "unknown"
    )


async def test_agent_change_between_selection_and_dispatch_has_no_input(visible, monkeypatch):  # noqa: F811
    bridge, transport = visible
    row = new_row()
    _, binding = bridge.sessions.explicit_agent_binding(row)
    row["processes"][-1]["pid"] = 902
    await new_selection(bridge, monkeypatch, row)
    with pytest.raises(BridgeError, match="changed before dispatch"):
        async with bridge.sessions.agent_selection("chatgpt", "codex", binding):
            pytest.fail("Changed agent must not enter dispatch")
    assert not transport["calls"]


async def test_process_start_identity_is_task_local_and_transport_guarded(visible, monkeypatch):  # noqa: F811
    bridge, _ = visible
    row = new_row()
    row["transport"] = "terminal_app"
    await new_selection(bridge, monkeypatch, row)
    _, binding = bridge.sessions.explicit_agent_binding(row)
    calls = []

    async def identity(pid, **kwargs):
        return (
            f"{os.getuid()} ttys006 Sat Oct 24 12:00:00 2026 "
            f"{899 if pid == 900 else 900} /bin/{'zsh' if pid == 900 else 'codex'}"
        )

    async def native(source, **kwargs):
        calls.append(source)
        return {"sent": True}

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "native", native)

    async def ready_screen(pane):
        return "› "

    monkeypatch.setattr(bridge.sessions.terminal_app, "read", ready_screen)
    # Use real SessionManager insertion (the handoff fixture normally mocks that owner).
    from kirabridge.session_manager import SessionManager

    entered, release = asyncio.Event(), asyncio.Event()

    async def unrelated():
        entered.set()
        await release.wait()
        assert bridge.sessions._selection.get() is None

    independent = asyncio.create_task(unrelated())
    await entered.wait()
    async with bridge.sessions.agent_selection("chatgpt", "codex", binding):
        release.set()
        await independent
        assert bridge.sessions.assigned_agent(row) == "codex"

        async def inherited_child():
            with pytest.raises(BridgeError, match="another task"):
                bridge.sessions.current_selection()
            with pytest.raises(BridgeError, match="another task"):
                await SessionManager.insert(
                    bridge.sessions,
                    "chatgpt",
                    SessionInput(
                        pane_id=row["pane_id"],
                        expected_pid=900,
                        text="MUST_NOT_REACH",
                        submit=False,
                    ),
                )

        await asyncio.create_task(inherited_child())
        await SessionManager.insert(
            bridge.sessions,
            "chatgpt",
            SessionInput(pane_id=row["pane_id"], expected_pid=900, text="test input", submit=False),
        )
        assert bridge.sessions.selected_identities(row)[901].endswith("/bin/codex")

        assert "checkTargetIdentity" in calls[0]
        assert "/bin/zsh" in calls[0] and "/bin/codex" in calls[0]
        assert "ppid=,comm=" in calls[0]
        before_paste = calls[0].split('paste.actions.byName("AXPress").perform();', 1)[0]
        assert before_paste.rfind("checkTargetIdentity();") < before_paste.rfind("checkFocus();")
        assert before_paste.rfind("checkFocus();") < before_paste.rfind(
            "Selected terminal input changed"
        )
    assert bridge.sessions._selection.get() is None


def test_catalog_does_not_claim_open_cli_busy_means_working(visible):  # noqa: F811
    bridge, _ = visible
    row = bridge.sessions.describe([new_row()])[0]
    assert row["busy"] is True and row["agent_activity"] == "not_probed"
    assert row["agent_candidate"] == "codex" and not row["configured_binding_current"]
    assert row["agent_identity_verified"] is False
    assert "not cryptographic" in row["agent_identity_scope"]


def test_a_shell_pid_cannot_preserve_an_old_codex_protocol_pin(visible, config):  # noqa: F811
    bridge, _ = visible
    original = config.visible_handoffs.bindings["codex"]
    original.pane_id, original.expected_pid, original.agent_pid = "terminal:202:ttys006", 900, 900
    original.codex_thread_id = "11111111-1111-1111-1111-111111111111"
    original.codex_rollout_path = "/configured/old.jsonl"
    row = new_row()
    assert not bridge.sessions.describe([row])[0]["configured_binding_current"]
    _, binding = bridge.sessions.explicit_agent_binding(row)
    assert binding.agent_pid == 901 and binding.codex_thread_id is None


async def test_exec_change_during_identity_capture_cannot_be_pinned(visible, monkeypatch):  # noqa: F811
    bridge, _ = visible
    row = new_row()
    row["transport"] = "terminal_app"
    await new_selection(bridge, monkeypatch, row)
    _, binding = bridge.sessions.explicit_agent_binding(row)

    async def identity(pid, **kwargs):
        return (
            f"{os.getuid()} ttys006 Sat Oct 24 12:00:00 2026 {899 if pid == 900 else 900} /bin/zsh"
        )

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    with pytest.raises(BridgeError, match="image/parent/TTY"):
        async with bridge.sessions.agent_selection("chatgpt", "codex", binding):
            pytest.fail("A changed executable must not acquire the selection context")


def test_native_screen_guard_uses_unicode_codepoints_for_long_emoji_viewport(tmp_path):
    from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

    text = "🧠" * 9000 + "› "
    guard = TerminalAppTransport.native_screen_guard(text)
    assert "Array.from(tab.contents()).slice(-8192).join('')" in guard
    import json

    literal = guard.split("!==", 1)[1].split(") throw Error", 1)[0]
    assert json.loads(literal) == text[-8192:]
    import subprocess
    import sys

    if sys.platform == "darwin":
        script = tmp_path / "unicode-guard.js"
        script.write_text(
            "const tab={contents:()=>"
            + json.dumps(text)
            + "};"
            + guard
            + ";JSON.stringify({guarded:true});"
        )
        assert json.loads(
            subprocess.check_output(
                ["/usr/bin/osascript", "-l", "JavaScript", str(script)], text=True
            )
        ) == {"guarded": True}


async def test_explicit_handle_does_not_grant_an_unallowed_agent(visible, config, monkeypatch):  # noqa: F811
    bridge, transport = visible
    row = new_row()
    await new_selection(bridge, monkeypatch, row)
    config.principals["chatgpt"].agents = []
    with pytest.raises(BridgeError) as exc:
        await bridge.execute(
            {
                "id": "not-granted",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": {
                    "pane_id": row["pane_id"],
                    "expected_pid": 900,
                    "text": "must not be sent",
                },
            },
            callback,
            callback,
        )
    assert exc.value.code == "agent_denied" and not transport["calls"]


@pytest.mark.parametrize("uncertain", [False, True])
async def test_paste_only_is_durable_exact_and_never_replayed(
    visible,  # noqa: F811
    config,
    monkeypatch,
    uncertain,
):
    from conftest import request

    from kirabridge.bridge_core.models import UncertainExecution

    bridge, transport = visible
    transport.update(target="codex", text="› ")
    row = new_row()
    await new_native_selection(bridge, monkeypatch, row)
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["chatgpt"]
    texts = []

    async def paste(principal, args, *, before_transport=None):
        assert before_transport is not None
        await before_transport()
        assert bridge.sessions.current_selection()[0] == "codex"
        task = bridge.store.get("literal-paste", principal)
        assert task["state"] == "running"
        assert task["evidence"]["terminal_input_attempted"] is True
        assert task["input_buffer"]["state"] == "dispatching"
        texts.append(args.text)
        if uncertain:
            raise UncertainExecution("session_input_unknown", "Outcome unknown; do not resend")
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    monkeypatch.setattr(bridge.sessions, "insert", paste)
    value = request(
        "session.input",
        {
            "pane_id": row["pane_id"],
            "expected_pid": row["expected_pid"],
            "text": "Unicode 😀\nLiteral text go-go-go",
            "submit": False,
        },
        task_id="literal-paste",
    )
    before = config.visible_handoffs.bindings["codex"].model_dump()
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == ("unknown" if uncertain else "completed"), task
        if uncertain:
            assert task["evidence"]["safe_to_retry"] is False
            assert task["evidence"]["last_observation"]["return_sent"] is False
        else:
            assert task["input_buffer"]["state"] == "sent"
            assert task["result"]["paste_event_sent"] is True
            for key in ("return_sent", "agent_confirmed", "execution_confirmed", "submitted"):
                assert task["result"][key] is False
        assert bridge.submit("chatgpt", value, "")["state"] == task["state"]
    from kirabridge.bridge_core.bridge import Bridge

    restarted = Bridge(config)
    try:
        restarted.store.recover()
        assert restarted.submit("chatgpt", value, "")["state"] == task["state"]
        assert (
            restarted.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 0
        )
    finally:
        restarted.store.close()
    assert texts == ["Unicode 😀\nLiteral text"]
    assert not transport["calls"]
    assert config.visible_handoffs.bindings["codex"].model_dump() == before
    assert bridge.sessions._selection.get() is None


@pytest.mark.parametrize("denial", ["agent", "busy"])
async def test_paste_only_rejects_denied_agent_or_active_widget_before_input(
    visible,  # noqa: F811
    config,
    monkeypatch,
    denial,
):
    bridge, transport = visible
    row = new_row()
    await new_native_selection(bridge, monkeypatch, row)
    transport.update(target="codex", text="› ")
    if denial == "agent":
        config.principals["chatgpt"].agents = ["grok"]
    else:
        transport["text"] = "• Working (12s • esc to interrupt)\n› "
    with pytest.raises(BridgeError) as failure:
        await bridge.execute(
            {
                "id": "denied-paste",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": {
                    "pane_id": row["pane_id"],
                    "expected_pid": row["expected_pid"],
                    "text": "must not paste",
                    "submit": False,
                },
            },
            callback,
            callback,
        )
    assert failure.value.code == ("agent_denied" if denial == "agent" else "visible_target_working")
    assert not transport["calls"]


async def test_observed_read_catalogues_once_per_operation_with_two_argument_readiness(
    visible,  # noqa: F811
    monkeypatch,
):
    from kirabridge.session_manager import SessionManager

    bridge, _ = visible
    row = new_row()
    calls = []

    async def selected(principal, pane, pid):
        calls.append((principal, pane, pid))
        return deepcopy(row)

    async def read(pane):
        return "› "

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions, "read", SessionManager.read.__get__(bridge.sessions))
    result = await bridge.sessions.read_observed("chatgpt", row["pane_id"], 900)
    assert result["input_readiness"]["ready"] is True
    assert len(calls) == 1


async def test_observation_scope_rejects_wrong_handle_identity_task_and_expiration(
    visible,  # noqa: F811
    monkeypatch,
):
    bridge, _ = visible
    row = new_row()
    _, binding = bridge.sessions.explicit_agent_binding(row)
    calls = []

    async def selected(*args):
        calls.append(args)
        return deepcopy(row)

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    with bridge.sessions.observation_scope("chatgpt", row):
        captured = bridge.sessions._observation.get()
        assert await bridge.sessions.observed_selected("chatgpt", row["pane_id"], 900) == row
        for principal, pane, pid in (
            ("other", row["pane_id"], 900),
            ("chatgpt", "terminal:999:ttys999", 900),
            ("chatgpt", row["pane_id"], 901),
        ):
            with pytest.raises(BridgeError) as error:
                await bridge.sessions.observed_selected(principal, pane, pid)
            assert error.value.code == "session_observation_changed"

        async def child():
            with pytest.raises(BridgeError, match="scope changed or expired"):
                await bridge.sessions.observed_selected("chatgpt", row["pane_id"], 900)

        await asyncio.create_task(child())
        wrong_agent = binding.model_copy(update={"agent_pid": 902})
        observation = await bridge.visible_handoffs.binding_readiness(
            "chatgpt", "codex", wrong_agent, {"text": "› "}
        )
        assert observation["state"] == "target_changed" and not observation["ready"]
        wrong_target = await bridge.visible_handoffs.binding_readiness(
            "chatgpt", "grok", binding, {"text": "› "}
        )
        assert wrong_target["state"] == "target_changed"
    token = bridge.sessions._observation.set(captured)
    try:
        with pytest.raises(BridgeError, match="scope changed or expired"):
            await bridge.sessions.observed_selected("chatgpt", row["pane_id"], 900)
    finally:
        bridge.sessions._observation.reset(token)
    assert not calls
    assert await bridge.sessions.observed_selected("chatgpt", row["pane_id"], 900) == row
    assert len(calls) == 1  # A subsequent operation must select freshly.


async def test_check_target_reuses_only_its_fresh_selection_for_read_and_readiness(
    visible,  # noqa: F811
    monkeypatch,
):
    from kirabridge.session_manager import SessionManager

    bridge, _ = visible
    row = new_row()
    _, binding = bridge.sessions.explicit_agent_binding(row)
    calls = []

    async def selected(*args):
        calls.append(args)
        return deepcopy(row)

    async def read(pane):
        return "› "

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions, "read", SessionManager.read.__get__(bridge.sessions))
    assert (await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True))[
        "text"
    ] == "› "
    assert len(calls) == 1
    row["processes"][-1]["pid"] = 902
    with pytest.raises(BridgeError, match="Bound CLI process"):
        await bridge.visible_handoffs.check_target("chatgpt", "codex", binding, ready=True)
    assert len(calls) == 2
