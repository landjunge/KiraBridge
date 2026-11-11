"""The actual product open path against synthetic AX/CG and JavaScript objects."""

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

ROOT = Path(__file__).resolve().parents[1]
NONCE = "0123456789abcdef0123456789abcdef"
TITLE = "KiraBridge_" + NONCE


def fixture_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"tests/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def product(tmp_path, monkeypatch):
    fixture = fixture_module("test_codex_window_isolation")
    fixture.TITLE = TITLE
    scene = fixture.Scene(SimpleNamespace(PhysicalIsolation=lambda *a, **kw: None), tmp_path)
    original_groups = scene.groups

    def groups():
        result = original_groups()
        if scene.phase in {"created", "tagged"} and not scene.already_isolated:
            result = [(777, title, count) for _, title, count in result]
        return [(777 if number == 888 else number, title, count) for number, title, count in result]

    scene.groups = groups
    leaf = TerminalAppTransport(asyncio.Lock(), desktop=object())
    leaf.system_transport = SimpleNamespace(request=scene.request)
    leaf.window_inventory = scene.terminal.window_inventory
    leaf.process_identity = scene.terminal.process_identity
    leaf.process_working_directory = scene.terminal.process_working_directory
    scene.no_own_group = True
    events = []
    receipt = {
        "opened": True,
        "tty": fixture.CREATED["tty"],
        "window_id": 123,
        "nonce": TITLE,
        "app_pid": 775,
        "app_identity": fixture.TERMINAL,
        "creation_bound": True,
        "tagged": True,
        "script_tab_count": 1,
    }

    async def native(source, *, mutation):
        assert mutation is True
        if "const tab=app.doScript(" in source:
            events.append("create")
            scene.created()
            scene.phase = "tagged"
            return deepcopy(receipt)
        if "entries[0].click()" in source:
            events.append("move")
            assert events.index("receipt") < events.index("move")
            scene.phase = "detached"
            if scene.unknown_move:
                raise UncertainExecution("session_input_unknown", "Lost menu result")
            return {"detached": True}
        events.append("focus")
        return {"focused": True}

    leaf.native = AsyncMock(side_effect=native)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.secrets.token_hex", lambda n: NONCE
    )

    async def created(value):
        assert value == receipt and "physical_window" not in value
        events.append("receipt")

    return scene, leaf, events, receipt, created


async def test_product_open_records_creation_before_one_move_and_pins_native_ids(product):
    scene, leaf, events, receipt, created = product
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert events == ["create", "receipt", "focus", "move"]
    assert result["separate_window"] and result["physical_window"]["own_tabbar_hidden"]
    assert result["physical_window"]["cg_window_id"] == 777 != receipt["window_id"]
    scene.groups = lambda: [(231, "live CLI title changed", 3), (777, "OSC replaced nonce", None)]
    await leaf.verify_opened(
        result, principal="chatgpt"
    )  # no title adoption after the original native binding
    request = leaf.system_transport.request

    async def resized_own(operation, arguments, **kwargs):
        value = await request(operation, arguments, **kwargs)
        if operation == "windows.list":
            next(w for w in value["windows"] if w["window_id"] == 777)["bounds"]["Width"] = 920
        elif (
            operation == "accessibility.inspect"
            and arguments.get("element_token") == result["physical_window"]["ax_window_token"]
        ):
            value["element"]["size"] = [920, 600]
        return value

    leaf.system_transport.request = resized_own
    await leaf.verify_opened(result, principal="chatgpt")
    assert leaf.native.await_count == 3


async def test_product_unknown_move_retains_exact_creation_and_never_sends_or_reopens(product):
    scene, leaf, events, receipt, created = product
    scene.unknown_move = True
    with pytest.raises(UncertainExecution) as error:
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert error.value.provider_error["creation_receipt"] == receipt
    assert error.value.provider_error["automatic_retry"] is False
    assert events == ["create", "receipt", "focus", "move"]


async def test_product_initial_separate_hidden_surface_preserves_original_groups(product):
    scene, leaf, events, _, created = product
    scene.already_isolated = True
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["physical_window"]["move_confirmed"] is False
    assert events == ["create", "receipt", "focus"]


