"""Synthetic console fixture process; no dispatcher, user config or adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from pathlib import Path

import uvicorn

import kirabridge.approval_console as console
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import State, TaskRequest

KEY = "synthetic-console-browser-key-" + "x" * 48


def fixture_tasks(bridge, workspace):
    def pending(identity, operation="file.list", args=None, principal="local"):
        value = TaskRequest(
            task_id=identity,
            idempotency_key=identity,
            operation=operation,
            arguments=args or {"path": str(workspace)},
        )
        bridge.prepare(principal, value)

    def observed(identity, state, *, agent=False):
        pending(
            identity,
            "agent.execute" if agent else "file.list",
            {
                "agent": "codex",
                "prompt": "Synthetic UI state only; never execute",
                "cwd": str(workspace),
            }
            if agent
            else None,
        )
        bridge.tasks.approve(identity)
        assert bridge.store.claim("synthetic-ui-fixture", 30)["id"] == identity
        if state is not State.ACCEPTED:
            bridge.store.transition(identity, State.RUNNING, {"synthetic_console_fixture": True})
        if state in {State.COMPLETED, State.UNKNOWN, State.FAILED}:
            bridge.store.transition(
                identity,
                state,
                {"synthetic_console_fixture": True},
                result={"turn_completed": True, "project_completion_verified": False}
                if agent
                else None,
                error={"code": "synthetic_failure"} if state is State.FAILED else None,
            )

    observed("completed-agent", State.COMPLETED, agent=True)
    observed("unknown-task", State.UNKNOWN)
    observed("accepted-task", State.ACCEPTED)
    observed("running-task", State.RUNNING)
    observed("failed-task", State.FAILED)
    for identity in ("pending-approve", "pending-deny", "pending-lost", "pending-stale"):
        pending(
            identity,
            "file.write",
            {
                "path": str(workspace / (identity + ".txt")),
                "text": '<img src=x onerror="window.__consoleInjected=1"> synthetic only',
            },
        )
    pending("automatic-queued", principal="chatgpt")


async def main(root):
    workspace = root / "workspace"
    workspace.mkdir()
    policy = PrincipalConfig(
        capabilities=["file.list", "file.write", "agent.execute", "task.read"],
        roots=[str(workspace)],
        agents=["codex"],
    )
    bridge = Bridge(
        Config(
            data_dir=str(root / "state"),
            principals={
                "local": policy,
                "chatgpt": policy.model_copy(update={"approval_mode": "automatic"}),
            },
        )
    )
    fixture_tasks(bridge, workspace)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    console.PORT, console.ORIGIN = port, url
    app = console.ApprovalConsole(bridge, KEY)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        path = root / "fixture.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(
                {
                    "url": url,
                    "ticket": console.signed_token(KEY, "login:" + app.instance),
                    "dispatcher_started": False,
                },
                stream,
            )
        await serving
    finally:
        server.should_exit = True
        await serving
        bridge.store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    asyncio.run(main(parser.parse_args().root))
