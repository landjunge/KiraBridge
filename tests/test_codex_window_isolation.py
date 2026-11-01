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
                accessibility_windows=[{} for _ in groups],
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
                        "element_token": f"{index + 1:032x}",
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
                        "element_token": f"{1000 + index * 20 + i:032x}",
                        "title": TITLE if title == TITLE and i == count - 1 else f"tab-{i}",
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


async def test_no_ax_group_counts_as_one_only_after_known_successful_move(module, tmp_path):
    scene = await prepared(module, tmp_path)
    scene.no_own_group = True
    assert (await scene.controller.isolate(CREATED, SHELL))["tab_count"] == 1
    scene = await prepared(module, tmp_path)
    scene.no_own_group = scene.already_isolated = True
    with pytest.raises(RuntimeError, match="not a standalone"):
        await scene.controller.isolate(CREATED, SHELL)
    assert scene.effects == ["title"]


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
    with pytest.raises(RuntimeError, match="baseline"):
        scene.controller.topology(snapshot, after_move=True)


@pytest.mark.parametrize("change", ["radio", "cg-reused"])
async def test_ax_membership_or_reused_baseline_cg_also_refuses(module, tmp_path, change):
    scene = await prepared(module, tmp_path)
    scene.phase = "detached"
    scene.controller.move_accepted = True
    snapshot = await scene.controller.snapshot()
    if change == "radio":
        snapshot["ax"][0]["radios"][0]["element_token"] = "replacement-tab"
    else:
        snapshot["cg"][0]["window_id"] = 999
        snapshot["cg"][1]["window_id"] = 231
        snapshot["cg"][1]["revision"] = snapshot["cg"][0]["revision"]
    with pytest.raises(RuntimeError, match="baseline"):
        scene.controller.topology(snapshot, after_move=True)


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
    }
    script = (
        "const cfg="
        + json.dumps(config)
        + ";"
        + r"""
const vm=require('node:vm');let clicks=0,tags=0,title=cfg.is_tag?'fresh':cfg.nonce;
let busy=false,screen='KiraBridge visible % ';
const tab={tty:()=>'/dev/ttys004',busy:()=>busy,history:()=>screen,selected:true};
Object.defineProperty(tab,'customTitle',{set:value=>{title=value;tags++;}});
const win={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab,name:()=>title};
function windows(){return [win];}windows.byId=()=>win;
const app={running:()=>true,windows,activate:()=>{}};
const entry={name:()=>cfg.change==='label'?'Other':'Tab in ein neues Fenster bewegen',
 enabled:()=>cfg.change!=='disabled',click:()=>{clicks++;}};
const entries=()=>cfg.change==='duplicate-menu'?[entry,entry]:[entry];
const process={unixId:()=>775,frontmost:()=>cfg.change!=='focus',
 windows:()=>cfg.change==='duplicate-nonce'?[win,win]:[win],
 menuBars:()=>[{menuBarItems:()=>[{name:()=>'Fenster',menus:()=>[{menuItems:entries}]}]}]};
function processes(){return [process];}processes.byName=()=>process;
function Application(name){return name==='Terminal'?app:{processes};}
Application.currentApplication=()=>({doShellScript:(command)=>{
 if(command.includes('lsof')){if(cfg.change==='late-busy')busy=true;
  if(cfg.change==='late-screen')screen+='foreign input';
  return cfg.change==='cwd'?'p345\nfcwd\nn/wrong':cfg.cwd;}
 if(command.includes(' -t '))return 'exact-shell-row';
 return command.includes('-p 775 ')?cfg.terminal:cfg.change==='generation'?'changed':cfg.shell;
}});
let error;try{vm.runInNewContext(cfg.source,{Application,delay:()=>{}});}catch(e){error=e.message;}
process.stdout.write(JSON.stringify({clicks,error,...(cfg.is_tag?{tags}:{} )}));
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
