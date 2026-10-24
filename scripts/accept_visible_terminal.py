"""Real Intel/arm macOS acceptance restricted to windows this test opens itself."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shlex
from pathlib import Path

from kirabridge.bridge_core.bridge import INPUTS, Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.discovery import live


async def accept(root):
    if platform.system() != "Darwin":
        raise RuntimeError("Actual macOS required")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir()
    config = Config(
        data_dir=str(root / "state"),
        concurrency=2,
        principals={
            "chatgpt": PrincipalConfig(
                capabilities=[
                    *INPUTS,
                    "session.inspect",
                    "bridge.health",
                    "task.read",
                    "task.cancel",
                    "agent.inspect",
                ],
                roots=[str(workspace)],
                terminal_roots=[str(workspace)],
                allow_any_executable=True,
                approval_mode="automatic",
                permission_level="full",
            )
        },
    )
    bridge = Bridge(config)
    transport = bridge.sessions.terminal_app
    original_catalog, original_open = transport.catalog, transport.open
    owned = set()
    evidence = {
        "platform": platform.platform(),
        "scope": "only freshly test-owned Terminal.app windows",
        "production_modified": False,
        "checks": [],
    }

    async def catalog():
        return [row for row in await original_catalog() if row["tty"] in owned]

    async def opened(command):
        result = await original_open(command)
        owned.add(result["tty"])
        return result

    # Filtering narrows the real observation, never fabricates a handle or idle proof.
    transport.catalog, transport.open = catalog, opened

    async def submit(identifier, argv, **extra):
        task = TaskRequest(
            task_id=identifier,
            idempotency_key=identifier,
            operation="terminal.visible",
            arguments={"cwd": str(workspace), "argv": argv, "timeout": 30, **extra},
        )
        bridge.prepare("chatgpt", task)
        return task

    async def finished(task):
        result = await bridge.tasks.wait("chatgpt", task.task_id, 40)
        if result["state"] != "completed":
            raise RuntimeError(
                json.dumps(
                    {
                        "id": result["id"],
                        "state": result["state"],
                        "error": result.get("error"),
                        "result": result.get("result"),
                    }
                )
            )
        return result["result"]

    original_execute = bridge.visible_terminal.execute

    async def traced_execute(*args, **kwargs):
        try:
            return await original_execute(*args, **kwargs)
        except Exception as exc:
            evidence["last_execution_error"] = {
                "code": getattr(exc, "code", "unknown"),
                "message": str(exc),
            }
            raise

    bridge.visible_terminal.execute = traced_execute
    try:
        async with bridge:
            first = await submit(
                "visible-first",
                [
                    "/bin/zsh",
                    "-f",
                    "-c",
                    "/usr/bin/tty > "
                    + shlex.quote(str(workspace / "tty-proof"))
                    + "; /usr/bin/printf VISIBLE_FIRST_OK",
                ],
            )
            result = await finished(first)
            assert (workspace / "tty-proof").read_text().strip() == result["tty"]
            evidence["checks"].append(
                "opens separate real visible window; command inherits its exact TTY"
            )
            first_handle = (result["pane_id"], result["expected_pid"])
            # Observe prompt redraw after the exit receipt before asserting reuse.
            async with asyncio.timeout(15):
                while True:  # noqa: ASYNC110 -- bounded real UI observation
                    current = await bridge.sessions.selected("chatgpt", *first_handle)
                    if await bridge.visible_terminal.suitable("chatgpt", current):
                        break
                    text = await transport.read(current["pane_id"])
                    evidence["last_owned_shell_probe"] = {
                        "busy": current["busy"],
                        "process_names": [p["name"] for p in current["processes"]],
                        "tail": repr(text[-180:]),
                        "controls": sorted({ord(c) for c in text if ord(c) < 32 and c != "\n"}),
                    }
                    await asyncio.sleep(0.1)
            second = await submit("visible-second", ["/usr/bin/printf", "VISIBLE_SECOND_OK"])
            again = await finished(second)
            assert (again["pane_id"], again["expected_pid"]) == first_handle
            evidence["checks"].append(
                "reuses confirmed existing idle shell; no stale saved binding"
            )
            before = (await live(bridge, "chatgpt"))["revision"]
            # A long, harmless command in our own window must remain uninterrupted.
            busy = await submit("visible-busy", ["/bin/sleep", "12"])
            async with asyncio.timeout(10):
                while not any(row["busy"] for row in await catalog()):  # noqa: ASYNC110 -- bounded real UI observation
                    await asyncio.sleep(0.05)
            concurrent = await submit(
                "visible-concurrent", ["/usr/bin/printf", "SEPARATE_WINDOW_OK"]
            )
            separate = await finished(concurrent)
            assert separate["pane_id"] != first_handle[0]
            assert len(owned) == 2
            evidence["checks"].append("busy running window preserved; separate visible window used")
            await finished(busy)
            after = (await live(bridge, "chatgpt"))["revision"]
            assert after != before
            evidence["checks"].append(
                "fresh discovery revision changes with actual visible sessions"
            )
            stale = await submit(
                "visible-stale",
                ["/usr/bin/printf", "MUST_NOT_RUN"],
                pane_id=first_handle[0],
                expected_pid=first_handle[1] + 100000,
            )
            rejected = await bridge.tasks.wait("chatgpt", stale.task_id, 10)
            assert rejected["state"] == "failed"
            evidence["checks"].append("stale PID rejected before input; no alternate fallback")
            evidence["version"] = bridge.runtime["version"]
            evidence["passed"] = True
    except Exception as exc:
        evidence["error"] = str(exc)
        raise
    finally:
        evidence["test_window_ttys"] = sorted(owned)
        for row in await catalog() if owned else []:
            try:
                await transport.native(
                    transport.native_target(row["pane_id"])
                    + "\nif(tab.busy()) throw Error('Test still busy; preserve');"
                    + "\nif(wins[0].tabs().length!==1) throw Error('Other tabs; preserve');"
                    + "\nwins[0].close(); JSON.stringify({closed:true});",
                    mutation=True,
                )
            except Exception:
                evidence.setdefault("cleanup_preserved", []).append(row["pane_id"])
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    opts = parser.parse_args()
    asyncio.run(accept(opts.root.resolve()))
