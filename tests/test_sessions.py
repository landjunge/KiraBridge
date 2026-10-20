import asyncio
import shutil
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionInput, SessionManager, SessionOpen


async def test_native_catalog_binds_window_tty_and_unambiguous_root_pid(bridge, monkeypatch):
    monkeypatch.setattr("kirabridge.session_manager.sys", SimpleNamespace(platform="darwin"))
    manager = SessionManager(bridge)

    async def native(*args, **kwargs):
        return [
            {"window_id": 123, "tty": "/dev/ttys004", "busy": True},
            {"window_id": 124, "tty": "/dev/ttys005", "busy": False},
        ]

    async def communicate():
        return (
            b"345 1 ttys004 /usr/bin/login\n346 345 ttys004 /bin/zsh\n"
            b"347 346 ttys004 /private/path/codex\n"
            b"400 1 ttys005 /bin/zsh\n401 1 ttys005 /bin/zsh\n",
            b"",
        )

    async def process(*args, **kwargs):
        return SimpleNamespace(communicate=communicate)

    monkeypatch.setattr(manager, "native", native)
    monkeypatch.setattr("kirabridge.session_manager.asyncio.create_subprocess_exec", process)
    rows = await manager.terminal_catalog()
    assert len(rows) == 1  # Two possible roots on ttys005 must not be guessed.
    assert rows[0]["pane_id"] == "terminal:123:ttys004"
    assert rows[0]["expected_pid"] == 345
    assert rows[0]["processes"][-1] == {"pid": 347, "ppid": 346, "name": "codex"}


async def test_idle_only_input_rejects_busy_target_before_transport(bridge, config, monkeypatch):
    config.principals["local"].capabilities += ["session.inspect"]
    target = {"pane_id": "terminal:123:ttys004", "expected_pid": 345, "busy": True}

    async def catalog(principal):
        return {"sessions": [target]}

    async def no_transport(*args, **kwargs):
        pytest.fail("busy target must never receive input")

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "native", no_transport)
    with pytest.raises(BridgeError, match="idle shell"):
        await bridge.sessions.send(
            "local",
            SessionInput(
                pane_id=target["pane_id"],
                expected_pid=345,
                text="printf harmless",
                require_idle=True,
            ),
        )


@pytest.mark.asyncio
async def test_exact_session_input_and_capture_on_private_real_tmux(bridge, config, tmp_path):
    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux not installed")
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    bridge.terminal.environment["PATH"] = (
        str(__import__("pathlib").Path(tmux).parent) + ":" + bridge.terminal.environment["PATH"]
    )
    socket = "kb-test-" + uuid.uuid4().hex
    manager = SessionManager(bridge, socket_name=socket)
    fixture = tmp_path / "receiver.py"
    fixture.write_text(
        "import time\nprint('SESSION_READY',flush=True)\nline=input()\n"
        "print('RECEIVED:'+line,flush=True)\ntime.sleep(10)\n"
    )
    await asyncio.to_thread(
        subprocess.run,
        [tmux, "-L", socket, "new-session", "-d", "-s", "fixture", sys.executable, str(fixture)],
        check=True,
    )
    try:
        listed = await manager.catalog("local")
        selected = listed["sessions"][0]
        args = SessionInput(
            pane_id=selected["pane_id"],
            expected_pid=selected["expected_pid"],
            text="harmless session test",
        )
        with pytest.raises(BridgeError):
            await manager.send("other", args)
        with pytest.raises(BridgeError, match="exact current"):
            await manager.send(
                "local", args.model_copy(update={"expected_pid": args.expected_pid + 100000})
            )
        sent = await manager.send("local", args)
        assert sent["input_handed_to_transport"] and not sent["agent_processed"]
        async with asyncio.timeout(3):
            while True:
                captured = await manager.read("local", args.pane_id, args.expected_pid)
                if "RECEIVED:harmless session test" in captured["text"]:
                    break
                await asyncio.sleep(0.03)
    finally:
        await asyncio.to_thread(subprocess.run, [tmux, "-L", socket, "kill-server"], check=False)


@pytest.mark.asyncio
async def test_native_session_selection_read_and_input(bridge, config, monkeypatch):
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    manager = SessionManager(bridge)
    selected = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "tty": "/dev/ttys004",
        "transport": "terminal_app",
    }
    calls = []

    async def catalog(principal):
        bridge.security.principal(principal, "session.inspect")
        return {"sessions": [selected]}

    async def native(source, *, mutation=False):
        calls.append((source, mutation))
        return "read-output" if not mutation else {"sent": True}

    monkeypatch.setattr(manager, "catalog", catalog)
    monkeypatch.setattr(manager, "native", native)
    with pytest.raises(BridgeError, match="exact current"):
        await manager.read("local", selected["pane_id"], 346)
    assert not calls
    result = await manager.read("local", selected["pane_id"], 345)
    assert result["text"] == "read-output"
    args = SessionInput(
        **{k: selected[k] for k in ("pane_id", "expected_pid")}, text='hello "quoted"\nline'
    )
    with pytest.raises(BridgeError, match="submits a line"):
        await manager.send("local", args.model_copy(update={"submit": False}))
    sent = await manager.send("local", args)
    assert sent["input_handed_to_transport"] and not sent["agent_processed"]
    assert calls[-1][1] is True
    assert 'hello \\"quoted\\"\\nline' in calls[-1][0]


