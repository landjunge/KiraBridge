"""OpenCode ACP adapter on the shared, reusable ACP client.

A fresh, isolated ``opencode acp`` process per task over stdio. The same bounded,
session-bound ACP client used by Grok is reused here; this adapter only supplies the
OpenCode command line, isolated profile and its own, stricter text-only policy.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import ExitStack

from kirabridge.agent_manager.acp import ACPClient
from kirabridge.agent_manager.opencode import _isolated_environment, _managed_configuration_present
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import reap_process, spawn_process

_MODEL = re.compile(r"[a-z0-9][a-z0-9_-]{0,100}/[A-Za-z0-9][A-Za-z0-9._:/-]{0,240}")


class OpenCodeACPAdapter:
    """ACP v1 text-only OpenCode turn; no local tools, no adopted interactive session."""

    interface_version = "1"

    def __init__(self, terminal):
        self.terminal = terminal

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "OpenCode executable must be configured explicitly")
        if not config.model or not _MODEL.fullmatch(config.model):
            raise BridgeError("agent_config", "OpenCode requires an explicit provider/model")
        if config.allow_local_tools and args.local_tools:
            raise BridgeError(
                "agent_capability", "OpenCode local tools require a separately verified sandbox"
            )
        if _managed_configuration_present():
            raise BridgeError(
                "agent_config",
                "Managed OpenCode configuration requires a separately verified profile",
            )

        session = None

        async def on_activity(kind):
            await running({"agent": args.agent, "session_id": session, "event": kind})

        async def on_request(method, params):
            # A text-only turn never grants permission; every request is refused.
            if method != "session/request_permission":
                return None
            return {"outcome": {"outcome": "cancelled"}}

        command = [config.executable, "acp"]
        with ExitStack() as stack:
            fd = stack.enter_context(PathScope(roots).directory(args.cwd))
            # The isolated XDG profile must stay on disk for the whole process
            # lifetime, so keep the context open until after reap_process().
            env, _workspace, _temporary_root = stack.enter_context(
                _isolated_environment(config, self.terminal)
            )
            process = await spawn_process(
                command,
                fd,
                env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1048576,
            )
            client = ACPClient(process)
            client.on_activity = on_activity
            client.on_request = on_request
            client.start()
            try:
                async with asyncio.timeout(args.timeout):
                    await progress(
                        {"agent": args.agent, "pid": process.pid, "event": "process_spawned"}
                    )
                    init = await client.request(
                        "initialize", {"protocolVersion": 1, "clientCapabilities": {}}, args.timeout
                    )
                    if init.get("protocolVersion") != 1:
                        raise BridgeError("agent_protocol", "Unsupported ACP version")
                    methods = {item["id"] for item in init.get("authMethods", [])}
                    if "cached_token" in methods:
                        await client.request(
                            "authenticate",
                            {"methodId": "cached_token", "_meta": {"headless": True}},
                            args.timeout,
                        )
                    new = await client.request(
                        "session/new", {"cwd": args.cwd, "mcpServers": []}, args.timeout
                    )
                    session = client.bind_session(new.get("sessionId"))
                    await progress(
                        {"agent": args.agent, "session_id": session, "event": "session_created"}
                    )
                    result = await client.request(
                        "session/prompt",
                        {"sessionId": session, "prompt": [{"type": "text", "text": args.prompt}]},
                        args.timeout,
                    )
                    stop = result.get("stopReason")
                    if not stop:
                        raise UncertainExecution(
                            "agent_unconfirmed", "OpenCode returned no stop reason"
                        )
                    if not client.started:
                        await running(
                            {
                                "agent": args.agent,
                                "session_id": session,
                                "event": "prompt_response_observed",
                            }
                        )
                    return {
                        "success": stop == "end_turn",
                        "text": client.text,
                        "final_message": client.text,
                        "evidence": {
                            "agent": args.agent,
                            "adapter": "opencode_acp",
                            "session_id": session,
                            "stop_reason": stop,
                            "local_tools_enabled": False,
                            "mcp_servers_enabled": False,
                            "output_truncated": client.truncated,
                        },
                        "scope": "agent_turn",
                        "project_completion_verified": False,
                    }
            except TimeoutError:
                await client.cancel()
                raise UncertainExecution(
                    "agent_interrupted", "OpenCode ACP execution cannot be confirmed"
                ) from None
            except (ValueError, OSError) as exc:
                raise UncertainExecution(
                    "agent_interrupted", "OpenCode ACP execution cannot be confirmed"
                ) from exc
            finally:
                await client.aclose()
                await reap_process(process)