async def test_product_cold_terminal_uses_one_returned_tty_without_adopting_restored_windows(
    product,
):
    scene, leaf, events, _, created = product
    scene.rows = []
    scene.already_isolated = True
    groups = scene.groups
    scene.groups = lambda: [] if scene.phase == "baseline" else [g for g in groups() if g[0] == 777]
    request = leaf.system_transport.request
    inventory = leaf.window_inventory

    async def cold_inventory():
        value = await inventory()
        return {**value, "running": scene.phase != "baseline"}

    leaf.window_inventory = cold_inventory

    async def cold_request(operation, arguments, **kwargs):
        result = await request(operation, arguments, **kwargs)
        if operation == "apps.list" and scene.phase == "baseline":
            result.update(applications=[], total=0)
        return result

    leaf.system_transport.request = cold_request
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["separate_window"] and result["tty"] == "/dev/ttys004"
    assert events == ["create", "receipt", "focus"]


@pytest.mark.parametrize("direct", [True, False])
async def test_argv_for_all_principals_waits_for_full_binding_and_fresh_cwd(
    tmp_path, direct, native_session_platform
):
    fixture = fixture_module("test_session_open_ambiguity")
    selected = fixture.row()
    manager, native, _ = fixture.manager_for_open(tmp_path, [selected])
    manager.ports = replace(manager.ports, visible_required=lambda _: direct)
    receipt = {
        "tty": selected["tty"],
        "opened": True,
        "separate_window": True,
        "physical_window": {"proof": "native"},
    }
    events = []

    async def opened(command, *, on_created, principal):
        assert sys.executable not in command and "&& /" not in command
        events.append("physical-bound")
        await on_created(dict(receipt))
        return dict(receipt)

    async def created(value):
        assert value == receipt
        events.append("durable-receipt")

    async def sent(row, text, identity, *, expected_cwd, before_transport):
        assert identity == "full-identity" and expected_cwd == str(tmp_path)
        await before_transport()
        events.append("argv-once")
        return {"sent": True}

    native.open = AsyncMock(side_effect=opened)
    native.process_identity = AsyncMock(return_value="full-identity")
    native.process_working_directory = AsyncMock(return_value=str(tmp_path))
    native.verify_opened = AsyncMock()
    native.send_confirmed = AsyncMock(side_effect=sent)
    result = await manager.open(
        "chatgpt",
        fixture.SessionOpen(cwd=str(tmp_path), argv=[sys.executable]),
        task_id="owned",
        on_created=created,
    )
    assert result["creation_receipt"] == receipt
    assert events == ["physical-bound", "durable-receipt", "argv-once"]
    native.process_identity.assert_awaited_once_with(selected["expected_pid"], detailed=True)
    native.verify_opened.assert_awaited_once_with(receipt, principal="chatgpt")
    native.send_confirmed.assert_awaited_once()


async def test_native_creation_binds_only_doscript_returned_new_tty(product):
    scene, leaf, _, _, _ = product
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    prior = [[row["window_id"], [row["tty"]]] for row in scene.rows]
    source = leaf.native_open_source(
        "cd -- /private/work", TITLE, SimpleNamespace(logical_before=prior, app=None)
    )
    for change in (None, "reused", "duplicate"):
        code = (
            "const cfg="
            + json.dumps({"source": source, "prior": prior, "change": change})
            + ";"
            + r"""
const vm=require('node:vm');let opens=0,tags=0;
function make(id,tty){const tab={tty:()=>tty};
 Object.defineProperty(tab,'customTitle',{set:()=>{tags++;}});
 return {id:()=>id,tabs:()=>[tab],tab};}
const wins=cfg.prior.map(([id,ttys])=>make(id,ttys[0]));
const app={running:()=>true,windows:()=>wins,doScript:()=>{opens++;
 if(cfg.change==='reused')return wins[0].tab;
 const own=make(123,'/dev/ttys004');wins.push(own);
 if(cfg.change==='duplicate')wins.push(make(124,'/dev/ttys004'));
 return own.tab;}};
const owner={bundleIdentifier:()=>'com.apple.Terminal',unixId:()=>775};
function Application(name){return name==='Terminal'?app:{processes:()=>[owner]};}
Application.currentApplication=()=>({
 doShellScript:()=> '501 ?? Sun Nov 1 10:00:00 2026 1 /Terminal'});
const receipt=JSON.parse(vm.runInNewContext(cfg.source,{Application}));
process.stdout.write(JSON.stringify({receipt,opens,tags}));
"""
        )
        completed = await asyncio.to_thread(
            subprocess.run,
            [node, "-e", code],
            text=True,
            capture_output=True,
            check=True,
            timeout=3,
        )
        result = json.loads(completed.stdout)
        assert result["opens"] == 1
        if change is None:
            assert (
                result["receipt"]["creation_bound"] and result["receipt"]["tty"] == "/dev/ttys004"
            )
            assert result["tags"] == 1
        else:
            assert not result["receipt"]["creation_bound"] and result["tags"] == 0


