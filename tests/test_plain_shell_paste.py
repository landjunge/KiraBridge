"""Mocked native transport only; no host Terminal, clipboard, config or process probes."""

import os
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionInput


@pytest.fixture
def plain(bridge, config, monkeypatch):
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    row = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 900,
        "tty": "/dev/ttys004",
        "transport": "terminal_app",
        "busy": False,
        "visual_window_id": 10621,
        "tab_count": 1,
        "identity_ambiguous": False,
        "selection_ambiguous": False,
        "process_owner_verified": True,
        "processes": [{"pid": 900, "ppid": 800, "name": "zsh", "image": "/bin/zsh"}],
    }
    snapshot = {
        "command": ["/bin/ps", "-t", "ttys004", "-o", "uid=,pid=,ppid=,tty=,lstart=,comm="],
        "rows": sorted(
            [
                f"{os.getuid()} 900 800 ttys004 Sat Oct 24 12:00:00 2026 /bin/zsh",
                "0 800 1 ttys004 Sat Oct 24 11:00:00 2026 /usr/bin/login",
            ]
        ),
    }
    monkeypatch.setattr(bridge.sessions, "selected", AsyncMock(return_value=row))
    monkeypatch.setattr(
        bridge.sessions.terminal_app, "shell_process_snapshot", AsyncMock(return_value=snapshot)
    )
    monkeypatch.setattr(
        bridge.sessions.terminal_app, "read", AsyncMock(return_value="KiraBridge fixture % ")
    )
    native = AsyncMock(return_value={"paste_event_sent": True, "return_sent": False})
    monkeypatch.setattr(bridge.sessions.terminal_app, "native", native)
    return bridge.sessions, row, snapshot, native


def arguments(text="# harmless ä🧠"):
    return SessionInput(pane_id="terminal:123:ttys004", expected_pid=900, text=text, submit=False)


async def test_plain_paste_uses_guarded_literal_insert_without_return(plain):
    sessions, row, snapshot, native = plain
    events = []

    async def intent():
        assert sessions.terminal_app.read.await_count == 1
        assert sessions.terminal_app.shell_process_snapshot.await_count == 1
        assert not native.called
        events.append("durable-intent")

    result = await sessions.send("local", arguments(), before_transport=intent)
    assert events == ["durable-intent"] and result["paste_event_sent"]
    assert (
        not result["return_sent"] and not result["submitted"] and not result["execution_confirmed"]
    )
    source = native.call_args.args[0]
    assert 'paste.actions.byName("AXPress").perform()' in source
    assert "app.doScript" not in source and "keyCode(36)" not in source
    assert "shellRows" in source and "if(tab.busy())" in source
    assert "checkTargetIdentity" in source and "expected_pid" not in source
    assert "Selected terminal input changed" in source and "checkClipboard" in source
    assert source.index("const shellRows") < source.index("paste.actions.byName")
    assert source.index("if(tab.busy())") < source.index(
        "checkFocus(); checkClipboard();", source.index("const shellRows")
    )
    assert "0 ttys004 Sat Oct 24 11:00:00 2026 1 /usr/bin/login" in source


@pytest.mark.parametrize(
    "text",
    ["a\nb", "a\rb", "a\tb", "\x1b[1A", "a\x00b", "a\x7fb", "a\u0085b", "a\u009bb", "a\u2028b", ""],
)
async def test_control_or_multiline_paste_refuses_before_intent(plain, text):
    sessions, _, _, native = plain
    intent = AsyncMock()
    with pytest.raises((BridgeError, ValidationError)):
        await sessions.send("local", arguments(text), before_transport=intent)
    intent.assert_not_awaited()
    native.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "busy",
        "nonempty",
        "agent",
        "stale-image",
        "stale-parent",
        "foreign-job",
        "extra-own-process",
        "stale-tty",
        "missing",
    ],
)
async def test_unknown_or_changed_shell_refuses_before_intent(plain, change):
    sessions, row, snapshot, native = plain
    if change == "busy":
        row["busy"] = True
    elif change == "nonempty":
        sessions.terminal_app.read.return_value = "KiraBridge fixture % user input"
    elif change == "agent":
        row["processes"].append({"pid": 901, "ppid": 900, "name": "codex", "image": "/bin/codex"})
    elif change == "stale-image":
        snapshot["rows"] = [s.replace("/bin/zsh", "/bin/bash") for s in snapshot["rows"]]
    elif change == "stale-parent":
        snapshot["rows"] = [s.replace("900 800", "900 801") for s in snapshot["rows"]]
    elif change == "foreign-job":
        snapshot["rows"].append("0 950 800 ttys004 Sat Oct 24 12:00:00 2026 /bin/zsh")
    elif change == "extra-own-process":
        snapshot["rows"].append(
            f"{os.getuid()} 950 900 ttys004 Sat Oct 24 12:00:00 2026 /bin/sleep"
        )
    elif change == "stale-tty":
        snapshot["rows"] = [s.replace("ttys004", "ttys005") for s in snapshot["rows"]]
    else:
        snapshot["rows"] = []
    intent = AsyncMock()
    with pytest.raises(BridgeError):
        await sessions.send("local", arguments(), before_transport=intent)
    intent.assert_not_awaited()
    native.assert_not_awaited()


