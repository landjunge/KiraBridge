"""Private R3 Core child; invoked only by test_remote_os_restart.py."""

import asyncio
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

import uvicorn

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import digest
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.remote_handoff_peer import HttpHandoffPeer


async def main():
    settings = json.loads(Path(sys.argv[1]).read_text())
    config = Config.model_validate(settings["config"])
    assert settings["fixture_profile"] == "r2-owned-python-agent"
    assert Path(config.agents["codex"].executable).resolve() == (
        Path(sys.argv[1]).resolve().parent / "owned-codex"
    )
    # Reconstruct precisely conftest's R2 in-memory fixture. False is deliberately
    # NOT accepted by the product configuration parser. This child is no evidence
    # of a deployable managed-agent profile or a visible-terminal fallback.
    config.visible_handoffs.enabled = False
    trace = Path(settings["trace"])
    # The inherited listening socket was bound to loopback by our test parent.
    sock = socket.socket(fileno=int(sys.argv[2]))
    assert sock.getsockname()[0] == "127.0.0.1"
    generation = None

    def record(event, **fields):
        with trace.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": event,
                        "pid": os.getpid(),
                        "generation": generation,
                        "at": time.time(),
                        **fields,
                    }
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    async with HttpHandoffPeer(**settings["source"]) as source:
        async with Bridge(config, handoff_peer=source) as bridge:
            generation = bridge.runtime["instance_id"]
            original = bridge.submit

            def counted_submit(principal, request, approval, **kwargs):
                record(
                    "task_submit",
                    task_id=request.task_id,
                    request_sha256=digest(request.model_dump()),
                )
                return original(principal, request, approval, **kwargs)

            bridge.submit = counted_submit
            server = uvicorn.Server(
                uvicorn.Config(
                    create_http_app(bridge),
                    log_level="critical",
                    access_log=False,
                    ssl_certfile=config.tls_cert,
                    ssl_keyfile=config.tls_key,
                )
            )
            # Uvicorn restores/re-emits SIGTERM after its graceful HTTP shutdown.
            # The embedding test app must then finish its Bridge context cleanup.
            signal.signal(signal.SIGTERM, lambda *_: None)
            serving = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                            raise RuntimeError("Owned Core exited before readiness")
                        await asyncio.sleep(0.01)
                record(
                    "ready",
                    runtime_pid=bridge.runtime["pid"],
                    source_package_path=bridge.runtime["source_package_path"],
                    source_tree_sha256=bridge.runtime["source_tree_sha256"],
                    fixture_profile=settings["fixture_profile"],
                )
                await serving
                record("http_stopped")
            finally:
                server.should_exit = True
                await asyncio.wait_for(serving, 10)
                sock.close()
    record("core_closed")


if __name__ == "__main__":
    asyncio.run(main())