async def test_real_send_source_checks_full_image_parent_cwd_and_final_empty_screen(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    fixture = fixture_module("test_codex_window_isolation")
    leaf = TerminalAppTransport(asyncio.Lock(), desktop=object())
    leaf.read = AsyncMock(return_value="KiraBridge visible % ")
    leaf.native = AsyncMock(side_effect=["KiraBridge visible % ", {"sent": True}] * 2)
    before_transport = AsyncMock()
    row = {"pane_id": "terminal:123:ttys004", "tty": "/dev/ttys004", "expected_pid": 345}
    await leaf.send_confirmed(
        row,
        "/bin/echo owned",
        fixture.SHELL,
        expected_cwd=str(tmp_path),
        before_transport=before_transport,
    )
    before_transport.assert_awaited_once()
    source = leaf.native.await_args.args[0]
    for change in (None, "image", "parent", "cwd", "screen", "busy"):
        config = {
            "source": source,
            "identity": fixture.SHELL,
            "cwd": f"p345\nfcwd\nn{tmp_path}",
            "change": change,
        }
        code = (
            "const cfg="
            + json.dumps(config)
            + ";"
            + r"""
const vm=require('node:vm');let sent=0,identity=cfg.identity,busy=false;
let screen='KiraBridge visible % ';
const tab={tty:()=>'/dev/ttys004',busy:()=>busy,history:()=>screen};
const win={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab};
function windows(){return [win];}windows.byId=()=>win;
const app={running:()=>true,windows,activate:()=>{},doScript:()=>{sent++;}};
function Application(name){return name==='System Events'?
 {processes:{byName:()=>({frontmost:()=>true})}}:app;}
Application.currentApplication=()=>({doShellScript:command=>{
 if(command.includes('lsof')){
  if(cfg.change==='image')identity=identity.replace('/bin/zsh','/bin/fish');
  if(cfg.change==='parent')identity=identity.replace(' 344 ',' 999 ');
  if(cfg.change==='screen')screen+='foreign input';
  if(cfg.change==='busy')busy=true;
  return cfg.change==='cwd'?'p345\nfcwd\nn/wrong':cfg.cwd;
 }
 return identity;
}});
let error;try{vm.runInNewContext(cfg.source,{Application});}catch(e){error=e.message;}
process.stdout.write(JSON.stringify({sent,error}));
"""
        )
        result = await asyncio.to_thread(
            subprocess.run,
            [node, "-e", code],
            text=True,
            capture_output=True,
            check=True,
            timeout=3,
        )
        observed = json.loads(result.stdout)
        assert observed["sent"] == (1 if change is None else 0), observed

    await leaf.send_confirmed(row, "/bin/echo owned", fixture.SHELL)
    assert "targetWindow.tabs().length!==1" not in leaf.native.await_args.args[0]


async def test_preopen_original_radio_replacement_stops_before_any_move(product):
    scene, leaf, events, receipt, created = product
    request = leaf.system_transport.request

    async def replacement(operation, arguments, **kwargs):
        value = await request(operation, arguments, **kwargs)
        if (
            scene.phase == "tagged"
            and operation == "accessibility.inspect"
            and value["element"]["role"] == "AXTabGroup"
        ):
            value["children"][0]["element_token"] = "f" * 32
        return value

    leaf.system_transport.request = replacement
    with pytest.raises(UncertainExecution) as error:
        await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert error.value.provider_error["creation_receipt"] == receipt
    assert events == ["create", "receipt", "focus"]


async def test_existing_terminal_in_other_space_activates_once_then_only_bounded_reads(product):
    from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof

    scene, leaf, events, _, _ = product
    fixture = fixture_module("test_codex_window_isolation")
    original_groups = scene.groups
    scene.groups = lambda: (
        [] if sum(op == "windows.list" for op, _ in scene.calls) < 3 else original_groups()
    )
    leaf.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
    proof = TerminalWindowProof(leaf, leaf.system_transport, "chatgpt")
    await proof.prepare()
    leaf.native.assert_awaited_once()
    source = leaf.native.await_args.args[0]
    assert source == leaf.native_existing_app_activation_source(775, fixture.TERMINAL)
    assert source.count("app.activate()") == 1
    assert all(word not in source for word in ("doScript(", "windows", "keystroke", "keyCode"))
    assert sum(op == "windows.list" for op, _ in scene.calls) == 3
    assert len(proof.before["cg"]) == len(proof.before["ax"]) == 1 and events == []
    assert await asyncio.to_thread(fixture.javascript, scene, source) == {
        "clicks": 0,
        "activations": 1,
    }
    changed = await asyncio.to_thread(fixture.javascript, scene, source, change="app-generation")
    assert changed["activations"] == 0 and changed["error"]

    scene.groups = lambda: []
    leaf.native.reset_mock()
    previous = sum(op == "windows.list" for op, _ in scene.calls)
    with pytest.raises(BridgeError, match="Existing Terminal surfaces are not observable"):
        await TerminalWindowProof(leaf, leaf.system_transport, "chatgpt").prepare()
    leaf.native.assert_awaited_once()
    assert sum(op == "windows.list" for op, _ in scene.calls) - previous == 4
    assert events == []


@pytest.mark.parametrize("swapped", [False, True])
async def test_one_confirmed_move_allows_either_split_surface_to_keep_shared_cg(product, swapped):
    scene, leaf, events, _, created = product
    groups = scene.groups
    own_id = 888 if swapped else 777

    def split_groups():
        if scene.phase == "detached" and swapped:
            return [(777, "original", 3), (888, TITLE, None)]
        return groups()

    scene.groups = split_groups
    request = leaf.system_transport.request

    async def moved_geometry(operation, arguments, **kwargs):
        value = await request(operation, arguments, **kwargs)
        if scene.phase == "detached":
            if operation == "windows.list":
                next(w for w in value["windows"] if w["window_id"] == own_id)["bounds"] = {
                    "X": 0,
                    "Y": 30,
                    "Width": 800,
                    "Height": 580,
                }
            elif (
                operation == "accessibility.inspect"
                and arguments.get("element_token") == f"{1:032x}"
            ):
                value["element"]["position"], value["element"]["size"] = [0, 30], [800, 580]
        return value

    leaf.system_transport.request = moved_geometry
    result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
    assert result["physical_window"]["cg_window_id"] == own_id
    assert result["physical_window"]["ax_window_token"] == f"{1:032x}"
    assert events == ["create", "receipt", "focus", "move"]
    await leaf.verify_opened(result, principal="chatgpt")


@pytest.mark.parametrize("persistent", [False, True])
async def test_postmove_only_count_mismatch_reads_again_without_repeating_move(product, persistent):
    scene, leaf, events, receipt, created = product
    request = leaf.system_transport.request
    postmove_reads = 0

    async def asynchronous_move(operation, arguments, **kwargs):
        nonlocal postmove_reads
        value = await request(operation, arguments, **kwargs)
        if (
            scene.phase == "detached"
            and operation == "accessibility.inspect"
            and not arguments.get("element_token")
        ):
            postmove_reads += 1
            if persistent or postmove_reads == 1:
                value["children"] = value["children"][:1]
                value["total_children"] = 1
        return value

    leaf.system_transport.request = asynchronous_move
    if persistent:
        with pytest.raises(UncertainExecution) as error:
            await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
        assert error.value.provider_error["cause_code"] == "session_window_inventory_pending"
        assert error.value.provider_error["cause_message"] == (
            "Native AX/CG window inventory differs (CG=2, AX=1, AX-list=2)"
        )
        assert error.value.provider_error["creation_receipt"] == receipt
        assert postmove_reads == 10
    else:
        result = await leaf.open("cd -- /private/work", on_created=created, principal="chatgpt")
        assert result["separate_window"] and result["physical_window"]["move_confirmed"]
        assert postmove_reads == 2
    assert events == ["create", "receipt", "focus", "move"]
    assert leaf.native.await_count == 3