async def test_callback_failure_prevents_all_transport(plain):
    sessions, _, _, native = plain
    intent = AsyncMock(side_effect=RuntimeError("Intent journal unavailable"))
    with pytest.raises(RuntimeError):
        await sessions.send("local", arguments(), before_transport=intent)
    intent.assert_awaited_once()
    native.assert_not_awaited()


async def test_theme_prompt_plain_paste_uses_shared_empty_prompt_check(plain):
    sessions, _, _, native = plain
    sessions.terminal_app.read.return_value = "➜  ~ \n\n"
    result = await sessions.send("local", arguments())
    assert result["paste_event_sent"] and not result["return_sent"]
    native.assert_awaited_once()


async def test_input_policy_refusal_prevents_intent_and_transport(plain, monkeypatch):
    sessions, _, _, native = plain

    def denied(*args):
        raise BridgeError("approval_required", "Policy refused")

    monkeypatch.setattr(sessions.input_release, "dispatch", denied)
    intent = AsyncMock()
    with pytest.raises(BridgeError, match="Policy refused"):
        await sessions.send("local", arguments(), before_transport=intent)
    intent.assert_not_awaited()
    native.assert_not_awaited()


@pytest.mark.parametrize("ready", [True, False])
async def test_agent_insert_callback_follows_readiness_checks(plain, monkeypatch, ready):
    sessions, _, _, native = plain
    monkeypatch.setattr(sessions, "selected_identities", lambda row: {900: "bound identity"})
    sessions.readiness = AsyncMock(return_value={"ready": ready})
    intent = AsyncMock()
    if ready:
        await sessions.insert("local", arguments(), before_transport=intent)
        intent.assert_awaited_once()
        native.assert_awaited_once()
    else:
        with pytest.raises(BridgeError, match="not ready"):
            await sessions.insert("local", arguments(), before_transport=intent)
        intent.assert_not_awaited()
        native.assert_not_awaited()


async def test_agent_insert_callback_failure_blocks_native(plain, monkeypatch):
    sessions, _, _, native = plain
    monkeypatch.setattr(sessions, "selected_identities", lambda row: {900: "bound identity"})
    sessions.readiness = AsyncMock(return_value={"ready": True})
    with pytest.raises(RuntimeError):
        await sessions.insert(
            "local", arguments(), before_transport=AsyncMock(side_effect=RuntimeError("journal"))
        )
    native.assert_not_awaited()


@pytest.mark.parametrize("failure", ["nonzero", "stderr", "empty"])
async def test_shell_snapshot_requires_positive_complete_os_observation(
    plain, monkeypatch, failure
):
    from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

    sessions, _, _, native = plain
    child = type("Child", (), {})()
    child.returncode = 1 if failure == "nonzero" else 0
    child.wait = AsyncMock(return_value=child.returncode)
    child.stdin = child.stdout = child.stderr = None
    child.communicate = AsyncMock(
        return_value=(
            b"" if failure == "empty" else b"501 900 800 ttys004 Sat Oct 24 12:00:00 2026 /bin/zsh",
            b"permission denied" if failure == "stderr" else b"",
        )
    )
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    with pytest.raises(BridgeError, match="unavailable"):
        await TerminalAppTransport.shell_process_snapshot(sessions.terminal_app, "/dev/ttys004")
    native.assert_not_awaited()


