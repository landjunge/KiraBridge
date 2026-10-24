"""Current explicit selection is per task; old uncertainty is never rebound/replayed."""

import asyncio
import os
from copy import deepcopy

import pytest
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical, digest
from kirabridge.session_manager import SessionInput


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


async def new_selection(bridge, monkeypatch, row):
    original = bridge.sessions.selected

    async def selected(principal, pane, pid):
        if pane == row["pane_id"] and pid == row["expected_pid"]:
            return deepcopy(row)
        return await original(principal, pane, pid)

    monkeypatch.setattr(bridge.sessions, "selected", selected)


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
        before_paste = calls[0].split("paste.click();", 1)[0]
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
