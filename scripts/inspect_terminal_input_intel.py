"""Inspect only a freshly certified owned shell: raw key bytes, ZLE state and AX.

This diagnostic never accepts pending text as a command. It leaves the owned empty
window for the separate complete acceptance, which independently closes it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

RAW = """import json,os,selectors,sys,termios,time,tty
from pathlib import Path
root=Path(sys.argv[1]);fd=sys.stdin.fileno();saved=termios.tcgetattr(fd)
events=[];start=time.monotonic();selector=selectors.DefaultSelector()
try:
 tty.setraw(fd);selector.register(fd,selectors.EVENT_READ)
 (root/"raw-ready.tmp").write_text(json.dumps({"pid":os.getpid(),"tty":os.ttyname(fd)}))
 (root/"raw-ready.tmp").replace(root/"raw-ready.json")
 while time.monotonic()-start<45 and not (root/"raw-stop").exists():
  if selector.select(.05):
   data=os.read(fd,256)
   if not data:break
   events.append({"elapsed":time.monotonic()-start,"hex":data.hex(),"phase":(root/"phase").read_text()})
   (root/"raw-live.tmp").write_text(json.dumps(events));(root/"raw-live.tmp").replace(root/"raw-live.json")
finally:
 termios.tcsetattr(fd,termios.TCSANOW,saved);selector.close()
 restored=termios.tcgetattr(fd)==saved
 (root/"raw-events.tmp").write_text(json.dumps(events,indent=2))
 (root/"raw-events.tmp").replace(root/"raw-events.json")
 (root/"raw-restored.tmp").write_text(json.dumps({"restored":restored}))
 (root/"raw-restored.tmp").replace(root/"raw-restored.json")
print("KB_RAW_TTY_RESTORED",flush=True)
"""

AX = """
checkFocus();
const nativeBefore=tab.contents().slice(-65536);
const axwin=se.processes.byName('Terminal').windows()[0];
if(axwin.name()!==targetWindow.name()) throw Error('AX window mismatch');
function val(e,n){try{return {value:e.attributes.byName(n).value()};}
 catch(error){return {error:String(error)};}}