@pytest.mark.asyncio
async def test_native_open_checks_authority_and_quotes_command(bridge, config, monkeypatch):
    manager = SessionManager(bridge)
    calls = []

    async def native(source, *, mutation=False):
        calls.append(source)
        return {"opened": True, "tty": "/dev/ttys009"}

    async def catalog():
        return [{"pane_id": "terminal:333:ttys009", "expected_pid": 444, "tty": "/dev/ttys009"}]

    monkeypatch.setattr(manager, "native", native)
    monkeypatch.setattr(manager, "terminal_catalog", catalog)
    with pytest.raises(BridgeError):
        await manager.open("local", SessionOpen(cwd="/"))
    assert not calls
    cwd = config.principals["local"].roots[0]
    args = SessionOpen(cwd=cwd, argv=[sys.executable, "-c", "print('hello')"])
    token = bridge.security.grant_window("local", "explicit-new-window", args)
    args = args.model_copy(update={"window_authorization": token})
    with bridge.store.transaction():
        bridge.security.consume_window("local", "explicit-new-window", args)
    result = await manager.open("local", args, task_id="explicit-new-window")
    assert result["opened"] and result["expected_pid"] == 444
    assert len(calls) == 1 and "app.doScript" in calls[0]
    with pytest.raises(BridgeError) as exc:
        await manager.open("local", args, task_id="explicit-new-window")
    assert exc.value.code == "window_already_dispatched" and len(calls) == 1


@pytest.mark.parametrize(
    "argv", [[], ["codex"], ["/bin/sh", "-c", "grok"], ["/usr/bin/osascript", "-e", "anything"]]
)
async def test_no_window_for_shell_or_wrapper_without_trusted_operator_grant(
    bridge, config, monkeypatch, argv
):
    calls = []

    async def native(*args, **kwargs):
        calls.append(args)
        raise AssertionError("No window creation allowed")

    monkeypatch.setattr(bridge.sessions, "native", native)
    args = SessionOpen(
        cwd=config.principals["local"].roots[0],
        argv=argv,
        window_authorization="agent-claims-user-approved",
    )
    with pytest.raises(BridgeError) as exc:
        await bridge.sessions.open("local", args, task_id="untrusted")
    assert exc.value.code == "window_request_required"
    assert not calls


def test_window_grant_is_bound_to_exact_request_principal_and_task(bridge, config):
    args = SessionOpen(cwd=config.principals["local"].roots[0])
    token = bridge.security.grant_window("local", "explicit-window", args)
    authorized = args.model_copy(update={"window_authorization": token})
    for principal, task_id, changed in [
        ("other", "explicit-window", authorized),
        ("local", "different-window", authorized),
        ("local", "explicit-window", authorized.model_copy(update={"argv": ["grok"]})),
    ]:
        with bridge.store.transaction(), pytest.raises(BridgeError):
            bridge.security.consume_window(principal, task_id, changed)
    with bridge.store.transaction():
        bridge.security.consume_window("local", "explicit-window", authorized)
    with bridge.store.transaction(), pytest.raises(BridgeError):
        bridge.security.consume_window("local", "explicit-window", authorized)


async def test_expired_window_grant_cannot_reach_the_transport(bridge, config, monkeypatch):
    args = SessionOpen(cwd=config.principals["local"].roots[0])
    token = bridge.security.grant_window("local", "expired-window", args)
    args = args.model_copy(update={"window_authorization": token})
    with bridge.store.transaction():
        bridge.security.consume_window("local", "expired-window", args)
        bridge.store.db.execute("UPDATE approvals SET expires=0 WHERE task_id='expired-window'")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Expired grant must not start any window")

    monkeypatch.setattr(bridge.sessions, "native", forbidden)
    with pytest.raises(BridgeError) as exc:
        await bridge.sessions.open("local", args, task_id="expired-window")
    assert exc.value.code == "window_request_required"


@pytest.mark.parametrize("action", ["insert", "return"])
async def test_native_two_step_scripts_compile_without_executing_ui(
    bridge, monkeypatch, tmp_path, action
):
    compiler = shutil.which("osacompile") or shutil.which("node")
    if not compiler:
        pytest.skip("No JavaScript syntax compiler available")
    scripts = []

    async def selected(*args):
        return {"pane_id": "terminal:123:ttys004", "expected_pid": 345}

    async def capture(source, **kwargs):
        scripts.append(source)
        return {}

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "native", capture)
    if action == "insert":
        await bridge.sessions.insert(
            "local",
            SessionInput(
                pane_id="terminal:123:ttys004",
                expected_pid=345,
                text='Quoted " ä🙂\\\nKB-END-static',
                submit=False,
            ),
        )
    else:
        await bridge.sessions.press_return("local", "terminal:123:ttys004", 345)
    source = tmp_path / "native.js"
    source.write_text(scripts[0])
    command = [compiler, "-l", "JavaScript", "-o", str(tmp_path / "compiled.scpt"), str(source)]
    if compiler.endswith("node"):
        command = [compiler, "--check", str(source)]
    compiled = await asyncio.to_thread(
        subprocess.run, command, capture_output=True, text=True, timeout=10
    )
    assert compiled.returncode == 0, compiled.stderr
