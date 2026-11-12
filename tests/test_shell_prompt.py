"""Shell prompt recognition and real generated dispatch JS with a fake native host.

The JS harness cannot access Terminal.app, clipboard, processes or operator state.
"""

import asyncio
import json
import shutil
import sys
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.session_manager import SessionInput


@pytest.mark.parametrize(
    "screen",
    [
        "➜  ~ ",
        "➜  project ",
        "➜  repo git:(main) ",
        "➜  KiraBridge git:(fix/visible-busy-idle-20261021) ✗ \n\n",
        "➜  café🧠 \n\n\n",
        "Last login: Friday\n➜  ~ cd -- /Users/operator\n➜  ~ \n\n",
        "host project% ",
        "host:project user$ \n\n",
        "KiraBridge visible % ",
        "previous output\nKiraBridge visible % \n\n",
        "KiraBridge fixture % ",
        # Terminal.app records zsh's PROMPT_SP marker and padding on the same
        # row as an unfinished output line, followed by the real prompt.
        "      --agent  agent to use  [string]%                   ➜  KiraBridge-Workspace ",
        "unfinished output%    KiraBridge visible % ",
    ],
)
def test_known_empty_prompts(screen):
    assert empty_shell_prompt(screen)


@pytest.mark.parametrize(
    "screen",
    [
        "➜  ~ echo harmless ",
        "➜  ~ echo",
        "➜  ~  ",
        "➜  ~\t",
        "➜ ~ ",
        "➜  ~",
        "➜  two words ",
        "➜  repo git:(main) typed ",
        "➜  repo git:(main) ✗ typed ",
        "➜  repo git:(main) ✗  ",
        "➜  repo git:(main)  ",
        "➜  repo git:(main) ✔ ",
        "➜  repo git:() ",
        "➜  ~ \n> ",
        "➜  ~ \n› ",
        "➜  ~ \x1b[31m",
        "➜  \u009b ",
        "➜  " + "a" * 241 + " ",
        "host% typed text ",
        # A prompt-like suffix inside typed text is not the live prompt. The
        # first marker is the real one and the rest is pending input.
        "➜  repo echo ➜  ~ ",
        "➜  repo echo%    ➜  ~ ",
        "[string]%                   ➜  KiraBridge-Workspace do not overwrite ",
        "unfinished output%    KiraBridge visible % do not overwrite ",
        "",
    ],
)
def test_input_or_unknown_prompts_stay_protected(screen):
    assert not empty_shell_prompt(screen)


@pytest.fixture
def direct_shell(bridge, config, monkeypatch):
    # Use the production client-type decision, not a monkeypatched direct() flag.
    config.principals["local"].client_type = "chatgpt"
    config.principals["local"].capabilities += ["session.inspect"]
    row = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 900,
        "tty": "/dev/ttys004",
        "transport": "terminal_app",
        "busy": False,
        "processes": [{"pid": 900, "ppid": 800, "name": "zsh", "image": "/bin/zsh"}],
    }
    identity = "501 ttys004 Fri Oct 30 01:00:00 2026"
    terminal = bridge.sessions.terminal_app
    monkeypatch.setattr(bridge.sessions, "selected", AsyncMock(return_value=row))
    monkeypatch.setattr(terminal, "process_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(terminal, "read", AsyncMock(return_value="➜  ~ \n\n"))
    # Executing this fallback would conceal a broken ChatGPT preflight path.
    monkeypatch.setattr(terminal, "send", AsyncMock(side_effect=AssertionError("raw send")))
    monkeypatch.setattr(terminal, "native", AsyncMock(side_effect=["➜  ~ \n\n", {"sent": True}]))
    return bridge, row, identity


def arguments(row):
    return SessionInput(
        pane_id=row["pane_id"], expected_pid=row["expected_pid"], text="printf harmless"
    )


async def test_chatgpt_session_input_task_uses_confirmed_shell_path(direct_shell):
    bridge, row, _ = direct_shell
    bridge.tasks.preflight = None
    value = request("session.input", arguments(row).model_dump())
    submit(bridge, value)
    task = bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds)
    await bridge.tasks._execute(task)
    persisted = bridge.store.get(value.task_id)
    assert persisted["state"] == State.COMPLETED
    terminal = bridge.sessions.terminal_app
    terminal.process_identity.assert_awaited_once_with(900)
    terminal.read.assert_awaited_once_with(row["pane_id"])
    assert terminal.native.await_count == 2
    sources = [call.args[0] for call in terminal.native.await_args_list]
    assert "app.doScript(" not in sources[0]
    assert sources[1].count("app.doScript(") == 1
    assert terminal.native.call_args.kwargs["mutation"] is True
    terminal.send.assert_not_awaited()


