"""Real terminal guards and original task authority against isolated protocol/JXA peers."""

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit
from test_terminal_input_authority import Native

from kirabridge.bridge_core.models import BridgeError
from kirabridge.desktop_input import DesktopInput
from kirabridge.keyboard_manager import KeyboardManager
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.session_manager import SessionInput, SessionManager
from kirabridge.terminal_input import TerminalNativeInput

OLD = f"{os.getuid()} ttys004 Sun Nov 1 12:00:00 2026 344 /bin/zsh"
NEW = OLD.replace("12:00:00", "12:00:01")


class LiteralProtocol(Native):
    """Own synthetic native peer; echo the actual staged Unicode, never execute it."""

    def __init__(self, on_type):
        super().__init__(SimpleNamespace(text=""))
        self.on_type, self.units, self.typed, self.returns = on_type, bytearray(), [], 0

    async def request(self, operation, args, **options):
        if operation.endswith(".chunk"):
            self.units.extend(base64.b64decode(args["data_b64"], validate=True))
        result = await super().request(operation, args, **options)
        if operation.endswith(".commit"):
            text = self.units.decode("utf-16-le")
            assert hashlib.sha256(text.encode()).hexdigest() == self.manifest["sha256"]
            self.typed.append(text)
            self.shell.text = self.on_type(text)
            result["value_sha256"] = hashlib.sha256(self.shell.text.encode()).hexdigest()
            result["selection_utf16"] = {
                "location": len(self.shell.text.encode("utf-16-le")) // 2,
                "length": 0,
            }
        if operation == "terminal.input.return":
            self.returns += 1
        return result


def wire_submit(bridge, manager, protocol=None):
    manager.native_input = TerminalNativeInput(
        KeyboardManager(
            transport=protocol,
            desktop_input=(
                bridge.desktop_input if manager is bridge.sessions else DesktopInput(manager.lock)
            ),
            authorize=bridge.security.authorize,
        ),
        bridge.security,
    )


def accepted_input(bridge, args, *, task_id="owned-native-input", principal="local"):
    bridge.tasks.preflight = None
    value = request("session.input", args.model_dump(), task_id=task_id)
    submit(bridge, value, principal)
    task = bridge.store.claim_exact(bridge.tasks.owner, bridge.config.lease_seconds, task_id)
    assert task is not None and task["request_sha256"]
    return task_id


def native_manager(monkeypatch, bridge, config):
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    current = {"identity": OLD, "calls": [], "screen": "KiraBridge visible % "}
    native = TerminalAppTransport(asyncio.Lock(), desktop=object())
    native.process_identity = AsyncMock(return_value=OLD)
    native.process_working_directory = AsyncMock(return_value="/owned")
    native.read = AsyncMock(side_effect=lambda _: current["screen"])
    row = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "tty": "/dev/ttys004",
        "window_id": 123,
        "visual_window_id": 10621,
        "tab_count": 1,
        "selection_ambiguous": False,
        "identity_ambiguous": False,
        "process_owner_verified": True,
        "processes": [{"pid": 345, "ppid": 344, "name": "zsh", "image": "/bin/zsh"}],
        "busy": False,
        "transport": "terminal_app",
    }
    native.catalog = AsyncMock(return_value=[row])
    native.last_catalog_incomplete = False

    async def execute(source, *, mutation=False):
        script = (
            r"""
const vm=require('node:vm'),calls=[];
const tab={tty:()=>'/dev/ttys004',busy:()=>false,history:()=>SCREEN};
const win={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab};
function windows(){return [win];}windows.byId=()=>win;
const app={running:()=>true,windows,activate:()=>{},doScript:text=>calls.push(text)};
function Application(name){return name==='System Events'?
 {processes:{byName:()=>({frontmost:()=>true})}}:app;}
Application.currentApplication=()=>({doShellScript:c=>c.includes('lsof')?'p345\nfcwd\nn/owned':IDENTITY});
let result,error;try{result=JSON.parse(vm.runInNewContext(SOURCE,{Application,delay:()=>{}}));}
catch(e){error=e.message;}process.stdout.write(JSON.stringify({result,error,calls}));
""".replace("IDENTITY", json.dumps(current["identity"]))
            .replace("SCREEN", json.dumps(current["screen"]))
            .replace("SOURCE", json.dumps(source))
        )
        completed = await asyncio.to_thread(
            subprocess.run, [node, "-e", script], capture_output=True, text=True, timeout=3
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        current["calls"].extend(result["calls"])
        if result.get("error"):
            raise BridgeError("visible_target_changed", result["error"])
        return result["result"]

    monkeypatch.setattr(native, "native", execute)
    manager = SessionManager(bridge.sessions.ports, terminal_app=native)
    manager.selected = AsyncMock(return_value=row)

    def typed(text):
        current["screen"] += text
        return current["screen"]

    protocol = LiteralProtocol(typed)
    wire_submit(bridge, manager, protocol)
    return manager, native, current, protocol


async def test_reused_native_pid_cannot_receive_non_direct_submit(monkeypatch, bridge, config):
    manager, native, current, protocol = native_manager(monkeypatch, bridge, config)
    args = SessionInput(pane_id="terminal:123:ttys004", expected_pid=345, text="write once")
    task_id = accepted_input(bridge, args)

    async def replace_process():
        current["identity"] = NEW

    with pytest.raises(BridgeError) as error:
        await manager.send("local", args, task_id=task_id, before_transport=replace_process)
    assert error.value.code == "visible_target_changed"
    assert current["calls"] == protocol.calls == []
    native.process_identity.assert_awaited_once_with(345, detailed=True)


async def test_unchanged_native_process_types_exact_literal_then_one_guarded_return(
    monkeypatch, bridge, config
):
    manager, _, current, protocol = native_manager(monkeypatch, bridge, config)
    text = '/bin/echo "quoted ä😀"'
    args = SessionInput(
        pane_id="terminal:123:ttys004", expected_pid=345, text=text, require_idle=True
    )
    task_id = accepted_input(bridge, args)
    intent = AsyncMock()
    result = await manager.send("local", args, task_id=task_id, before_transport=intent)
    assert result["submitted"] and protocol.typed == [text] and protocol.returns == 1
    assert current["calls"] == []  # No doScript submit, for non-direct principals either.
    assert (
        protocol.manifest["owner"]["request_sha256"] == bridge.store.get(task_id)["request_sha256"]
    )
    assert protocol.manifest["owner"]["operation"] == "session.input"
    intent.assert_awaited_once()


async def test_process_moved_to_another_tty_is_refused_before_input_intent(
    monkeypatch, bridge, config
):
    manager, native, current, protocol = native_manager(monkeypatch, bridge, config)
    native.process_identity.return_value = OLD.replace("ttys004", "ttys005")
    args = SessionInput(pane_id="terminal:123:ttys004", expected_pid=345, text="write once")
    task_id = accepted_input(bridge, args)
    intent = AsyncMock()
    with pytest.raises(BridgeError) as error:
        await manager.send("local", args, task_id=task_id, before_transport=intent)
    assert error.value.code == "visible_target_changed" and current["calls"] == protocol.calls == []
    intent.assert_not_awaited()


async def test_unbound_native_send_cannot_bypass_original_task_or_turn(monkeypatch, bridge, config):
    _, native, current, protocol = native_manager(monkeypatch, bridge, config)
    with pytest.raises(BridgeError) as error:
        await native.send("terminal:123:ttys004", "write once", submit=True, require_idle=False)
    assert (
        error.value.code == "terminal_authority_required"
        and current["calls"] == protocol.calls == []
    )
