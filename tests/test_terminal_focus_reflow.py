"""Execute real generated JXA against a persistent synthetic tab-switch scene."""

import asyncio
import json
import shutil

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

SCENE = r"""
const readline=require('node:readline'),vm=require('node:vm');
const state={sent:0,focus:0,foreground:true,window:456,tty:'/dev/ttys004',
 history:'installed\nKiraBridge visible % \n\n',identity:'501 ttys004 Sun Nov 1 12:00:00 2026'};
const tab={tty:()=>state.tty,busy:()=>false,history:()=>state.history,
 contents:()=>{throw Error('Viewport contents must not replace the history tail');}};
const own={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab,name:()=> 'owned target'};
Object.defineProperty(own,'frontmost',{set:()=>{state.window=123;}});
Object.defineProperty(own,'index',{set:()=>{state.window=123;}});
const other={id:()=>456,selectedTab:()=>({tty:()=>'/dev/ttys005'})};
function windows(){return state.window===123?[own,other]:[other,own];}
windows.byId=id=>id===123?own:other;
const app={running:()=>true,windows,activate:()=>{state.focus++;state.foreground=true;
 state.history=state.focusHistory || 'installed\nKiraBridge visible % \n';
 if(state.focusInput)state.history+='user input';},doScript:()=>{state.sent++;}};
const owner={frontmost:()=>state.foreground};const processes={byName:()=>owner};
function Application(name){return name==='System Events'?{processes}:app;}
Application.currentApplication=()=>({doShellScript:()=>state.identity});
readline.createInterface({input:process.stdin}).on('line',line=>{
 const request=JSON.parse(line);
 if(request.focus_input)state.focusInput=true;
 if(request.focus_history)state.focusHistory=request.focus_history;
 if(request.change==='screen')state.history='installed\nKiraBridge visible % user input';
 if(request.change==='focus')state.foreground=false;
 if(request.change==='tab')state.window=456;
 if(request.change==='identity')state.identity+=' changed';
 if(request.change==='tty')state.tty='/dev/ttys999';
 try {const value=JSON.parse(vm.runInNewContext(request.source,{Application,delay:()=>{}}));
 process.stdout.write(JSON.stringify({value,state})+'\n');}
 catch(error){process.stdout.write(JSON.stringify({error:error.message,state})+'\n');}
});
"""


@pytest.mark.parametrize(
    "change", [None, "screen", "focus", "tab", "identity", "tty", "focus_input", "unicode"]
)
async def test_shell_focus_precedes_fresh_buffer_and_final_checks_never_reacquire(change):
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    child = await asyncio.create_subprocess_exec(
        node,
        "-e",
        SCENE,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        limit=512 * 1024,
    )
    observed, calls = {}, []
    focus_history = "a" * 70000 + "👩‍💻\nKiraBridge visible % "

    async def native(source, **kwargs):
        final = "app.doScript(" in source
        calls.append((source, kwargs.get("mutation", False)))
        child.stdin.write(
            (
                json.dumps(
                    {
                        "source": source,
                        "change": change if final else None,
                        "focus_input": change == "focus_input",
                        "focus_history": focus_history if change == "unicode" else None,
                    }
                )
                + "\n"
            ).encode()
        )
        await child.stdin.drain()
        value = json.loads(await asyncio.wait_for(child.stdout.readline(), 5))
        observed.update(value["state"])
        if "error" in value:
            raise BridgeError("native_guard_refused", value["error"])
        if kwargs.get("mutation") and not final:
            assert isinstance(value["value"], str)
            if change == "unicode":
                assert value["value"] == focus_history[-65536:]
        return value["value"]

    leaf = TerminalAppTransport(asyncio.Lock())
    leaf.native = native
    row = {"pane_id": "terminal:123:ttys004", "tty": "/dev/ttys004", "expected_pid": 345}
    try:
        refused = change not in {None, "unicode"}
        if refused:
            with pytest.raises(BridgeError):
                await leaf.send_confirmed(row, "/usr/bin/printf acceptance", observed_identity())
        else:
            await leaf.send_confirmed(row, "/usr/bin/printf acceptance", observed_identity())
        assert observed["sent"] == (0 if refused else 1)
        assert observed["focus"] == 1  # Never reacquire after the accepted buffer.
        assert sum(not mutation for _, mutation in calls) == 1
        assert len(calls) == (2 if change == "focus_input" else 3)
    finally:
        child.stdin.close()
        await asyncio.wait_for(child.wait(), 5)


def observed_identity():
    return "501 ttys004 Sun Nov 1 12:00:00 2026"


def test_focus_acquire_uses_fixed_attempts_inside_the_mutation_budget():
    source = TerminalAppTransport(asyncio.Lock()).native_focus("terminal:123:ttys004")
    assert "for (let focusAttempt=0; focusAttempt<8; focusAttempt++)" in source
    assert "if(focusAttempt===7) throw error;" in source
    assert "delay(0.25);" in source
    assert "Date.now()+2000" not in source
    assert TerminalAppTransport.FOCUS_ATTEMPTS == 8
    assert (
        TerminalAppTransport.MUTATION_SCRIPT_TIMEOUT
        > TerminalAppTransport.FOCUS_ATTEMPTS * TerminalAppTransport.FOCUS_POLL_DELAY
    )
    assert TerminalAppTransport.MUTATION_SCRIPT_TIMEOUT == 30