const text=[];let count=0;
function visit(e,depth){if(++count>200||depth>8)return;let role='';
 try{role=e.role();}catch(error){}
 if(role==='AXTextArea')text.push({role,value:val(e,'AXValue'),
  selectedRange:val(e,'AXSelectedTextRange'),selectedRanges:val(e,'AXSelectedTextRanges'),
  insertionLine:val(e,'AXInsertionPointLineNumber'),selectedText:val(e,'AXSelectedText'),
  visibleRange:val(e,'AXVisibleCharacterRange'),numberOfCharacters:val(e,'AXNumberOfCharacters')});
 try{e.uiElements().forEach(c=>visit(c,depth+1));}catch(error){}
}
visit(axwin,0);checkFocus();
if(tab.contents().slice(-65536)!==nativeBefore)throw Error('Selected terminal input changed');
JSON.stringify({nativeWindow:targetWindow.id(),tty:tab.tty(),nativeContents:nativeBefore,text});
"""


async def inspect(root, certificate_path, operation_id):
    assert not certificate_path.is_symlink() and certificate_path.stat().st_uid == os.getuid()
    assert certificate_path.resolve().is_relative_to(root.parent.resolve())
    certificate = json.loads(certificate_path.read_text())
    assert certificate["owner_uid"] == os.getuid() and certificate["ready_for_acceptance"]
    assert certificate["task"] == operation_id
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    widget_root = certificate_path.parent
    row = certificate["owned"]
    terminal = TerminalAppTransport(asyncio.Lock())
    assert terminal.available
    identity = certificate["identity"]
    assert await terminal.process_identity(row["expected_pid"], detailed=True) == identity
    before = await terminal.window_inventory()
    expected = set(certificate["original_windows"]) | {int(row["pane_id"].split(":")[1])}
    assert {r["window_id"] for r in before["windows"]} == expected
    evidence = {"owned": row, "states": [], "key_phases": [], "state": "in_progress"}

    def save():
        (root / "inspection.json").write_text(json.dumps(evidence, indent=2) + "\n")

    async def screen():
        return await terminal.read(row["pane_id"])

    async def keys(code, *, child_identity=None):
        assert await terminal.process_identity(row["expected_pid"], detailed=True) == identity
        identities = {row["expected_pid"]: identity}
        if child_identity:
            identities.update(child_identity)
        await terminal.native(
            terminal.native_focus(row["pane_id"])
            + terminal.native_identity_guard(identities)
            + "\ncheckFocus();"
            + terminal.native_screen_guard(await screen())
            + "\n"
            + code
            + "\nJSON.stringify({fixture_event_sent:true});",
            mutation=True,
        )

    async def probe():
        (widget_root / "probe-ready.txt").unlink(missing_ok=True)
        await keys(
            'se.keyCode(7,{using:["control down"]});se.keyCode(11,{using:["control down"]});'
        )
        async with asyncio.timeout(5):
            while (  # noqa: ASYNC110 -- complete private widget receipt
                not (widget_root / "probe-ready.txt").exists()
                or (widget_root / "probe-ready.txt").read_text() != "ready\n"
            ):
                await asyncio.sleep(0.05)
        return {
            name: (widget_root / (name + ".txt")).read_text().removesuffix("\n")
            for name in ("buffer", "postdisplay", "cursor", "keymap", "lastwidget", "keys")
        }

    async def assign(value, cursor):
        observed = await probe()
        assert observed["buffer"] in {"", "abcdef", "   ", "# KB_CTRL_U", "\t"}
        (root / "assign-expected").write_text(observed["buffer"] + "\n")
        (root / "assign-new").write_text(value + "\n")
        (root / "assign-cursor").write_text(str(cursor) + "\n")
        (root / "assign-ready").unlink(missing_ok=True)
        await keys('se.keyCode(7,{using:["control down"]});se.keyCode(5,{using:["control down"]});')
        async with asyncio.timeout(5):
            while (  # noqa: ASYNC110 -- complete own fixture ack
                not (root / "assign-ready").exists()
                or (root / "assign-ready").read_text() not in {"assigned\n", "mismatch\n"}
            ):
                await asyncio.sleep(0.05)
        assert (root / "assign-ready").read_text() == "assigned\n"
        assert (await probe())["buffer"] == value

    async def refresh():
        await assign("", 0)
        assert (await probe())["buffer"] == ""
        await terminal.press_return(
            row["pane_id"],
            identity_guard={row["expected_pid"]: identity},
            expected_screen=await screen(),
        )
        async with asyncio.timeout(15):
            while not empty_shell_prompt(await screen()):  # noqa: ASYNC110 -- own empty redraw
                await asyncio.sleep(0.1)

    async def state(name):
        ax = await terminal.native(
            terminal.native_focus(row["pane_id"])
            + terminal.native_identity_guard({row["expected_pid"]: identity})
            + AX
        )
        rendered = ax.pop("nativeContents")
        logical = await probe()
        record = {
            "name": name,
            "last_line": rendered.rstrip("\n").split("\n")[-1],
            "screen_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "recognized_empty": empty_shell_prompt(rendered),
            "zle": logical,
            "ax": ax,
        }
        (root / (name + "-screen.txt")).write_text(rendered)
        evidence["states"].append(record)
        save()
        print(
            json.dumps({k: record[k] for k in ("name", "last_line", "recognized_empty", "zle")}),
            flush=True,
        )

    try:
        assert empty_shell_prompt(await screen())
        witness = "function _kb_issue51_probe() { "
        for name, expression in [
            ("buffer", "$BUFFER"),
            ("postdisplay", "${POSTDISPLAY-}"),
            ("cursor", "$CURSOR"),
            ("keymap", "$KEYMAP"),
            ("lastwidget", "$LASTWIDGET"),
            ("keys", "$KEYS"),
        ]:
            witness += 'builtin print -r -- "' + expression + '" > '
            witness += shlex.quote(str(widget_root / (name + ".txt"))) + "; "
        witness += "builtin print -r -- ready > " + shlex.quote(
            str(widget_root / "probe-ready.txt")
        )
        witness += "; }; zle -N _kb_issue51_probe; bindkey '^X^B' _kb_issue51_probe; "
        setup = witness + (
            "function _kb_finish_assign() { local e n c; IFS= builtin read -r e < "
            + shlex.quote(str(root / "assign-expected"))
            + "; IFS= builtin read -r n < "
            + shlex.quote(str(root / "assign-new"))
            + "; IFS= builtin read -r c < "
            + shlex.quote(str(root / "assign-cursor"))
            + '; if [[ $BUFFER == "$e" && $c == <-> ]]; '
            + "then BUFFER=\"$n\"; CURSOR=$c; POSTDISPLAY=''; "
            + "builtin print -r -- assigned > "
            + shlex.quote(str(root / "assign-ready"))
            + "; else builtin print -r -- mismatch > "
            + shlex.quote(str(root / "assign-ready"))
            + "; fi; }; zle -N _kb_finish_assign; bindkey '^X^G' _kb_finish_assign; "
            + "bindkey '^U' > "
            + shlex.quote(str(root / "ctrl-u-binding.txt"))
            + "; builtin print -r -- $KEYMAP > "
            + shlex.quote(str(root / "initial-keymap.txt"))
        )
        await terminal.send_confirmed(
            row, setup, await terminal.process_identity(row["expected_pid"])
        )
        async with asyncio.timeout(15):
            while not empty_shell_prompt(await screen()):  # noqa: ASYNC110 -- setup shell completion
                await asyncio.sleep(0.1)
        await state("initial-empty")
        for trial in range(1, 4):
            await refresh()
            current = next(r for r in await terminal.catalog() if r["pane_id"] == row["pane_id"])
            context = await terminal.prepare_shell_paste(current)
            await terminal.insert(
                row["pane_id"],
                "# KB_CTRL_U",
                identity_guard=context["identities"],
                expected_screen=context["screen"],
                shell_snapshot=context["snapshot"],
            )
            await keys('se.keyCode(32,{using:["control down"]});')
            await state(f"ctrl-u-{trial}")
        await refresh()
        await assign("abcdef", 6)
        await assign("", 0)
        await state("empty-erased-padding")
        await assign("   ", 0)
        await state("pending-spaces-home")
        await refresh()

        # A bounded foreground raw reader separates emitted key bytes from ZLE behavior.
        payload = root / "raw_fixture.py"
        payload.write_text(RAW)
        (root / "phase").write_text("starting")
        command = shlex.join([sys.executable, str(payload), str(root)])
        await terminal.send_confirmed(
            row, command, await terminal.process_identity(row["expected_pid"])
        )
        async with asyncio.timeout(10):
            while not (root / "raw-ready.json").exists():  # noqa: ASYNC110 -- owned child receipt
                await asyncio.sleep(0.05)
        child = json.loads((root / "raw-ready.json").read_text())
        assert child["tty"] == row["tty"]
        child_id = await terminal.process_identity(child["pid"], detailed=True)
        for name, code, expected_hex in [
            ("ctrl-u", 'se.keyCode(32,{using:["control down"]});', "15"),
            ("tab-control", "se.keyCode(48);", "09"),
            (
                "probe-chord",
                'se.keyCode(7,{using:["control down"]});se.keyCode(11,{using:["control down"]});',
                "1802",
            ),
        ]:
            for trial in range(1, 4):
                phase = f"{name}-{trial}"
                (root / "phase").write_text(phase)
                await keys(code, child_identity={child["pid"]: child_id})
                async with asyncio.timeout(5):
                    while True:  # noqa: ASYNC110 -- read own foreground byte receipt
                        live = (
                            json.loads((root / "raw-live.json").read_text())
                            if (root / "raw-live.json").exists()
                            else []
                        )
                        actual_hex = "".join(e["hex"] for e in live if e["phase"] == phase)
                        if len(actual_hex) >= len(expected_hex):
                            break
                        await asyncio.sleep(0.05)
                await asyncio.sleep(0.3)  # Retain a quiet interval before changing the phase label.
                live = json.loads((root / "raw-live.json").read_text())
                actual_hex = "".join(e["hex"] for e in live if e["phase"] == phase)
                evidence["key_phases"].append(
                    {
                        "phase": phase,
                        "expected_hex": expected_hex,
                        "actual_hex": actual_hex,
                        "matches": actual_hex == expected_hex,
                    }
                )
        (root / "raw-stop").write_text("stop only own bounded fixture\n")
        async with asyncio.timeout(10):
            while not (root / "raw-restored.json").exists():  # noqa: ASYNC110 -- restored tty witness
                await asyncio.sleep(0.1)
        evidence["raw_events"] = json.loads((root / "raw-events.json").read_text())
        evidence["raw_tty_restoration"] = json.loads((root / "raw-restored.json").read_text())
        assert evidence["raw_tty_restoration"]["restored"]
        assert len(evidence["key_phases"]) == 9
        evidence["raw_all_phase_bytes_match_expected"] = all(
            p["matches"] for p in evidence["key_phases"]
        )
        async with asyncio.timeout(15):
            while not empty_shell_prompt(await screen()):  # noqa: ASYNC110 -- own raw fixture exit
                await asyncio.sleep(0.1)
        await refresh()
        # Restore the original diagnostic clear binding before handing off this window.
        await terminal.send_confirmed(
            row,
            "bindkey '^X^G' _kb_issue51_clear",
            await terminal.process_identity(row["expected_pid"]),
        )
        async with asyncio.timeout(15):
            while not empty_shell_prompt(await screen()):  # noqa: ASYNC110 -- final owned prompt
                await asyncio.sleep(0.1)
        assert await terminal.process_identity(row["expected_pid"], detailed=True) == identity
        assert {r["window_id"] for r in (await terminal.window_inventory())["windows"]} == expected
        for pid, original in certificate["original_identities"].items():
            assert await terminal.process_identity(int(pid), detailed=True) == original
        evidence["original_windows_processes_preserved"] = True
        evidence["state"] = "complete_owned_window_ready"
    except BaseException as error:
        evidence["state"] = "failed"
        evidence["error"] = repr(error)
        raise
    finally:
        if (root / "raw-ready.json").exists() and not (root / "raw-restored.json").exists():
            (root / "raw-stop").write_text("stop only owned raw reader on diagnostic failure\n")
            try:
                async with asyncio.timeout(10):
                    while not (root / "raw-restored.json").exists():  # noqa: ASYNC110 -- own cleanup receipt
                        await asyncio.sleep(0.1)
                evidence["failure_raw_restoration"] = json.loads(
                    (root / "raw-restored.json").read_text()
                )
            except TimeoutError:
                evidence["failure_raw_restoration"] = {
                    "restored": "unverified; do not reuse window"
                }
        save()
    print(
        json.dumps({"state": evidence["state"], "raw_events": evidence["raw_events"]}), flush=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owned-window", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    options = parser.parse_args()
    asyncio.run(inspect(options.root.resolve(), options.owned_window, options.operation_id))
