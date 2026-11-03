"""Execute native submit guards against a private JavaScript Terminal stub."""

import asyncio
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.session_manager import SessionInput, SessionManager
from kirabridge.session_ports import SessionPorts

OLD = f"{os.getuid()} ttys004 Sun Nov 1 12:00:00 2026 344 /bin/zsh"
NEW = OLD.replace("12:00:00", "12:00:01")


def native_manager(monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    current = {"identity": OLD, "calls": []}
    native = TerminalAppTransport(asyncio.Lock(), desktop=object())
    native.process_identity = AsyncMock(return_value=OLD)

    async def execute(source, *, mutation=False):
        assert mutation is True
        script = """
const vm=require('node:vm');
const calls=[];
const tab={tty:()=>'/dev/ttys004',busy:()=>false};
const win={id:()=>123,tabs:()=>[tab]};
function windows(){return [win];} windows.byId=()=>win;
const app={running:()=>true,windows:windows,doScript:(text)=>calls.push(text)};
function Application(name){if(name!=='Terminal')throw Error('Unexpected app');return app;}
Application.currentApplication=()=>({doShellScript:()=>IDENTITY});
let result,error;
try{result=JSON.parse(vm.runInNewContext(SOURCE,{Application}));}
catch(e){error=e.message;}
process.stdout.write(JSON.stringify({result,error,calls}));
""".replace("IDENTITY", json.dumps(current["identity"])).replace("SOURCE", json.dumps(source))
        completed = await asyncio.to_thread(
            subprocess.run, [node, "-e", script], capture_output=True, text=True, timeout=3
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        current["calls"].extend(result["calls"])
        if result.get("error"):
            assert "Selected target identity changed" in result["error"]
            raise BridgeError("visible_target_changed", result["error"])
        return result["result"]

    monkeypatch.setattr(native, "native", execute)
    release = SimpleNamespace(
        dispatch=Mock(side_effect=lambda principal, args, task: args), sent=Mock()
    )
    manager = SessionManager(
        SessionPorts(
            authorization=SimpleNamespace(principal=Mock()),
            input_release=release,
            audit=None,
            environment={},
            agent_registry=lambda: ({}, {}),
            clipboard_lock=asyncio.Lock(),
            visible_required=lambda _: False,
        ),
        terminal_app=native,
    )
    manager.selected = AsyncMock(
        return_value={
            "pane_id": "terminal:123:ttys004",
            "expected_pid": 345,
            "tty": "/dev/ttys004",
            "busy": False,
            "transport": "terminal_app",
        }
    )
    return manager, native, release, current


async def test_reused_native_pid_cannot_receive_non_direct_submit(monkeypatch):
    manager, native, release, current = native_manager(monkeypatch)

    async def replace_process():
        current["identity"] = NEW

    with pytest.raises(BridgeError) as error:
        await manager.send(
            "local",
            SessionInput(pane_id="terminal:123:ttys004", expected_pid=345, text="write once"),
            before_transport=replace_process,
        )

    assert error.value.code == "visible_target_changed"
    assert current["calls"] == []
    native.process_identity.assert_awaited_once_with(345, detailed=True)
    release.sent.assert_not_called()


async def test_unchanged_native_process_keeps_do_script_input_semantics(monkeypatch):
    manager, native, release, current = native_manager(monkeypatch)
    text = 'quoted "text"\nand second line'
    intent = AsyncMock()

    result = await manager.send(
        "local",
        SessionInput(
            pane_id="terminal:123:ttys004", expected_pid=345, text=text, require_idle=True
        ),
        before_transport=intent,
    )

    assert result["submitted"] is True
    assert current["calls"] == [text]
    intent.assert_awaited_once()
    native.process_identity.assert_awaited_once_with(345, detailed=True)
    release.sent.assert_called_once()


async def test_process_moved_to_another_tty_is_refused_before_input_intent(monkeypatch):
    manager, native, release, current = native_manager(monkeypatch)
    native.process_identity.return_value = OLD.replace("ttys004", "ttys005")
    intent = AsyncMock()

    with pytest.raises(BridgeError) as error:
        await manager.send(
            "local",
            SessionInput(pane_id="terminal:123:ttys004", expected_pid=345, text="write once"),
            before_transport=intent,
        )

    assert error.value.code == "visible_target_changed"
    assert current["calls"] == []
    intent.assert_not_awaited()
    release.sent.assert_not_called()


async def test_native_send_requires_a_process_identity_even_without_idle_check(monkeypatch):
    _, native, _, current = native_manager(monkeypatch)
    with pytest.raises(BridgeError) as error:
        await native.send("terminal:123:ttys004", "write once", submit=True, require_idle=False)
    assert error.value.code == "visible_selection_required"
    assert current["calls"] == []
