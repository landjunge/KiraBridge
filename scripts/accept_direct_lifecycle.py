"""Explicit native macOS lifecycle acceptance; one owned test window, no CLI-agent input."""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
import time
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.private_files import private_json, write_private
from kirabridge.session_manager import SessionOpen


async def accept(root):
    if sys.platform != "darwin":
        raise SystemExit("Actual macOS required")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    policy = PrincipalConfig(
        permission_level="full",
        approval_mode="automatic",
        capabilities=[
            "terminal.execute",
            "session.inspect",
            "session.input",
            "session.open",
            "bridge.health",
            "task.read",
        ],
        roots=[str(root)],
        executables=["/usr/bin/printf", "/bin/zsh"],
    )
    config = Config(data_dir=str(root / "state"), principals={"acceptance": policy})
    receipt_path, nonce = root / "owned-receipt.json", "native-lifecycle-only"
    evidence = {
        "scope": "one explicitly owned native fixture; no Codex/Git input or interruption",
        "production_daemon_modified": False,
        "created_windows": 0,
    }
    first = Bridge(config)
    async with first:
        initial = await first.sessions.catalog("acceptance")
        initial_panes = {row["pane_id"] for row in initial["sessions"]}
        original_execute = first.tasks.executor

        async def create_fixture(task, running, progress):
            if task["operation"] != "session.open":
                return await original_execute(task, running, progress)
            # This acceptance-only factory must create ONE owned resource to prove
            # native cleanup. Production SessionManager.open always prefers reuse.
            args = SessionOpen.model_validate(task["args"])
            first.security.validate_window("acceptance", task["id"], args)
            first.security.check_window("acceptance", task["id"], args)
            await running({"scope": "explicit_native_owned_fixture"})
            opened = await first.sessions.terminal_app.open(
                "cd -- "
                + shlex.quote(str(root))
                + " && exec /usr/bin/env PS1='KiraBridge visible %% ' /bin/zsh -f"
            )
            evidence["created_windows"] += 1
            first.security.window_outcome("acceptance", task["id"], "opened")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                rows = (await first.sessions.catalog("acceptance"))["sessions"]
                matches = [r for r in rows if r["tty"] == opened["tty"]]
                if len(matches) == 1 and await first.visible_terminal.suitable(
                    "acceptance", matches[0]
                ):
                    row = matches[0]
                    await first.owned_windows.register("acceptance", task["id"], row)
                    first.owned_windows.command(row["pane_id"], task["id"], receipt_path, nonce)
                    return {
                        "success": True,
                        "pane_id": row["pane_id"],
                        "expected_pid": row["expected_pid"],
                        "tty": row["tty"],
                    }
                await asyncio.sleep(0.1)
            raise AssertionError("Native fixture startup unconfirmed; do not open a replacement")

        first.tasks.executor = create_fixture
        value = TaskRequest(
            task_id="owned-native-fixture",
            idempotency_key="owned-native-fixture",
            operation="session.open",
            arguments={"cwd": str(root), "controlled_shell": True},
        )
        first.prepare("acceptance", value)
        result = await first.tasks.wait("acceptance", value.task_id, 20)
        assert result["state"] == "completed", result.get("error")
        owned = result["result"]
        assert owned["pane_id"] not in initial_panes
        evidence["owned_pane"] = owned["pane_id"]
    # A new core/connection reads durable ownership after the prior runtime closed.
    second = Bridge(config)
    async with second:
        await second.owned_windows.cleanup()
        row = await second.sessions.selected("acceptance", owned["pane_id"], owned["expected_pid"])
        evidence["ownership_survived_restart"] = True
        identity = await second.sessions.terminal_app.process_identity(row["expected_pid"])
        command = "umask 077; /usr/bin/printf '%s\\n' " + shlex.quote(
            json.dumps({"nonce": nonce, "exit_code": 0})
        )
        command += " > " + shlex.quote(str(receipt_path))
        await second.sessions.terminal_app.send_confirmed(row, command, identity)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            await second.owned_windows.cleanup()
            state = second.store.db.execute(
                "SELECT state FROM owned_terminal_windows WHERE pane_id=?", (row["pane_id"],)
            ).fetchone()[0]
            if state == "closed":
                break
            await asyncio.sleep(0.2)
        assert state == "closed", "Owned fixture not closed; preserve it for reconciliation"
        assert private_json(receipt_path) == {"nonce": nonce, "exit_code": 0}
        after = {r["pane_id"] for r in (await second.sessions.catalog("acceptance"))["sessions"]}
        assert row["pane_id"] not in after and initial_panes.issubset(after)
        evidence["native_owned_close_confirmed"] = True
        # Exact repeated commands must reuse a free existing shell, never create
        # another test window. A missing shell is an explicit test blocker.
        reused = []
        for index in range(2):
            request = TaskRequest(
                task_id=f"native-reuse-{index}",
                idempotency_key=f"native-reuse-{index}",
                operation="terminal.visible",
                arguments={
                    "argv": ["/usr/bin/printf", "KiraBridge reuse proof\\n"],
                    "cwd": str(root),
                    "timeout": 10,
                    "create_if_needed": False,
                },
            )
            second.prepare("acceptance", request)
            result = await second.tasks.wait("acceptance", request.task_id, 20)
            assert result["state"] == "completed", result.get("error")
            reused.append(result["result"]["pane_id"])
        assert reused[0] == reused[1]
        evidence["repeated_existing_shell"] = reused
    write_private(root / "evidence.json", json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--native-owned-window", action="store_true", required=True)
    args = parser.parse_args()
    asyncio.run(accept(args.root))