@pytest.mark.parametrize("failure", ["input", "busy", "tty", "intent"])
async def test_chatgpt_refusal_never_enters_native_dispatch(direct_shell, failure):
    bridge, row, _ = direct_shell
    terminal = bridge.sessions.terminal_app
    intent = AsyncMock()
    if failure == "input":
        terminal.read.return_value = "➜  ~ user command "
    elif failure == "busy":
        row["busy"] = True
    elif failure == "tty":
        terminal.process_identity.return_value = "501 ttys005 Fri Oct 30 01:00:00 2026"
    else:
        intent.side_effect = BridgeError("evidence_unavailable", "Cannot persist intent")
    with pytest.raises(BridgeError):
        await bridge.sessions.send("local", arguments(row), before_transport=intent)
    terminal.native.assert_not_awaited()
    terminal.send.assert_not_awaited()
    if failure != "intent":
        intent.assert_not_awaited()


@pytest.mark.parametrize(
    "screen",
    [
        "➜  ~ echo# ",
        "➜  ~ echo$ ",
        "➜  ~ echo% ",
        "➜  ~ # ",
        "➜ ~ echo$ ",
        " ➜  ~ echo# ",
        "\t➜  ~ echo% ",
        "➜  ~ echo KiraBridge visible % ",
        "host% echoKiraBridge visible % ",
        "KiraBridge visible % typed KiraBridge visible % ",
        "prefix KiraBridge visible % ",
    ],
)
async def test_typed_prompt_suffix_never_enters_transport_or_intent(direct_shell, screen):
    bridge, row, _ = direct_shell
    terminal = bridge.sessions.terminal_app
    terminal.read.return_value = screen
    intent = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.sessions.send("local", arguments(row), before_transport=intent)
    assert failure.value.code == "visible_input_not_empty"
    intent.assert_not_awaited()
    terminal.native.assert_not_awaited()
    terminal.send.assert_not_awaited()


async def test_prompt_sp_row_is_accepted_as_an_empty_shell(direct_shell):
    bridge, row, _ = direct_shell
    bridge.sessions.terminal_app.read.return_value = (
        "      --agent  agent to use  [string]%                   ➜  KiraBridge-Workspace "
    )
    intent = AsyncMock()
    result = await bridge.sessions.send("local", arguments(row), before_transport=intent)
    assert result["submitted"] and result["input_handed_to_transport"]
    intent.assert_awaited_once()
    bridge.sessions.terminal_app.send.assert_not_awaited()


async def test_prompt_sp_row_with_typed_suffix_stays_blocked(direct_shell):
    bridge, row, _ = direct_shell
    bridge.sessions.terminal_app.read.return_value = (
        "[string]%                   ➜  KiraBridge-Workspace do not overwrite "
    )
    intent = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.sessions.send("local", arguments(row), before_transport=intent)
    assert failure.value.code == "visible_input_not_empty"
    intent.assert_not_awaited()
    bridge.sessions.terminal_app.native.assert_not_awaited()


async def test_ambiguous_rendered_whitespace_preserves_input_before_intent(direct_shell):
    bridge, row, _ = direct_shell
    terminal = bridge.sessions.terminal_app
    # Erased cells and genuine pending spaces can share this visible line. No
    # visual normalization may turn either case into permission to send input.
    screen = "previous output\n➜  owned       \n\n"
    terminal.read.return_value = screen
    intent = AsyncMock()
    with pytest.raises(BridgeError) as failure:
        await bridge.sessions.send("local", arguments(row), before_transport=intent)
    assert failure.value.code == "visible_input_not_empty"
    assert str(failure.value) == (
        "Cannot verify an empty shell prompt; existing or ambiguous input is preserved"
    )
    terminal.read.assert_awaited_once_with(row["pane_id"])
    assert terminal.read.return_value == screen
    intent.assert_not_awaited()
    terminal.native.assert_not_awaited()
    terminal.send.assert_not_awaited()