async def test_plain_paste_native_script_compiles_without_executing_ui(plain, tmp_path):
    import shutil
    import subprocess

    sessions, _, _, native = plain
    await sessions.send("local", arguments())
    source = tmp_path / "native-paste.js"
    source.write_text(native.call_args.args[0])
    compiler = shutil.which("osacompile") or shutil.which("node")
    if compiler is None:
        pytest.skip("No syntax compiler available")
    command = [compiler, "-l", "JavaScript", "-o", str(tmp_path / "syntax.scpt"), str(source)]
    if compiler.endswith("node"):
        command = [compiler, "--check", str(source)]
    import asyncio

    compiled = await asyncio.to_thread(
        subprocess.run, command, capture_output=True, text=True, timeout=10
    )
    assert compiled.returncode == 0, compiled.stderr


async def test_submitted_direct_shell_checks_input_before_intent(plain, monkeypatch, bridge):
    from test_native_send_identity import accepted_input

    sessions, _, _, native = plain
    monkeypatch.setattr(sessions, "direct", lambda principal: True)
    monkeypatch.setattr(
        sessions.terminal_app,
        "process_identity",
        AsyncMock(return_value=f"{os.getuid()} ttys004 Sat Oct 24 12:00:00 2026 800 /bin/zsh"),
    )
    monkeypatch.setattr(
        sessions.terminal_app, "process_working_directory", AsyncMock(return_value="/owned")
    )
    sessions.terminal_app.read.return_value = "KiraBridge fixture % unfinished user text"
    intent = AsyncMock()
    args = arguments().model_copy(update={"submit": True})
    task_id = accepted_input(bridge, args)
    with pytest.raises(BridgeError) as failure:
        await sessions.send("local", args, task_id=task_id, before_transport=intent)
    assert failure.value.code == "visible_input_not_empty"
    intent.assert_not_awaited()
    native.assert_not_awaited()


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_native_shell_snapshot_parser_accepts_macos_line_endings(separator, tmp_path):
    import json
    import shutil
    import subprocess

    from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

    rows = [
        "0 800 1 ttys004 Sat Oct 24 11:00:00 2026 /usr/bin/login",
        f"{os.getuid()} 900 800 ttys004 Sat Oct 24 12:00:00 2026 /bin/zsh",
    ]
    snapshot = {"rows": sorted(rows), "command": ["/bin/ps", "-t", "ttys004"]}
    # JXA's StandardAdditions.doShellScript returns CR on macOS, unlike subprocess stdout.
    source = (
        "const identityHost={doShellScript:()=>"
        + json.dumps(separator.join(rows) + separator)
        + "};const tab={busy:()=>false};"
    )
    source += TerminalAppTransport.native_shell_guard(snapshot)
    compiler = shutil.which("osascript")
    if compiler:
        source += "JSON.stringify({matched:true});"
        result = subprocess.run(
            [compiler, "-l", "JavaScript", "-"],
            input=source,
            capture_output=True,
            text=True,
            timeout=5,
        )
    else:
        node = shutil.which("node")
        if not node:
            pytest.skip("No isolated JavaScript runtime")
        source += "process.stdout.write(JSON.stringify({matched:true}));"
        result = subprocess.run(
            [node, "-"], input=source, capture_output=True, text=True, timeout=5
        )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"matched": True}


@pytest.mark.parametrize("effective", ["# harmless", "# first\n# second"])
async def test_plain_shell_validates_effective_text_after_actual_buffer_framing(
    plain, bridge, config, effective
):
    from conftest import request

    from kirabridge.bridge_core.models import State

    sessions, _, _, native = plain
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].approval_mode = "automatic"
    args = arguments(effective + "\ngo-go-go\n")
    task = request("session.input", args.model_dump(), task_id="framed-paste")
    bridge.prepare("local", task)
    claimed = bridge.store.claim("fixture-worker", 30)
    assert claimed["id"] == task.task_id
    bridge.store.transition(task.task_id, State.RUNNING, {"fixture": True}, owner="fixture-worker")
    intent = AsyncMock()
    if "\n" in effective:
        with pytest.raises(BridgeError, match="single-line"):
            await sessions.send("local", args, task_id=task.task_id, before_transport=intent)
        intent.assert_not_awaited()
        native.assert_not_awaited()
    else:
        await sessions.send("local", args, task_id=task.task_id, before_transport=intent)
        intent.assert_awaited_once()
        source = native.call_args.args[0]
        assert "go-go-go" not in source and effective in source
        assert "keyCode(36)" not in source and "app.doScript" not in source
