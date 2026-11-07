"""Real native guards in one test-owned Terminal window; not Codex/Grok product acceptance."""

import argparse
import asyncio
import hashlib
import json
import platform
import shlex
import subprocess
import uuid
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    VisibleTerminalBinding,
)
from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionInput


async def accept(root):
    assert platform.system() == "Darwin", "Actual macOS required"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    config = Config(
        data_dir=str(root / "state"),
        agents={"head": AgentConfig(kind="grok_acp")},
        principals={
            "test": PrincipalConfig(
                capabilities=["session.inspect", "session.input", "terminal.execute", "task.read"],
                roots=[str(workspace)],
                approval_mode="automatic",
            )
        },
    )
    bridge = Bridge(config)
    transport = bridge.sessions.terminal_app
    observed = await transport.catalog()
    previous_ttys = {r["tty"] for r in observed}
    evidence = {
        "platform": platform.platform(),
        "scope": "one new owned interactive head fixture, not Codex/Grok acceptance",
        "production_modified": False,
        "checks": [],
    }
    tty, row = None, None
    payload = "KB-OWNED-" + uuid.uuid4().hex
    output = workspace / "received.txt"
    command = (
        "cd "
        + shlex.quote(str(workspace))
        + " && /usr/bin/printf 'KB-OWNED-READY\\n' && /usr/bin/head -n 1 > "
        + shlex.quote(str(output))
        + " && /usr/bin/printf '\\nKB-OWNED-DONE\\n'"
    )
    try:
        opened = await transport.open(command)
        tty = opened["tty"]
        assert tty not in previous_ttys, "Never use an existing user window"
        async with asyncio.timeout(15):
            while True:
                row = next((r for r in await transport.catalog() if r["tty"] == tty), None)
                if row and any(p["name"] == "head" for p in row["processes"]):
                    break
                await asyncio.sleep(0.1)
        agent = next(p for p in row["processes"] if p["name"] == "head")
        binding = VisibleTerminalBinding(
            pane_id=row["pane_id"],
            expected_pid=row["expected_pid"],
            agent_pid=agent["pid"],
            ready_pattern="KB-OWNED-READY",
            busy_pattern="",
        )
        config.visible_handoffs.bindings["head"] = binding
        async with bridge.sessions.agent_selection("test", "head", binding):
            identities = bridge.sessions.selected_identities(row)
            snapshot = await transport.read(row["pane_id"])
            stat = output.stat()
            descriptor = await asyncio.to_thread(
                subprocess.check_output,
                [
                    "/usr/sbin/lsof",
                    "-n",
                    "-a",
                    "-p",
                    str(agent["pid"]),
                    "-d",
                    "1",
                    "-Fpin",
                    "--",
                    str(output),
                ],
                text=True,
            )
            assert f"p{agent['pid']}\n" in descriptor
            assert f"i{stat.st_ino}\n" in descriptor and "n" + str(output) + "\n" in descriptor
            evidence["fixture_binding"] = {
                "window_id": row["window_id"],
                "tty": tty,
                "shell_pid": row["expected_pid"],
                "agent_pid": agent["pid"],
                "identities": identities,
                "output_inode": stat.st_ino,
                "output_device": stat.st_dev,
                "private_output_fd_verified": True,
            }
            (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            stale = {pid: value + " stale" for pid, value in identities.items()}
            try:
                await transport.insert(
                    row["pane_id"], "MUST_NOT_PASTE", identity_guard=stale, expected_screen=snapshot
                )
                raise AssertionError("Stale identity accepted")
            except BridgeError as exc:
                assert exc.code == "visible_target_changed", exc.code
            assert output.read_bytes() == b""
            evidence["checks"].append("stale process generation rejected before native paste")
            try:
                await transport.press_return(
                    row["pane_id"], identity_guard=identities, expected_screen=snapshot + "changed"
                )
                raise AssertionError("Changed widget accepted")
            except BridgeError as exc:
                assert exc.code == "visible_input_changed", exc.code
            assert output.read_bytes() == b""
            evidence["checks"].append("changed widget rejected before native Return")
            await bridge.sessions.insert(
                "test",
                SessionInput(
                    pane_id=row["pane_id"],
                    expected_pid=row["expected_pid"],
                    text=payload,
                    submit=False,
                ),
            )
            inserted = await transport.read(row["pane_id"])
            assert payload in inserted
            await bridge.sessions.press_return(
                "test", row["pane_id"], row["expected_pid"], expected_screen=inserted
            )
        async with asyncio.timeout(10):
            while output.read_bytes() != (payload + "\n").encode():  # noqa: ASYNC110 -- bounded owned file receipt
                await asyncio.sleep(0.05)
        evidence["checks"].append(
            "confirmed native Paste/Return reaches exact owned TTY; bytes match"
        )
        evidence["payload_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        evidence["tty"] = tty
        evidence["passed"] = True
    except Exception as exc:
        evidence["error"] = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "message": str(exc),
        }
        raise
    finally:
        if tty is not None and tty not in previous_ttys:
            try:
                current = next((r for r in await transport.catalog() if r["tty"] == tty), None)
                if current:
                    await transport.native(
                        transport.native_target(current["pane_id"])
                        + "\nif(tab.busy()) throw Error('Owned fixture remains busy; preserve');"
                        "\nif(wins[0].tabs().length!==1) throw Error('Other tabs; preserve');"
                        "\nwins[0].close(); JSON.stringify({closed:true});",
                        mutation=True,
                    )
            except Exception:
                evidence["cleanup_preserved"] = True
        bridge.store.close()
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    asyncio.run(accept(parser.parse_args().root.resolve()))
