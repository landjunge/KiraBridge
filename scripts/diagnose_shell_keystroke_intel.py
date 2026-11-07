"""Reproduce the old race input once per trial, retaining actual ZLE buffer evidence.

Only one new owned Intel Mac window; no pending text is submitted. A successful
diagnostic leaves that empty window for accept_shell_input_intel --owned-window.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import plistlib
import shlex
import time
from pathlib import Path

from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

TASK = "channel-8f3be0698a9c44e2822382b88e5f57cb"


async def diagnose(
    root,
    repeats,
    owned_window=None,
    without_preprobe=False,
    original_only=False,
    operation_id=TASK,
    prepare_only=False,
):
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise RuntimeError("Intel macOS required")
    if repeats < 3 or repeats > 5:
        raise ValueError("Use three to five controlled repetitions")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    terminal = TerminalAppTransport(asyncio.Lock())
    inventory = await terminal.window_inventory()
    original_ids = sorted(row["window_id"] for row in inventory["windows"])
    original_rows = await terminal.catalog()
    identities = {
        str(p["pid"]): await terminal.process_identity(p["pid"], detailed=True)
        for row in original_rows
        for p in row["processes"]
    }
    certificate = None
    if owned_window is not None:
        assert not owned_window.is_symlink() and owned_window.stat().st_uid == os.getuid()
        assert owned_window.resolve().is_relative_to(root.parent.resolve())
        certificate = json.loads(owned_window.read_text())
        assert certificate["task"] == operation_id and certificate["owner_uid"] == os.getuid()
        assert certificate["ready_for_acceptance"]
        handle = certificate["owned"]
        assert set(original_ids) == set(certificate["original_windows"]) | {
            int(handle["pane_id"].split(":")[1])
        }
        assert (
            await terminal.process_identity(handle["expected_pid"], detailed=True)
            == certificate["identity"]
        )
        original_ids = certificate["original_windows"]
        identities = certificate["original_identities"]
    evidence = {
        "task": operation_id,
        "trials": [],
        "original_windows": original_ids,
        "original_identities": identities,
        "state": "in_progress",
        "without_preprobe": without_preprobe,
        "prepare_only": prepare_only,
    }
    selected = plistlib.loads(
        (Path.home() / "Library/Preferences/com.apple.HIToolbox.plist").read_bytes()
    )
    evidence["selected_input_sources"] = selected.get("AppleSelectedInputSources")
    owned = None

    def save():
        (root / "diagnosis.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
        )

    async def screen():
        return await terminal.read(owned["pane_id"])

    async def idle():
        async with asyncio.timeout(15):
            while True:  # noqa: ASYNC110 -- bounded own UI observation
                rows = [r for r in await terminal.catalog() if r["pane_id"] == owned["pane_id"]]
                assert len(rows) == 1 and rows[0]["expected_pid"] == owned["expected_pid"]
                if not rows[0]["busy"]:
                    text = await screen()
                    if empty_shell_prompt(text):
                        return text
                await asyncio.sleep(0.1)

    async def guarded_keys(source, expected_screen):
        observed = await terminal.process_identity(owned["expected_pid"], detailed=True)
        assert observed == evidence["owned_identity"]
        return await terminal.native(
            terminal.native_focus(owned["pane_id"])
            + terminal.native_identity_guard({owned["expected_pid"]: observed})
            + "\ncheckFocus();"
            + terminal.native_screen_guard(expected_screen)
            + "\n"
            + source
            + "\nJSON.stringify({fixture_event_sent:true});",
            mutation=True,
        )

    async def zle_probe(expected_screen):
        for name in ("buffer.txt", "postdisplay.txt", "probe-ready.txt"):
            (root / name).unlink(missing_ok=True)
        await guarded_keys(
            'se.keyCode(7,{using:["control down"]}); se.keyCode(11,{using:["control down"]});',
            expected_screen,
        )
        async with asyncio.timeout(5):
            while (  # noqa: ASYNC110 -- bounded external ZLE witness
                not (root / "probe-ready.txt").exists()
                or (root / "probe-ready.txt").read_text() != "ready\n"
            ):
                await asyncio.sleep(0.05)
        return {
            name: (root / (name + ".txt")).read_text().removesuffix("\n")
            for name in ("buffer", "postdisplay")
        }

    try:
        if certificate is not None:
            matches = [
                r
                for r in await terminal.catalog()
                if r["pane_id"] == handle["pane_id"]
                and r["expected_pid"] == handle["expected_pid"]
                and r["tty"] == handle["tty"]
            ]
            assert len(matches) == 1 and not matches[0]["busy"]
            owned = matches[0]
            evidence["reused_certificate"] = str(owned_window)
        else:
            initial = (
                "cd -- "
                + shlex.quote(str(root))
                + "; HISTFILE="
                + shlex.quote(str(root / "history"))
            )
            opened = await terminal.open(initial)
            async with asyncio.timeout(15):
                while True:  # noqa: ASYNC110 -- exact new-window reconciliation
                    matches = [
                        r
                        for r in await terminal.catalog()
                        if r["tty"] == opened["tty"]
                        and int(r["pane_id"].split(":")[1]) not in original_ids
                    ]
                    if len(matches) == 1:
                        owned = matches[0]
                        break
                    await asyncio.sleep(0.1)
        current_ids = {r["window_id"] for r in (await terminal.window_inventory())["windows"]}
        assert current_ids - set(original_ids) == {int(owned["pane_id"].split(":")[1])}
        evidence["owned"] = {k: owned[k] for k in ("pane_id", "expected_pid", "tty")}
        evidence["owned_identity"] = await terminal.process_identity(
            owned["expected_pid"], detailed=True
        )
        await idle()
        setup = (
            'function _kb_issue51_probe() { builtin print -r -- "$BUFFER" > '
            + shlex.quote(str(root / "buffer.txt"))
            + '; builtin print -r -- "${POSTDISPLAY-}" > '
            + shlex.quote(str(root / "postdisplay.txt"))
            + "; builtin print -r -- ready > "
            + shlex.quote(str(root / "probe-ready.txt"))
            + "; }; zle -N _kb_issue51_probe; bindkey '^X^B' _kb_issue51_probe; "
            + "function _kb_issue51_clear() { local kb_expected; "
            + "IFS= builtin read -r kb_expected < "
            + shlex.quote(str(root / "clear-expected.txt"))
            + '; if [[ "$BUFFER" == "$kb_expected" ]]; '
            + "then BUFFER=''; CURSOR=0; POSTDISPLAY=''; "
            + "builtin print -r -- cleared > "
            + shlex.quote(str(root / "clear-ready.txt"))
            + "; else builtin print -r -- mismatch > "
            + shlex.quote(str(root / "clear-ready.txt"))
            + "; fi; }; zle -N _kb_issue51_clear; bindkey '^X^G' _kb_issue51_clear"
        )
        (root / "setup-command.txt").write_text(setup + "\n")
        await terminal.send_confirmed(
            owned, setup, await terminal.process_identity(owned["expected_pid"])
        )
        await idle()
        sequence = [("keystroke-original", "# KB_ACCEPT_RACE", 5.0)] * repeats
        if not original_only:
            sequence += [
                ("keystroke-ascii", "abc", 0.5),
                ("keystroke-symbol", "_", 0.5),
                ("keystroke-space", " ", 0.5),
            ]
            sequence += [("paste-original", "# KB_ACCEPT_RACE", 0.5)] * repeats
        if prepare_only:
            sequence = []
        for number, (method, requested, duration) in enumerate(sequence, 1):
            before = await idle()
            if not without_preprobe:
                assert (await zle_probe(before))["buffer"] == "", "Never replace pre-existing input"
            before = await screen()
            started = time.monotonic()
            if method.startswith("keystroke"):
                # Exact old event, once only. Do not retry missing/uncertain input.
                await guarded_keys("se.keystroke(" + json.dumps(requested) + ");", before)
            else:
                row = next(r for r in await terminal.catalog() if r["pane_id"] == owned["pane_id"])
                context = await terminal.prepare_shell_paste(row)
                await terminal.insert(
                    owned["pane_id"],
                    requested,
                    identity_guard=context["identities"],
                    expected_screen=context["screen"],
                    shell_snapshot=context["snapshot"],
                )
            event_duration = time.monotonic() - started
            started = time.monotonic()  # Match the old observation window AFTER event return.
            observations = []
            while True:
                observed = await screen()
                last = observed.rstrip("\n").split("\n")[-1]
                observations.append(
                    {
                        "elapsed": time.monotonic() - started,
                        "last_line": last,
                        "matches_old_suffix": last.endswith(" " + requested),
                    }
                )
                if time.monotonic() - started >= duration:
                    break
                await asyncio.sleep(0.2)
            (root / f"trial-{number}-screen.txt").write_text(observed)
            actual = await zle_probe(observed)
            item = {
                "number": number,
                "method": method,
                "requested": requested,
                "before_last_line": before.rstrip("\n").split("\n")[-1],
                "event_duration": event_duration,
                "observations": observations,
                "zle": actual,
                "buffer_codepoints": [f"U+{ord(c):04X}" for c in actual["buffer"]],
                "screen_sha256": hashlib.sha256(observed.encode()).hexdigest(),
            }
            evidence["trials"].append(item)
            save()
            print(
                json.dumps(
                    {
                        k: item[k]
                        for k in ("number", "method", "requested", "zle", "buffer_codepoints")
                    }
                ),
                flush=True,
            )
            # Never submit malformed text. Clear only this owned fixture's input.
            (root / "clear-expected.txt").write_text(actual["buffer"] + "\n")
            (root / "clear-ready.txt").unlink(missing_ok=True)
            current = await screen()
            await guarded_keys(
                'se.keyCode(7,{using:["control down"]}); se.keyCode(5,{using:["control down"]});',
                current,
            )
            async with asyncio.timeout(5):
                while (  # noqa: ASYNC110 -- complete owned widget acknowledgement
                    not (root / "clear-ready.txt").exists()
                    or (root / "clear-ready.txt").read_text() not in {"cleared\n", "mismatch\n"}
                ):
                    await asyncio.sleep(0.05)
            assert (root / "clear-ready.txt").read_text() == "cleared\n"
            after_clear = await screen()
            cleared = await zle_probe(after_clear)
            item["clear_witness"] = {
                "zle": cleared,
                "last_line": after_clear.rstrip("\n").split("\n")[-1],
                "recognized_empty_prompt": empty_shell_prompt(after_clear),
                "method": "own ZLE widget checks exact expected BUFFER before clearing",
            }
            save()
            assert cleared["buffer"] == "", "No Return until actual owned BUFFER is empty"
            # A verified empty-line Return redraws the prompt after erased screen cells.
            await terminal.press_return(
                owned["pane_id"],
                identity_guard={owned["expected_pid"]: evidence["owned_identity"]},
                expected_screen=await screen(),
            )
            await idle()
            # Actual empty BUFFER was witnessed before Return; do not invoke a pre-trial widget.
        assert sorted(
            r["window_id"] for r in (await terminal.window_inventory())["windows"]
        ) == sorted(original_ids + [int(owned["pane_id"].split(":")[1])])
        for pid, expected in identities.items():
            assert await terminal.process_identity(int(pid), detailed=True) == expected
        evidence["state"] = "complete_owned_window_ready"
        certificate = {
            "task": operation_id,
            "owner_uid": os.getuid(),
            "owned": evidence["owned"],
            "identity": evidence["owned_identity"],
            "original_windows": original_ids,
            "original_identities": identities,
            "ready_for_acceptance": True,
        }
        (root / "owned-window.json").write_text(json.dumps(certificate, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "window_left_idle_for_acceptance": evidence["owned"],
                    "certificate": str(root / "owned-window.json"),
                }
            ),
            flush=True,
        )
    except BaseException as error:
        evidence["state"] = "failed"
        evidence["error"] = repr(error)
        if owned is not None:
            rows = [r for r in await terminal.catalog() if r["pane_id"] == owned["pane_id"]]
            if (
                len(rows) == 1
                and rows[0]["expected_pid"] == owned["expected_pid"]
                and not rows[0]["busy"]
            ):
                evidence["failed_fixture_closed"] = await terminal.close_tab(owned["pane_id"])
                after = await terminal.window_inventory()
                evidence["failure_cleanup_windows"] = sorted(
                    r["window_id"] for r in after["windows"]
                )
                assert evidence["failure_cleanup_windows"] == original_ids
                for pid, expected in identities.items():
                    assert await terminal.process_identity(int(pid), detailed=True) == expected
                evidence["failure_cleanup_independently_verified"] = True
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--allow-one-owned-visible-window", action="store_true", required=True)
    parser.add_argument("--owned-window", type=Path)
    parser.add_argument("--without-preprobe", action="store_true")
    parser.add_argument("--original-only", action="store_true")
    parser.add_argument("--operation-id", default=TASK)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        diagnose(
            args.root.resolve(),
            args.repeats,
            args.owned_window,
            args.without_preprobe,
            args.original_only,
            args.operation_id,
            args.prepare_only,
        )
    )
