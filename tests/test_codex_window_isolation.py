"""Synthetic native receipts and JavaScript objects only; no macOS/UI calls."""

import importlib.util
import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

NONCE = "0123456789abcdef"
TITLE = "KB_WINDOW_" + NONCE
SHELL = f"{os.getuid()} ttys004 Sun Nov 1 12:00:00 2026 344 /bin/zsh"
TERMINAL = f"{os.getuid()} ?? Sun Nov 1 10:00:00 2026 1 /Terminal"
CREATED = {"pane_id": "terminal:123:ttys004", "expected_pid": 345, "tty": "/dev/ttys004"}


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / "scripts/codex_window_isolation.py"
    spec = importlib.util.spec_from_file_location("physical_isolation_offline", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Scene:
    def __init__(self, module, tmp_path):
        self.phase = "baseline"
        self.already_isolated = self.no_own_group = False
        self.wrong_owner = self.wrong_count = self.duplicate_nonce = self.incomplete_ax = False
        self.unknown_move = False
        self.unknown_tag = False
        self.app = {
            "pid": 775,
            "started_at": 1000.25,
            "bundle_id": "com.apple.Terminal",
            "active": True,
        }
        self.worker = {"pid": 99, "generation": "a" * 36, "source_commit": "b" * 40}
        self.calls, self.effects, self.records, self.roles = [], [], [], []
        self.rows = [self.row(index + 1, index + 10) for index in range(3)]
        self.workspace = str(tmp_path)
        self.terminal = SimpleNamespace(
            last_catalog_incomplete=False,
            window_inventory=AsyncMock(side_effect=self.inventory),
            catalog=AsyncMock(side_effect=lambda: deepcopy(self.rows)),
            process_identity=AsyncMock(side_effect=self.identity),
            process_working_directory=AsyncMock(side_effect=lambda *a, **k: self.workspace),
            prepare_shell_paste=AsyncMock(side_effect=self.context),
            native=AsyncMock(side_effect=self.effect),
            native_target=TerminalAppTransport.native_target,
            native_identity_guard=TerminalAppTransport.native_identity_guard,
            native_shell_guard=TerminalAppTransport.native_shell_guard,
            native_screen_guard=TerminalAppTransport.native_screen_guard,
        )
        self.terminal.native_focus = lambda pane: TerminalAppTransport.native_focus(
            self.terminal, pane
        )
        self.controller = module.PhysicalIsolation(
            self.terminal,
            SimpleNamespace(request=self.request),
            nonce=NONCE,
            workspace=tmp_path,
            record=self.records.append,
        )

    @staticmethod
    def row(window, pid):
        return {
            "window_id": window,
            "pane_id": f"terminal:{window}:ttys00{window}",
            "tty": f"/dev/ttys00{window}",
            "expected_pid": pid,
            "legacy_expected_pid": pid + 100,
            "identity_ambiguous": False,
            "busy": False,
            "processes": [{"pid": pid, "ppid": 344, "image": "/bin/zsh"}],
        }

    def created(self):
        self.rows.append({**self.row(123, 345), **CREATED, "tab_count": 4, "visual_window_id": 1})
        self.phase = "created"

    async def inventory(self):
        return {
            "running": True,
            "windows": [{"window_id": row["window_id"], "ttys": [row["tty"]]} for row in self.rows],
        }

    async def identity(self, pid, *, detailed):
        assert detailed is True
        return TERMINAL if pid == 775 else SHELL if pid == 345 else f"original-{pid}"

    async def context(self, row):
        return {
            "identities": {345: SHELL},
            "screen": "KiraBridge visible % ",
            "snapshot": {"command": ["/bin/ps", "-t", "ttys004"], "rows": ["exact-shell-row"]},
        }

    def groups(self):
        own = self.phase in {"tagged", "detached"}
        if self.phase == "baseline":
            return [(231, "original", 3)]
        if self.phase == "detached" or self.already_isolated:
            result = [
                (231, "original", 3),
                (888, TITLE if own else "fresh", None if self.no_own_group else 1),
            ]
        else:
            result = [(231, TITLE if own else "fresh", 5 if self.wrong_count else 4)]
        if self.duplicate_nonce and own:
            result.append((777, TITLE, 1))
        return result

    async def request(self, operation, args, *, principal):
        self.calls.append((operation, deepcopy(args)))
        assert principal == "chatgpt" and operation in {
            "apps.list",
            "apps.inspect",
            "windows.list",
            "accessibility.inspect",
        }
        result = {
            "native_helper": deepcopy(self.worker),
            "revision": "f" * 64,
            "offset": args.get("offset", 0),
            "truncated": False,
        }
        if operation == "apps.list":
            result.update(applications=[deepcopy(self.app)], total=1, eof=True)
        elif operation == "apps.inspect":
            result["application"] = deepcopy(self.app)
        elif operation == "windows.list":
            groups = self.groups()
            result.update(
                windows=[
                    {
                        "window_id": number,
                        "owner_pid": 999 if self.wrong_owner else 775,
                        "application_start": f"{self.app['started_at']:.6f}",
                        "layer": 0,
                        "revision": f"{number:064x}",
                        "on_screen": True,
                        "title_available": True,
                        "title": title,
                        "bounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
                    }
                    for number, title, _ in groups
                ],
                total=len(groups),
                next_offset=len(groups),
                titles_redacted=False,
                accessibility_windows=[{"role": "AXWindow"} for _ in groups],
            )
        else:
            groups = self.groups()
            token = args.get("element_token")
            result.update(
                application=deepcopy(self.app),
                helper_pid=self.worker["pid"],
                worker_generation=self.worker["generation"],
                element_token=token or "0" * 32,
                eof=True,
            )
            if token is None:
                role, title = "AXApplication", "Terminal"
                children = [
                    {
                        "role": "AXWindow",
                        "element_token": format(
                            2 - index
                            if self.phase == "detached" and self.no_own_group
                            else index + 1,
                            "032x",
                        ),
                        "title": title,
                        "title_truncated": False,
                        "minimized": False,
                    }
                    for index, (_, title, _) in enumerate(groups)
                ]
                if self.incomplete_ax:
                    result.update(total_children=len(children) + 1, truncated=True, eof=False)
            elif int(token, 16) < 100:
                index = int(token, 16) - 1
                if self.phase == "detached" and self.no_own_group:
                    index = 1 - index
                _, title, count = groups[index]
                role = "AXWindow"
                children = [{"role": "AXSplitGroup", "element_token": "e" * 32}]
                if count is not None:
                    children.append({"role": "AXTabGroup", "element_token": f"{index + 100:032x}"})
            else:
                index = int(token, 16) - 100
                _, title, count = groups[index]
                role = "AXTabGroup"
                children = [
                    {
                        "role": "AXRadioButton",
                        "element_token": f"{1003 if index == 1 and i == 0 else 1000 + i:032x}",
                        "title": f"volatile-tab-{i}",
                        "title_truncated": False,
                        "value": title == TITLE and i == count - 1,
                    }
                    for i in range(count)
                ]
            self.roles.append(role)
            result.update(
                element={
                    "role": role,
                    "title": title,
                    "subrole": "AXStandardWindow" if role == "AXWindow" else "",
                    "title_truncated": False,
                    "minimized": False,
                    "position": [0, 0],
                    "size": [800, 600],
                },
                children=children,
            )
            result.setdefault("total_children", len(children))
        return result

    async def effect(self, source, *, mutation):
        assert mutation is True and "app.windows.byId(123)" in source
        assert "keystroke" not in source and "keyCode" not in source
        if "entries[0].click()" in source:
            self.effects.append("move")
            self.phase = "detached"
            if self.unknown_move:
                raise RuntimeError("Lost move result")
            return {"detached": True}
        self.effects.append("title")
        self.phase = "tagged"
        if self.unknown_tag:
            raise RuntimeError("Lost title result")
        return {"tagged": True}


async def prepared(module, tmp_path):
    scene = Scene(module, tmp_path)
    await scene.controller.capture_baseline()
    scene.created()
    return scene


async def test_shared_to_single_uses_one_move_and_does_not_equate_window_ids(module, tmp_path):
    scene = await prepared(module, tmp_path)
    proof = await scene.controller.isolate(CREATED, SHELL)
    assert proof["tab_count"] == 1 and proof["cg_window_id"] == 888
    assert proof["cg_window_id"] != 123
    assert scene.effects == ["title", "move"]
    assert (await scene.controller.current())["tab_count"] == 4  # heuristic remains untrusted
    assert set(scene.roles) == {"AXApplication", "AXWindow", "AXTabGroup"}


async def test_same_bounds_but_authoritatively_separate_needs_no_detach(module, tmp_path):
    scene = await prepared(module, tmp_path)
    scene.already_isolated = True
    assert (await scene.controller.isolate(CREATED, SHELL))["tab_count"] == 1
    assert scene.effects == ["title"]


async def test_known_move_preserves_hidden_own_window_and_positive_original_partition(
    module, tmp_path
):
    scene = await prepared(module, tmp_path)
    scene.no_own_group = True
    proof = await scene.controller.isolate(CREATED, SHELL)
    assert proof["tab_count"] == 1 and proof["own_tabbar_hidden"] is True
    assert proof["evidence"] == "known_move_preserved_own_ax_and_ordered_original_radios"
    assert proof["own_radio_token"] == f"{1003:032x}"
    assert (await scene.controller.current())["expected_pid"] == CREATED["expected_pid"]
    assert scene.effects == ["title", "move"] and scene.controller.confirmed
    with pytest.raises(RuntimeError, match="never be replayed"):
        await scene.controller.isolate(CREATED, SHELL)
    assert scene.effects == ["title", "move"]


@pytest.mark.parametrize("change", ["cwd", "generation", "worker", "target", "owner"])
async def test_changed_target_or_owner_refuses_before_any_display_effect(module, tmp_path, change):
    scene = await prepared(module, tmp_path)
    if change == "cwd":
        scene.workspace += "-changed"
    elif change == "generation":
        scene.app["started_at"] += 1
    elif change == "worker":
        scene.worker["generation"] = "c" * 36
    elif change == "target":
        scene.rows[-1]["expected_pid"] += 1
    else:
        scene.wrong_owner = True
    with pytest.raises(RuntimeError):
        await scene.controller.isolate(CREATED, SHELL)
    assert scene.effects == []


@pytest.mark.parametrize("change", ["count", "duplicate"])
async def test_wrong_ax_count_or_duplicate_nonce_never_clicks_menu(module, tmp_path, change):
    scene = await prepared(module, tmp_path)
    scene.wrong_count = change == "count"
    scene.duplicate_nonce = change == "duplicate"
    with pytest.raises(RuntimeError):
        await scene.controller.isolate(CREATED, SHELL)
    assert scene.effects == ["title"] and not scene.controller.confirmed


async def test_incomplete_ax_baseline_stops_before_any_creation_or_display(module, tmp_path):
    scene = Scene(module, tmp_path)
    scene.incomplete_ax = True
    with pytest.raises(RuntimeError):
        await scene.controller.capture_baseline()
    assert scene.effects == [] and scene.phase == "baseline"


async def test_unknown_menu_result_never_retries_or_adopts_observed_detach(module, tmp_path):
    scene = await prepared(module, tmp_path)
    scene.unknown_move = True
    with pytest.raises(RuntimeError, match="Lost move result"):
        await scene.controller.isolate(CREATED, SHELL)
    calls = len(scene.calls)
    with pytest.raises(RuntimeError, match="never be replayed"):
        await scene.controller.isolate(CREATED, SHELL)
    with pytest.raises(RuntimeError, match="Fresh physical proof"):
        await scene.controller.current()
    assert len(scene.calls) == calls and scene.effects == ["title", "move"]
    assert not scene.controller.move_accepted and not scene.controller.confirmed


@pytest.mark.parametrize("own_tabs", [None, 1])
async def test_equal_count_replacement_cannot_substitute_baseline_physical_identity(
    module, tmp_path, own_tabs
):
    scene = await prepared(module, tmp_path)
    scene.phase, scene.no_own_group = "detached", own_tabs is None
    scene.controller.move_accepted = True
    snapshot = await scene.controller.snapshot()
    original = next(window for window in snapshot["cg"] if window["window_id"] == 231)
    original.update(window_id=99, revision="9" * 64)
    old_ax = next(group for group in snapshot["ax"] if group["title"] == "original")
    old_ax.update(
        token="unrelated_ax",
        radios=[
            {"title": name, "element_token": name, "value": False}
            for name in ("general", "profiles", "groups")
        ],
    )
    with pytest.raises(RuntimeError):
        scene.controller.topology(snapshot, after_move=True)


@pytest.mark.parametrize("change", ["radio", "reordered", "duplicate", "worker", "layout"])
async def test_baseline_membership_generation_or_layout_change_refuses(module, tmp_path, change):
    scene = await prepared(module, tmp_path)
    scene.phase = "detached"
    snapshot = await scene.controller.snapshot()
    if change == "radio":
        snapshot["ax"][0]["radios"][0]["element_token"] = "replacement-tab"
    elif change == "reordered":
        snapshot["ax"][0]["radios"].reverse()
    elif change == "duplicate":
        snapshot["ax"][0]["radios"][0]["element_token"] = snapshot["ax"][0]["radios"][1][
            "element_token"
        ]
    elif change == "worker":
        snapshot["worker"][1] = "different-generation"
    else:
        snapshot["cg"][0]["bounds"]["Width"] += 1
        snapshot["ax"][0]["size"][0] += 1
    with pytest.raises(RuntimeError):
        scene.controller.topology(snapshot, after_move=True)


async def test_stable_radio_membership_allows_observed_parent_cg_and_title_changes(
    module, tmp_path
):
    scene = await prepared(module, tmp_path)
    scene.phase = "tagged"
    snapshot = await scene.controller.snapshot()
    snapshot["cg"][0].update(window_id=841, revision="9" * 64)
    snapshot["ax"][0]["token"] = "different-parent-window"
    for radio in snapshot["ax"][0]["radios"]:
        radio["title"] = "same generic title"  # no nonce in any radio title
    proof = scene.controller.topology(snapshot)
    assert proof["tab_count"] == 4 and proof["cg_window_id"] == 841
    own = proof["own_radio_token"]
    scene.phase = "detached"
    detached = await scene.controller.snapshot()
    detached["cg"][0].update(window_id=999, revision="8" * 64)
    detached["cg"][1]["window_id"] = 231  # CG identity is not membership authority
    detached["ax"][0]["token"] = "another-original-parent"
    assert scene.controller.topology(detached, after_move=True)["own_radio_token"] == own
    detached["ax"][1]["radios"][0]["element_token"] = "regenerated-own-radio"
    with pytest.raises(RuntimeError, match="Own radio token changed"):
        scene.controller.topology(detached, after_move=True)


async def test_unknown_title_result_never_retries_display(module, tmp_path):
    scene = await prepared(module, tmp_path)
    scene.unknown_tag = True
    with pytest.raises(RuntimeError, match="Lost title result"):
        await scene.controller.isolate(CREATED, SHELL)
    with pytest.raises(RuntimeError, match="never be replayed"):
        await scene.controller.isolate(CREATED, SHELL)
    assert scene.effects == ["title"] and not scene.controller.confirmed


def javascript(scene, source, *, change=None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    config = {
        "source": source,
        "nonce": TITLE,
        "shell": SHELL,
        "terminal": TERMINAL,
        "cwd": f"p345\nfcwd\nn{scene.workspace}",
        "change": change,
        "is_tag": "tab.customTitle=" in source,
        "is_activation": "activation_sent:true" in source,
    }
    script = (
        "const cfg="
        + json.dumps(config)
        + ";"
        + r"""
const vm=require('node:vm');let clicks=0,tags=0,activations=0,title=cfg.is_tag?'fresh':cfg.nonce;
let busy=false,screen='KiraBridge visible % ';
const tab={tty:()=>'/dev/ttys004',busy:()=>busy,history:()=>screen,selected:true};
Object.defineProperty(tab,'customTitle',{set:value=>{title=value;tags++;}});
const win={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab,name:()=>title};
function windows(){return [win];}windows.byId=()=>win;
const app={running:()=>true,windows,activate:()=>{activations++;},frontmost:()=>true};
const entry={name:()=>cfg.change==='label'?'Other':'Tab in ein neues Fenster bewegen',
 enabled:()=>cfg.change!=='disabled',click:()=>{clicks++;}};
const entries=()=>cfg.change==='duplicate-menu'?[entry,entry]:[entry];
const process={unixId:()=>775,frontmost:()=>cfg.change!=='focus',
 bundleIdentifier:()=>'com.apple.Terminal',
 windows:()=>cfg.change==='duplicate-nonce'?[win,win]:[win],
 menuBars:()=>[{menuBarItems:()=>[{name:()=>'Fenster',menus:()=>[{menuItems:entries}]}]}]};
function processes(){return [process];}processes.byName=()=>process;
function Application(name){return name==='Terminal'?app:{processes};}
Application.currentApplication=()=>({doShellScript:(command)=>{
 if(command.includes('lsof')){if(cfg.change==='late-busy')busy=true;
  if(cfg.change==='late-screen')screen+='foreign input';
  return cfg.change==='cwd'?'p345\nfcwd\nn/wrong':cfg.cwd;}
 if(command.includes(' -t '))return 'exact-shell-row';
 if(command.includes('-p 775 '))return cfg.change==='app-generation'?'changed':cfg.terminal;
 return cfg.change==='generation'?'changed':cfg.shell;
}});
let error;try{vm.runInNewContext(cfg.source,{Application,delay:()=>{}});}catch(e){error=e.message;}
process.stdout.write(JSON.stringify({clicks,error,...(cfg.is_tag?{tags}:{} ),
 ...(cfg.is_activation?{activations}:{})}));
"""
    )
    # The synthetic process object above must not shadow Node's stdout owner.
    script = (
        script.replace("const process={", "const terminalProcess={")
        .replace("return [process];", "return [terminalProcess];")
        .replace("byName=()=>process;", "byName=()=>terminalProcess;")
    )
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True, timeout=3
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "change",
    [
        None,
        "generation",
        "cwd",
        "focus",
        "label",
        "disabled",
        "duplicate-menu",
        "duplicate-nonce",
        "late-busy",
        "late-screen",
    ],
)
async def test_actual_generated_menu_guard_presses_only_exact_current_owned_target(
    module, tmp_path, change
):
    scene = await prepared(module, tmp_path)
    scene.controller.created, scene.controller.identity = CREATED, SHELL
    context = await scene.controller.context()
    result = javascript(scene, scene.controller.source(context, detach=True), change=change)
    if change is None:
        assert result == {"clicks": 1}
    else:
        assert result["clicks"] == 0 and result["error"]


@pytest.mark.parametrize("change", [None, "generation", "cwd", "late-busy", "late-screen"])
async def test_title_rechecks_busy_and_screen_after_slow_reads(module, tmp_path, change):
    scene = await prepared(module, tmp_path)
    scene.controller.created, scene.controller.identity = CREATED, SHELL
    context = await scene.controller.context()
    result = javascript(scene, scene.controller.source(context, detach=False), change=change)
    assert result["clicks"] == 0
    if change is None:
        assert result == {"clicks": 0, "tags": 1}
    else:
        assert result["tags"] == 0 and result["error"]


async def test_baseline_activates_existing_app_once_then_only_reads_until_visible(module, tmp_path):
    scene = Scene(module, tmp_path)
    actual_groups = scene.groups
    scene.groups = lambda: (
        [] if sum(op == "windows.list" for op, _ in scene.calls) == 1 else actual_groups()
    )
    scene.terminal.native = AsyncMock(
        return_value={"activation_sent": True, "pid": 775, "frontmost": True}
    )
    baseline = await scene.controller.prepare_visible_baseline(poll_interval=0)
    assert len(baseline["logical"]["rows"]) == 3 and len(baseline["native"]["cg"]) == 1
    scene.terminal.native.assert_awaited_once()
    source = scene.terminal.native.await_args.args[0]
    assert source.count("app.activate()") == 1
    assert all(
        word not in source
        for word in ("doScript", "windows", "keystroke", "keyCode", "customTitle")
    )
    activations = [
        event["baseline_activation"] for event in scene.records if "baseline_activation" in event
    ]
    assert [event["state"] for event in activations] == ["attempted", "returned"]
    assert (
        activations[0]["process_identity"] == TERMINAL
        and len(activations[0]["source_sha256"]) == 64
    )
    assert any(event.get("baseline_surface_pending") for event in scene.records)
    calls = len(scene.calls)
    with pytest.raises(RuntimeError, match="never be replayed"):
        await scene.controller.prepare_visible_baseline()
    assert len(scene.calls) == calls and scene.terminal.native.await_count == 1


async def test_unknown_activation_or_never_visible_surface_never_reactivates(module, tmp_path):
    for unknown in (True, False):
        scene = Scene(module, tmp_path)
        scene.groups = lambda: []
        scene.terminal.native = AsyncMock(
            side_effect=RuntimeError("lost activation") if unknown else None,
            return_value={"activation_sent": True, "pid": 775},
        )
        with pytest.raises(RuntimeError if unknown else TimeoutError):
            await scene.controller.prepare_visible_baseline(timeout=0, poll_interval=0)
        scene.terminal.native.assert_awaited_once()
        with pytest.raises(RuntimeError, match="never be replayed"):
            await scene.controller.prepare_visible_baseline()
        assert scene.terminal.native.await_count == 1 and scene.controller.baseline is None
        assert scene.effects == []  # no open, title, menu or input


def test_standard_activation_source_checks_full_generation_before_appleevent(module, tmp_path):
    scene = Scene(module, tmp_path)
    scene.controller.app = scene.app
    source = scene.controller.activation_source(TERMINAL)
    assert javascript(scene, source) == {"clicks": 0, "activations": 1}
    result = javascript(scene, source, change="app-generation")
    assert result["activations"] == 0 and result["error"]


async def test_baseline_spinner_mismatch_is_read_again_exactly_without_reactivation(
    module, tmp_path
):
    scene = Scene(module, tmp_path)
    scene.terminal.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
    snapshot = scene.controller.snapshot
    attempts = 0

    async def changing_title():
        nonlocal attempts
        current = await snapshot()
        attempts += 1
        current["cg"][0]["title"] = "⠧ Running original task"
        current["ax"][0]["title"] = (
            "⠇ Running original task" if attempts == 1 else "⠧ Running original task"
        )
        return current

    scene.controller.snapshot = changing_title
    baseline = await scene.controller.prepare_visible_baseline(poll_interval=0)
    assert (
        attempts == 2
        and baseline["native"]["cg"][0]["title"] == baseline["native"]["ax"][0]["title"]
    )
    scene.terminal.native.assert_awaited_once()
    assert scene.effects == [] and any(
        event.get("reason") == "BaselineTitlesUnsettled" for event in scene.records
    )


async def test_noncoherent_baseline_never_normalizes_titles_or_opens(module, tmp_path):
    scene = Scene(module, tmp_path)
    scene.terminal.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
    snapshot = scene.controller.snapshot

    async def mismatched():
        current = await snapshot()
        current["cg"][0]["title"] = "⠧ Running original task"
        current["ax"][0]["title"] = "⠇ Running original task"
        return current

    scene.controller.snapshot = mismatched
    with pytest.raises(TimeoutError):
        await scene.controller.prepare_visible_baseline(timeout=0.005, poll_interval=0)
    assert scene.controller.baseline is None and scene.effects == []
    scene.terminal.native.assert_awaited_once()


async def test_multiple_baseline_physical_groups_are_outside_observed_boundary(module, tmp_path):
    scene = Scene(module, tmp_path)
    scene.groups = lambda: [(231, "first", 2), (232, "second", 1)]
    with pytest.raises(RuntimeError, match="Only one observed baseline"):
        await scene.controller.capture_baseline()
    assert scene.controller.baseline is None and scene.effects == []


async def test_baseline_ax_tree_changed_repeats_same_request_without_effect_retry(module, tmp_path):
    from kirabridge.bridge_core.models import BridgeError

    scene = Scene(module, tmp_path)
    scene.terminal.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
    native_request = scene.controller.native.request
    failures = []

    async def changing_tree(operation, arguments, **kwargs):
        if (
            operation == "accessibility.inspect"
            and arguments.get("element_token") == f"{1:032x}"
            and not failures
        ):
            failures.append(deepcopy(arguments))
            raise BridgeError("macos_tree_changed", "Native system operation refused or failed")
        return await native_request(operation, arguments, **kwargs)

    scene.controller.native.request = changing_tree
    assert await scene.controller.prepare_visible_baseline(poll_interval=0)
    failed = [
        event["native_read_failed"] for event in scene.records if "native_read_failed" in event
    ]
    assert len(failed) == 1 and failed[0]["code"] == "macos_tree_changed"
    assert failed[0]["arguments"] == failures[0]
    assert failed[0]["worker"] == [99, "a" * 36, "b" * 40]
    assert sum(operation == "windows.list" for operation, _ in scene.calls) == 1
    successful = [
        args
        for operation, args in scene.calls
        if operation == "accessibility.inspect" and args.get("element_token") == f"{1:032x}"
    ]
    assert successful == failures
    scene.terminal.native.assert_awaited_once()
    assert scene.effects == []


async def test_persistent_baseline_ax_tree_change_stops_after_three_failures(module, tmp_path):
    from kirabridge.bridge_core.models import BridgeError

    scene = Scene(module, tmp_path)
    scene.terminal.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
    native_request = scene.controller.native.request
    errors = []

    async def changing_tree(operation, arguments, **kwargs):
        if operation == "accessibility.inspect" and arguments.get("element_token") == f"{1:032x}":
            error = BridgeError("macos_tree_changed", "Native system operation refused or failed")
            errors.append(error)
            raise error
        return await native_request(operation, arguments, **kwargs)

    scene.controller.native.request = changing_tree
    with pytest.raises(BridgeError) as raised:
        await scene.controller.prepare_visible_baseline(poll_interval=0)
    assert len(errors) == 3 and raised.value is errors[-1]
    assert sum("native_read_failed" in event for event in scene.records) == 3
    scene.terminal.native.assert_awaited_once()
    assert scene.controller.baseline is None and scene.effects == []


async def test_ax_retry_preserves_error_scope_and_app_worker_token_guards(module, tmp_path):
    from kirabridge.bridge_core.models import BridgeError

    for change in ("other-error", "worker", "app", "token", "non-ax-tree-error"):
        scene = Scene(module, tmp_path)
        scene.terminal.native = AsyncMock(return_value={"activation_sent": True, "pid": 775})
        native_request = scene.controller.native.request
        errors = []

        async def changing_tree(
            operation,
            arguments,
            *,
            errors=errors,
            change=change,
            scene=scene,
            native_request=native_request,
            **kwargs,
        ):
            target = (
                operation == "accessibility.inspect"
                and arguments.get("element_token") == f"{1:032x}"
            )
            if not errors and (
                target or change == "non-ax-tree-error" and operation == "windows.list"
            ):
                code = (
                    "macos_permission_denied" if change == "other-error" else "macos_tree_changed"
                )
                error = BridgeError(code, "Native system operation refused or failed")
                errors.append(error)
                if change == "worker":
                    scene.worker["generation"] = "c" * 36
                if change == "app":
                    scene.app["started_at"] += 1
                raise error
            result = await native_request(operation, arguments, **kwargs)
            if change == "token" and errors and target:
                result["element_token"] = "f" * 32
            return result

        scene.controller.native.request = changing_tree
        with pytest.raises(
            BridgeError if change in {"other-error", "non-ax-tree-error"} else RuntimeError
        ):
            await scene.controller.prepare_visible_baseline(poll_interval=0)
        assert len(errors) == 1
        assert sum("native_read_failed" in event for event in scene.records) == 1
        if change in {"other-error", "non-ax-tree-error"}:
            assert sum(operation == "windows.list" for operation, _ in scene.calls) <= 1
        scene.terminal.native.assert_awaited_once()
        assert scene.controller.baseline is None and scene.effects == []


async def test_hidden_own_tabbar_cannot_adopt_unknown_move_parent_or_foreign_partition(
    module, tmp_path
):
    for change in (
        "unknown-move",
        "before-move",
        "unbound-radio",
        "parent",
        "replace-none",
        "replace-one",
        "reorder",
        "duplicate",
        "extra",
        "worker",
        "layout",
        "cwd",
    ):
        scene = await prepared(module, tmp_path)
        scene.controller.created, scene.controller.identity = CREATED, SHELL
        scene.phase = "tagged"
        scene.controller.topology(await scene.controller.snapshot())
        scene.controller.move_attempted = scene.controller.move_accepted = True
        scene.phase, scene.no_own_group = "detached", True
        snapshot = await scene.controller.snapshot()
        own = next(group for group in snapshot["ax"] if group["title"] == TITLE)
        host = next(group for group in snapshot["ax"] if group is not own)
        if change == "unknown-move":
            scene.controller.move_accepted = False
        elif change == "unbound-radio":
            scene.controller.own_radio_token = None
        elif change == "parent":
            own["token"] = "replacement-parent"
        elif change in {"replace-none", "replace-one"}:
            host["radios"] = [
                {"element_token": name, "value": False}
                for name in ("general", "profiles", "groups")
            ]
            if change == "replace-one":
                own.update(tabs=1, radios=[{"element_token": f"{1003:032x}", "value": True}])
        elif change == "reorder":
            host["radios"].reverse()
        elif change == "duplicate":
            host["radios"][0]["element_token"] = host["radios"][1]["element_token"]
        elif change == "extra":
            host["radios"].append({"element_token": "extra", "value": False})
            host["tabs"] += 1
        elif change == "worker":
            snapshot["worker"][1] = "replacement-worker"
        elif change == "layout":
            window = next(window for window in snapshot["cg"] if window["title"] != TITLE)
            window["bounds"]["Width"] += 1
            host["size"][0] += 1
        elif change == "cwd":
            scene.workspace += "-changed"
            scene.controller.confirmed = True
        with pytest.raises(RuntimeError):
            if change == "cwd":
                await scene.controller.current()
            else:
                scene.controller.topology(snapshot, after_move=change != "before-move")
        assert scene.effects == []


async def test_tooltip_cg_layer_and_ax_help_tag_do_not_count_as_physical_windows(module, tmp_path):
    scene = Scene(module, tmp_path)
    native_request = scene.controller.native.request

    async def with_tooltip(operation, arguments, **kwargs):
        result = await native_request(operation, arguments, **kwargs)
        if operation == "windows.list":
            tooltip = {**result["windows"][0], "window_id": 124, "layer": 103, "title": "tooltip"}
            result["windows"].insert(0, tooltip)
            result.update(total=2, next_offset=2)
            result["accessibility_windows"] = [
                {"role": "AXHelpTag", "ax_identifier": "tooltip"},
                {"role": "AXWindow", "ax_identifier": "main"},
            ]
        elif operation == "accessibility.inspect" and not arguments.get("element_token"):
            result["children"].insert(0, {"role": "AXHelpTag", "element_token": "d" * 32})
            result["total_children"] += 1
        return result

    scene.controller.native.request = with_tooltip
    baseline = await scene.controller.capture_baseline()
    assert len(baseline["native"]["cg"]) == len(baseline["native"]["ax"]) == 1
    assert baseline["native"]["cg"][0]["window_id"] == 231
    assert not any(args.get("element_token") == "d" * 32 for _, args in scene.calls)
    assert scene.effects == []
