"""Intel macOS lifecycle acceptance using one owned head fixture at a time.

This proves native closed-window/TTY reuse and reservation release. It does not
send work to Codex/Grok, paste, press Return or claim a product handoff succeeded.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shlex
import signal
import subprocess
import uuid
from pathlib import Path

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    VisibleTerminalBinding,
)
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.visible_binding import identities_disjoint, overlay_path


async def accept(root: Path, *, allow_one_owned_visible_window: bool):
    if not allow_one_owned_visible_window:
        raise RuntimeError("Explicit --allow-one-owned-visible-window is required")
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise RuntimeError("Actual Intel macOS is required")
    source = Path(__file__).resolve().parents[1] / "src" / "kirabridge"
    if not Path(kirabridge.__file__).resolve().is_relative_to(source):
        raise RuntimeError("Run the worktree source, not the installed production package")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    config = Config(
        data_dir=str(root / "state"),
        agents={"head": AgentConfig(kind="grok_acp")},
        principals={
            "test": PrincipalConfig(
                capabilities=["session.inspect", "task.read", "message.send", "message.read"],
                roots=[str(workspace)],
                message_peers=["head"],
                agents=["head"],
                approval_mode="automatic",
            ),
            "head": PrincipalConfig(
                capabilities=["message.read"],
                message_peers=["test"],
                approval_mode="automatic",
            ),
        },
    )
    assert config.visible_handoffs.enabled is True
    bridge = Bridge(config)
    transport = bridge.sessions.terminal_app
    initial_inventory = await transport.window_inventory()
    initial_windows = {row["window_id"] for row in initial_inventory["windows"]}
    initial_native_ttys = {row["window_id"]: row["ttys"] for row in initial_inventory["windows"]}
    initial_rows = await transport.catalog()
    assert not transport.last_catalog_incomplete, "Initial native catalogue is incomplete"
    initial_ttys = {row["tty"] for row in initial_rows}
    original_identities = {
        process["pid"]: await transport.process_identity(process["pid"], detailed=True)
        for row in initial_rows
        for process in row["processes"]
    }
    evidence = {
        "platform": platform.platform(),
        "version": kirabridge.__version__,
        "package": str(Path(kirabridge.__file__).resolve()),
        "scope": "native owned head fixtures; no Codex/Grok handoff or paste/Return acceptance",
        "production_modified": False,
        "initial_windows": sorted(initial_windows),
        "initial_processes": sorted(original_identities),
        "fixtures": [],
        "cycles": [],
        "checks": [],
        "forbidden_input_calls": [],
        "acceptance": "in_progress",
    }
    owned = None
    restarted = None
    failure = None
    retained = {}

    def checkpoint():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def check(name, **detail):
        record = {"name": name, **detail}
        evidence["checks"].append(record)
        checkpoint()
        print(json.dumps(record), flush=True)

    async def forbid_input(*args, **kwargs):
        evidence["forbidden_input_calls"].append("unexpected native input route")
        raise AssertionError("Acceptance must never paste, submit or replay input")

    def guard_input_routes(candidate):
        for owner in (candidate.sessions, candidate.sessions.terminal_app):
            for method in ("insert", "send", "send_confirmed", "press_return"):
                if hasattr(owner, method):
                    setattr(owner, method, forbid_input)

    guard_input_routes(bridge)

    async def unchanged_originals():
        for pid, expected in original_identities.items():
            assert await transport.process_identity(pid, detailed=True) == expected, (
                "A pre-existing process identity changed"
            )
        inventory = await transport.window_inventory()
        actual = {row["window_id"] for row in inventory["windows"]}
        allowed = initial_windows | ({owned["window_id"]} if owned is not None else set())
        assert actual == allowed, "Native window inventory changed outside the owned fixture"
        for row in inventory["windows"]:
            if row["window_id"] in initial_windows:
                assert row["ttys"] == initial_native_ttys[row["window_id"]], (
                    "An original scripting window's native tabs changed"
                )
        return inventory

    async def single_native_tty(window_id, tty):
        # Visual tab_count groups windows by bounds/preferences; it is not the
        # scripting window's tabs(). Close only our exact new scripting object.
        inventory = await transport.window_inventory()
        matches = [row for row in inventory["windows"] if row["window_id"] == window_id]
        assert len(matches) == 1 and matches[0]["ttys"] == [tty], (
            "The owned scripting window must contain exactly its own TTY"
        )

    async def fixture(number):
        nonlocal owned
        assert owned is None, "Keep at most one additional fixture window open"
        await unchanged_originals()
        receipt = workspace / f"head-{number}.txt"
        marker = "KB_CLOSED_READY_" + uuid.uuid4().hex
        command = (
            "cd "
            + shlex.quote(str(workspace))
            + " && /usr/bin/printf '%s\\n' "
            + shlex.quote(marker)
            + " && /usr/bin/head -n 1 > "
            + shlex.quote(str(receipt))
        )
        opened = await transport.open(command)
        tty = opened["tty"]
        evidence["latest_open"] = {"number": number, "tty": tty, "identity_verified": False}
        checkpoint()
        assert tty not in initial_ttys, "Never adopt an original user's TTY"
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- bounded real process/window observation
                rows = await transport.catalog()
                assert not transport.last_catalog_incomplete, "Native catalogue is incomplete"
                candidates = [row for row in rows if row["tty"] == tty]
                if len(candidates) == 1:
                    row = candidates[0]
                    heads = [process for process in row["processes"] if process["name"] == "head"]
                    if len(heads) == 1:
                        break
                await asyncio.sleep(0.1)
        assert row["window_id"] not in initial_windows
        assert not row["identity_ambiguous"]
        head = heads[0]
        assert head["image"] == "/usr/bin/head" and head["ppid"] == row["expected_pid"]
        assert head["pid"] != row["expected_pid"]
        identities = {
            pid: await transport.process_identity(pid, detailed=True)
            for pid in (row["expected_pid"], head["pid"])
        }
        for pid, identity in identities.items():
            fields = identity.split(None, 8)
            process = next(process for process in row["processes"] if process["pid"] == pid)
            assert len(fields) == 9 and int(fields[0]) == os.getuid()
            assert fields[1] == Path(tty).name
            assert int(fields[7]) == process["ppid"] and fields[8] == process["image"]
        stat = receipt.stat()
        assert stat.st_uid == os.getuid() and receipt.read_bytes() == b""
        descriptor = await asyncio.to_thread(
            subprocess.check_output,
            [
                "/usr/sbin/lsof",
                "-n",
                "-a",
                "-p",
                str(head["pid"]),
                "-d",
                "1",
                "-Fpin",
                "--",
                str(receipt),
            ],
            text=True,
            timeout=5,
        )
        assert f"p{head['pid']}\n" in descriptor
        assert f"i{stat.st_ino}\n" in descriptor and "n" + str(receipt) + "\n" in descriptor
        binding = VisibleTerminalBinding(
            pane_id=row["pane_id"],
            expected_pid=row["expected_pid"],
            agent_pid=head["pid"],
            ready_pattern=r"(?m)^KB_CLOSED_READY_[0-9a-f]{32}$",
            busy_pattern="",
        )
        owned = {
            "number": number,
            "window_id": row["window_id"],
            "tty": tty,
            "binding": binding.model_dump(),
            "identities": identities,
            "receipt": str(receipt),
            "receipt_inode": stat.st_ino,
            "receipt_device": stat.st_dev,
            "private_stdout_fd_verified": True,
            "head_termination_attempted": False,
            "visual_tab_count": row.get("tab_count"),
        }
        evidence["fixtures"].append(owned)
        evidence["latest_open"]["identity_verified"] = True
        checkpoint()
        await single_native_tty(owned["window_id"], tty)
        owned["native_single_tty_script_window_verified"] = True
        await unchanged_originals()
        check("opened one fresh owned head fixture", number=number, pane_id=binding.pane_id)
        return binding

    def retain_unknown(binding, identifier):
        message = bridge.messages._send(
            "test",
            MessageSend(
                recipient="head",
                conversation_id=identifier,
                idempotency_key=identifier,
                body="Private unresolved fixture; never replay or execute",
                dispatch=False,
            ),
            visible_internal=True,
        )
        bridge.store.db.execute(
            "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                "test",
                "head",
                "private-fixture-hash",
                canonical(binding.model_dump()),
                message["id"],
                "unknown",
                1,
                1,
                canonical({"terminal_input_attempted": False, "automatic_retry": False}),
            ),
        )
        bridge.store.db.execute(
            "INSERT INTO visible_handoff_events(id,at,state,evidence) VALUES(?,1,'unknown',?)",
            (identifier, canonical({"private_fixture": True, "terminal_input_attempted": False})),
        )
        retained[identifier] = history(identifier)
        return bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()

    def history(identifier):
        row = dict(
            bridge.store.db.execute(
                "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
            ).fetchone()
        )
        events = [
            tuple(item)
            for item in bridge.store.db.execute(
                "SELECT * FROM visible_handoff_events WHERE id=? ORDER BY seq", (identifier,)
            )
        ]
        message = dict(
            bridge.store.db.execute(
                "SELECT * FROM messages WHERE id=?", (row["message_id"],)
            ).fetchone()
        )
        return hashlib.sha256(
            canonical({"row": row, "events": events, "message": message}).encode()
        ).hexdigest()

    async def close_owned():
        nonlocal owned
        if owned is None:
            return
        item = owned
        binding = VisibleTerminalBinding.model_validate(item["binding"])
        await unchanged_originals()
        if not item["head_termination_attempted"]:
            for pid, expected in item["identities"].items():
                assert await transport.process_identity(pid, detailed=True) == expected
            assert Path(item["receipt"]).stat().st_ino == item["receipt_inode"]
            assert Path(item["receipt"]).read_bytes() == b""
            item["head_termination_attempted"] = True
            checkpoint()
            os.kill(binding.agent_pid, signal.SIGTERM)
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- bounded owned child exit and shell redraw
                pids = await transport.process_ids()
                rows = [
                    row for row in await transport.catalog() if row["pane_id"] == binding.pane_id
                ]
                if binding.agent_pid not in pids and len(rows) == 1:
                    row = rows[0]
                    assert row["expected_pid"] == binding.expected_pid
                    assert not row["identity_ambiguous"]
                    if not row["busy"]:
                        screen = await transport.read(binding.pane_id)
                        if empty_shell_prompt(screen):
                            break
                await asyncio.sleep(0.1)
        assert (
            await transport.process_identity(binding.expected_pid, detailed=True)
            == item["identities"][binding.expected_pid]
        )
        await single_native_tty(item["window_id"], item["tty"])
        source = (
            transport.native_target(binding.pane_id)
            + transport.native_identity_guard(
                {binding.expected_pid: item["identities"][binding.expected_pid]}
            )
            + "\nif(tab.busy()) throw Error('Owned fixture remains busy; preserve');"
            + "\nif(targetWindow.tabs().length!==1) throw Error('Other tabs; preserve');"
            + "\nif("
            + transport.native_input_tail(65536)
            + "!=="
            + json.dumps(screen)
            + ") throw Error('Owned shell input changed; preserve');"
            + "\nconst otherIds=app.windows().filter(w=>w.id()!==targetWindow.id()).map(w=>w.id());"
            + "\ntargetWindow.close(); delay(0.3);"
            + "\nconst remainingIds=app.windows().map(w=>w.id());"
            + "\nif(otherIds.some(id=>!remainingIds.includes(id))) "
            + "throw Error('Closing owned scripting window removed another window');"
            + "\nJSON.stringify({closed:true,other_window_ids_preserved:true,"
            + "remaining:remainingIds});"
        )
        item["close_receipt"] = await transport.native(source, mutation=True)
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- independent native absence confirmation
                try:
                    item["absence_after_close"] = await bridge.sessions.prove_original_target_gone(
                        "test", binding.model_dump()
                    )
                    break
                except BridgeError as error:
                    if error.code != "visible_absence_unproven":
                        raise
                    await asyncio.sleep(0.1)
        assert Path(item["receipt"]).read_bytes() == b""
        item["closed_and_independently_absent"] = True
        owned = None
        await unchanged_originals()
        check("owned window and both exact PIDs independently absent", pane_id=binding.pane_id)

    try:
        first = await fixture(1)
        config.visible_handoffs.bindings["head"] = first
        original_config = config.model_copy(deep=True)
        old_row = retain_unknown(first, "owned-old-1")
        try:
            await bridge.sessions.prove_original_target_gone("test", first.model_dump())
            raise AssertionError("A live original fixture was incorrectly reported absent")
        except BridgeError as error:
            assert error.code == "visible_absence_unproven"
        try:
            await bridge.visible_handoffs.reconcile_target_reservations("test", "head", first)
            raise AssertionError("A live unresolved fixture must stay reserved")
        except BridgeError as error:
            assert error.code == "visible_target_busy"
        check("live original native fixture stays locked; no input")
        previous = first
        for number in (2, 3):
            await close_owned()
            current = await fixture(number)
            same_tty = current.pane_id.split(":")[2] == previous.pane_id.split(":")[2]
            baseline = identities_disjoint(previous, current)
            if same_tty:
                assert baseline is False, "Baseline must reproduce its reused-TTY refusal"
            async with bridge.sessions.agent_selection("test", "head", current):
                await bridge.visible_handoffs.check_target("test", "head", current, ready=True)
                released = await bridge.visible_handoffs._foreign_dead_reservation(
                    "test", "head", old_row, current, await transport.catalog()
                )
                assert released, "A proven dead original must not reserve the new native instance"
            refreshed, _ = await bridge.visible_handoffs.refreshed_binding("test", "head", previous)
            assert refreshed == current
            await bridge.visible_handoffs.dispatch_ready("test", "head")
            evidence["cycles"].append(
                {
                    "old_pane": previous.pane_id,
                    "new_pane": current.pane_id,
                    "same_tty_observed": same_tty,
                    "baseline_strict_identity_gate": baseline,
                    "native_absence_backed_release": released,
                }
            )
            for identifier, expected in retained.items():
                assert history(identifier) == expected, "Original unknown record changed"
            check(
                "new native fixture ready after closed predecessor",
                number=number,
                same_tty=same_tty,
            )
            if number == 2:
                old_row = retain_unknown(current, "owned-old-2")
            previous = current
        evidence["same_tty_reproduced"] = any(
            cycle["same_tty_observed"] for cycle in evidence["cycles"]
        )
        assert evidence["same_tty_reproduced"], "OS did not reuse a TTY; no reproduction claim"
        restarted = Bridge(original_config)
        guard_input_routes(restarted)
        restored = restarted.config.visible_handoffs.bindings["head"]
        assert restored == previous, "Restart must restore the latest real successor"
        await restarted.visible_handoffs.dispatch_ready("test", "head")
        saved = json.loads(overlay_path(config).read_text())["head"]
        assert saved["replaced_pane_id"] == first.pane_id
        assert saved["pane_id"] == previous.pane_id
        for identifier, expected in retained.items():
            assert history(identifier) == expected
        evidence["unknown_history_sha256"] = retained
        check("restart restores third native fixture; unknown rows/messages/events unchanged")
        assert not evidence["forbidden_input_calls"]
        assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        evidence["acceptance"] = "checks_passed_cleanup_pending"
    except BaseException as error:
        failure = error
        evidence["acceptance"] = "failed"
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            await close_owned()
            inventory = await unchanged_originals()
            assert {row["window_id"] for row in inventory["windows"]} == initial_windows
            evidence["original_process_identities_preserved"] = True
            evidence["final_windows"] = sorted(initial_windows)
            evidence["cleanup_complete"] = True
            if failure is None:
                evidence["acceptance"] = "passed"
        except BaseException as error:
            evidence["acceptance"] = "failed"
            evidence["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
            if failure is None:
                failure = error
        if restarted is not None:
            restarted.store.close()
        bridge.store.close()
        checkpoint()
        print(
            json.dumps(
                {"acceptance": evidence["acceptance"], "evidence": str(root / "evidence.json")}
            )
        )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow-one-owned-visible-window", action="store_true", required=True)
    options = parser.parse_args()
    asyncio.run(
        accept(
            options.root.resolve(),
            allow_one_owned_visible_window=options.allow_one_owned_visible_window,
        )
    )
