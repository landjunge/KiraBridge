"""Execute real generated JXA against a persistent synthetic tab-switch scene."""

import asyncio
import json
import shutil

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

SCENE = r"""
const readline=require('node:readline'),vm=require('node:vm');
const state={sent:0,focus:0,foreground:true,window:456,
 history:'installed\nKiraBridge visible % \n\n',identity:'501 ttys004 Sun Nov 1 12:00:00 2026'};
const tab={tty:()=>'/dev/ttys004',busy:()=>false,history:()=>state.history};
const own={id:()=>123,tabs:()=>[tab],selectedTab:()=>tab,name:()=> 'owned target'};
Object.defineProperty(own,'frontmost',{set:()=>{state.window=123;}});
Object.defineProperty(own,'index',{set:()=>{state.window=123;}});
const other={id:()=>456,selectedTab:()=>({tty:()=>'/dev/ttys005'})};
function windows(){return state.window===123?[own,other]:[other,own];}
windows.byId=id=>id===123?own:other;
const app={running:()=>true,windows,activate:()=>{state.focus++;state.foreground=true;
 state.history='installed\nKiraBridge visible % \n';},doScript:()=>{state.sent++;}};
const owner={frontmost:()=>state.foreground};const processes={byName:()=>owner};
function Application(name){return name==='System Events'?{processes}:app;}
Application.currentApplication=()=>({doShellScript:()=>state.identity});
readline.createInterface({input:process.stdin}).on('line',line=>{
 const request=JSON.parse(line);
 if(request.change==='screen')state.history='installed\nKiraBridge visible % user input';
 if(request.change==='focus')state.foreground=false;
 if(request.change==='tab')state.window=456;
 if(request.change==='identity')state.identity+=' changed';
 try {const value=JSON.parse(vm.runInNewContext(request.source,{Application,delay:()=>{}}));
 process.stdout.write(JSON.stringify({value,state})+'\n');}
 catch(error){process.stdout.write(JSON.stringify({error:error.message,state})+'\n');}
});
"""


@pytest.mark.parametrize("change", [None, "screen", "focus", "tab", "identity"])
async def test_shell_focus_precedes_fresh_buffer_and_final_checks_never_reacquire(change):
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    child = await asyncio.create_subprocess_exec(
        node, "-e", SCENE, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
    )
    observed = {}

    async def native(source, **kwargs):
        final = "app.doScript(" in source
        child.stdin.write(
            (json.dumps({"source": source, "change": change if final else None}) + "\n").encode()
        )
        await child.stdin.drain()
        value = json.loads(await asyncio.wait_for(child.stdout.readline(), 5))
        observed.update(value["state"])
        if "error" in value:
            raise BridgeError("native_guard_refused", value["error"])
        return value["value"]

    leaf = TerminalAppTransport(asyncio.Lock())
    leaf.native = native
    row = {"pane_id": "terminal:123:ttys004", "tty": "/dev/ttys004", "expected_pid": 345}
    try:
        if change:
            with pytest.raises(BridgeError):
                await leaf.send_confirmed(row, "/usr/bin/printf acceptance", observed_identity())
        else:
            await leaf.send_confirmed(row, "/usr/bin/printf acceptance", observed_identity())
        assert observed["sent"] == (0 if change else 1)
        assert observed["focus"] == 1  # Never reacquire after the accepted buffer.
    finally:
        child.stdin.close()
        await asyncio.wait_for(child.wait(), 5)


def observed_identity():
    return "501 ttys004 Sun Nov 1 12:00:00 2026"
