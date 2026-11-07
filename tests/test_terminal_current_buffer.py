"""Executable native-reader/guard regressions; never access a host Terminal."""

import asyncio
import json
import shutil
import subprocess

import pytest

from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


@pytest.fixture
def javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")

    def run(source):
        result = subprocess.run(
            [node, "-e", source], capture_output=True, text=True, check=True, timeout=5
        )
        return json.loads(result.stdout)

    return run


@pytest.mark.parametrize(
    "history,viewport,expected_empty",
    [
        pytest.param(
            "installed\nKiraBridge visible % ",
            "old installation output without current prompt",
            True,
            id="scrolled-old-viewport-does-not-hide-current-empty-prompt",
        ),
        pytest.param(
            "installed\nKiraBridge visible % do not overwrite",
            "KiraBridge visible % ",
            False,
            id="old-empty-viewport-does-not-hide-real-current-input",
        ),
    ],
)
async def test_reader_uses_exact_selected_tabs_current_buffer(
    javascript, monkeypatch, history, viewport, expected_empty
):
    transport = TerminalAppTransport(asyncio.Lock())

    async def native(source, **kwargs):
        # Execute the actual target selection and reader against several views.
        # Reading any viewport is a failure; it is never a fallback input source.
        return javascript(
            "const makeTab=(tty,history)=>({tty:()=>tty,history:()=>history,"
            "contents:()=>{throw Error('Viewport is not an input observation');}});"
            "const foreign=makeTab('/dev/ttys001','foreign pending input');"
            "const selected=makeTab('/dev/ttys004',"
            + json.dumps(history)
            + ");const other=makeTab('/dev/ttys003','other tab pending input');"
            "const views=[{id:()=>99,tabs:()=>[foreign]},"
            "{id:()=>123,tabs:()=>[other,selected]}];"
            "const windows=()=>views;windows.byId=id=>views.find(v=>v.id()===id);"
            "function Application(){return {running:()=>true,windows};}"
            "process.stdout.write(eval(" + json.dumps(source) + "));"
        )

    monkeypatch.setattr(transport, "native", native)
    observed = await transport.read("terminal:123:ttys004")
    assert observed == history
    assert observed != viewport
    assert empty_shell_prompt(observed) is expected_empty


@pytest.mark.parametrize(
    "observed,expected,blocked",
    [
        ("KiraBridge visible % ", "KiraBridge visible % ", False),
        ("KiraBridge visible % user input", "KiraBridge visible % ", True),
        ("KiraBridge visible % ", "KiraBridge visible % user input", True),
        ("new activity\n› ", "old activity\n› ", True),
    ],
)
def test_native_guard_freezes_current_input_not_viewport(javascript, observed, expected, blocked):
    guard = TerminalAppTransport.native_screen_guard(expected)
    value = javascript(
        "let inputCalls=0,viewportReads=0;const tab={history:()=>"
        + json.dumps(observed)
        + ",contents:()=>{viewportReads++;return 'unrelated viewport';}};"
        "let blocked=false;try {" + guard + ";inputCalls++;}catch(error){blocked=true;}"
        "process.stdout.write(JSON.stringify({blocked,inputCalls,viewportReads}));"
    )
    assert value == {"blocked": blocked, "inputCalls": 0 if blocked else 1, "viewportReads": 0}


def test_missing_current_buffer_never_falls_back_to_empty_viewport(javascript):
    expression = TerminalAppTransport.native_input_tail(65536)
    value = javascript(
        "let viewportReads=0;const tab={history:()=>{throw Error('unavailable');},"
        "contents:()=>{viewportReads++;return 'KiraBridge visible % ';}};"
        "let refused=false;try {" + expression + ";}catch(error){refused=true;}"
        "process.stdout.write(JSON.stringify({refused,viewportReads}));"
    )
    assert value == {"refused": True, "viewportReads": 0}


def test_native_read_tail_bounds_complete_unicode_points(javascript):
    text = "old output\n" + "🧠" * 70000 + "\nKiraBridge visible % "
    observed = javascript(
        "const tab={history:()=> 'old output\\n'+'🧠'.repeat(70000)"
        "+'\\nKiraBridge visible % '};process.stdout.write(JSON.stringify("
        + TerminalAppTransport.native_input_tail(65536)
        + "));"
    )
    assert observed == text[-65536:]