async def run_dispatch_js(source, state):
    """Run the actual generated JS, substituting only the native Application host."""
    node = shutil.which("node")
    if node:
        command = [node, "-"]
    elif sys.platform == "darwin":
        command = ["/usr/bin/osascript", "-l", "JavaScript", "-"]
    else:
        pytest.skip("native dispatch JS requires node or macOS JavaScript runtime")
    harness = (
        "const state=" + json.dumps(state) + "; const calls=[];"
        "const tab={tty:()=>'/dev/ttys004',busy:()=>state.busy,"
        "contents:()=>state.screen,history:()=>state.screen};"
        "const win={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab};"
        "const windows=()=>[win]; windows.byId=()=>win;"
        "const app={running:()=>true,windows,activate:()=>{"
        "if(state.focusScreen!==undefined)state.screen=state.focusScreen;"
        "if(state.focusBusy)state.busy=true;},"
        "doScript:(text,target)=>{if(target.in!==tab)throw Error('wrong target');"
        "calls.push(text);}};"
        "const Application=name=>name==='System Events'?"
        "{processes:{byName:()=>({frontmost:()=>true})}}:app;const delay=()=>{};"
        "Application.currentApplication=()=>({doShellScript:()=>state.identity});"
        "let result;try{result={value:JSON.parse(eval("
        + json.dumps(source)
        + ")),calls,state};}catch(error){result={error:String(error),calls,state};}"
    )
    harness += (
        "process.stdout.write(JSON.stringify(result));" if node else "JSON.stringify(result);"
    )
    child = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(5):
            stdout, stderr = await child.communicate(harness.encode())
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
    assert child.returncode == 0, stderr.decode()
    return json.loads(stdout)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("none", None),
        ("before-input", "Selected terminal input changed"),
        ("before-prompt", "Selected terminal input changed"),
        ("focus-input", "Focused shell input is not empty"),
        ("focus-busy", "Selected terminal is busy"),
        ("busy", "Selected terminal is busy"),
        ("identity", "Selected target identity changed"),
    ],
)
async def test_actual_native_dispatch_guards_races(direct_shell, monkeypatch, change, error):
    bridge, row, identity = direct_shell
    terminal = bridge.sessions.terminal_app
    state = {"screen": terminal.read.return_value, "busy": False, "identity": identity}
    observed = []

    async def intent():
        if change == "before-input":
            state["screen"] = "➜  ~ user command "
        elif change == "before-prompt":
            # Even another supported empty prompt is a changed observation.
            state["screen"] = "host% "
        elif change == "focus-input":
            state["focusScreen"] = "➜  ~ user command "
        elif change == "focus-busy":
            state["focusBusy"] = True
        elif change == "busy":
            state["busy"] = True
        elif change == "identity":
            state["identity"] = identity.replace("01:00", "02:00")

    async def native(source, *, mutation=False):
        assert mutation
        result = await run_dispatch_js(source, state)
        observed.append(result)
        state.update(result["state"])
        if result.get("error"):
            raise BridgeError("fixture_native_refused", result["error"])
        return result["value"]

    monkeypatch.setattr(terminal, "native", native)
    if error:
        with pytest.raises(BridgeError, match=error) as failure:
            await bridge.sessions.send("local", arguments(row), before_transport=intent)
        assert all(result["calls"] == [] for result in observed)
        if change == "focus-input":
            assert failure.value.code == "visible_input_not_empty"
    else:
        result = await bridge.sessions.send("local", arguments(row), before_transport=intent)
        assert result["submitted"] and result["input_handed_to_transport"]
        assert [call for result in observed for call in result["calls"]] == ["printf harmless"]
    terminal.send.assert_not_awaited()
