from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Protocol

import httpx

from kirabridge.bridge_core.config import AgentConfig, Config
from kirabridge.bridge_core.models import AgentInput, BridgeError, TerminalInput, UncertainExecution
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import reap_process, spawn_process
from kirabridge.terminal_manager import EvidenceCallback, TerminalManager, minimal_environment


async def bounded_lines(response, limit=1048576):
    pending = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=8192):
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, remainder = pending.partition(b"\n")
            if len(line) > limit:
                raise UncertainExecution("provider_protocol", "Provider event exceeds byte limit")
            pending = bytearray(remainder)
            yield line.decode("utf-8")
        if len(pending) > limit:
            raise UncertainExecution("provider_protocol", "Provider event exceeds byte limit")
    if pending:
        yield pending.decode("utf-8")


class AgentAdapter(Protocol):
    interface_version: str

    async def execute(
        self,
        task: dict,
        args: AgentInput,
        config: AgentConfig,
        roots: list[str],
        running: EvidenceCallback,
        progress: EvidenceCallback,
    ) -> dict: ...


def agent_environment(config: AgentConfig) -> dict:
    env = minimal_environment()
    env["HOME"] = str(Path.home())
    for key in (config.api_key_env, "CODEX_API_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class CodexAdapter:
    interface_version = "1"

    def __init__(self, terminal: TerminalManager):
        self.terminal = terminal

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Codex executable must be configured explicitly")
        session, completed, failed, started = None, False, False, False
        messages: list[str] = []
        message_bytes = 0

        async def event(line: str):
            nonlocal session, completed, failed, started, message_bytes
            try:
                value = json.loads(line)
            except ValueError:
                return
            kind = value.get("type")
            if kind == "thread.started" and isinstance(value.get("thread_id"), str):
                if session and session != value["thread_id"]:
                    raise UncertainExecution("agent_identity", "Codex changed session identity")
                session = value["thread_id"]
                await progress({"agent": args.agent, "session_id": session, "event": kind})
            elif kind == "turn.started" and session and not started:
                started = True
                await running({"agent": args.agent, "session_id": session, "event": kind})
            elif kind == "turn.completed" and session and started:
                completed = True
            elif kind == "turn.failed":
                failed = True
            elif kind == "item.completed":
                item = value.get("item", {})
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    data = item["text"].encode()[: max(0, 65536 - message_bytes)]
                    message_bytes += len(data)
                    if data:
                        messages.append(data.decode("utf-8", "replace"))

        command = [
            config.executable,
            "exec",
            "--ignore-user-config",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            config.sandbox_mode,
            "-c",
            'approval_policy="never"',
            "-c",
            "mcp_servers={}",
            "-c",
            "features.multi_agent=false",
        ]
        if config.model:
            command += ["--model", config.model]
        command += ["-"]

        async def spawned(evidence):
            await progress({"agent": args.agent, **evidence})

        result = await self.terminal.execute(
            task["id"],
            task["principal"],
            TerminalInput(argv=command, cwd=args.cwd, timeout=args.timeout),
            roots,
            [config.executable],
            spawned,
            env=agent_environment(config),
            stdin=args.prompt.encode(),
            line_callback=event,
        )
        evidence = {
            "agent": args.agent,
            "adapter": "codex",
            "sandbox_mode": config.sandbox_mode,
            "project_rules_enabled": True,
            "mcp_servers_enabled": False,
            "session_id": session,
            "exit_code": result["exit_code"],
            "turn_completed": completed,
            "turn_failed": failed,
            "timed_out": result["timed_out"],
        }
        if not completed and not failed:
            raise UncertainExecution("agent_unconfirmed", "No Codex turn completion evidence")
        if not started:
            await running({**evidence, "event": "terminal_response_observed"})
        return {
            "evidence": evidence,
            "text": "\n".join(messages),
            "success": completed and not failed and result["exit_code"] == 0,
            "scope": "agent_turn",
            "project_completion_verified": False,
        }


class GrokAPIAdapter:
    """One text-only model turn. No local tools and no implicit provider retries."""

    interface_version = "1"

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        key = os.environ.get(config.api_key_env)
        if not key or not config.model:
            raise BridgeError("agent_config", "Grok API requires a model and API-key environment")
        text, response_id, finish, started = bytearray(), None, None, False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(args.timeout), trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": config.model,
                        "messages": [{"role": "user", "content": args.prompt}],
                        "stream": True,
                    },
                ) as response:
                    if response.status_code != 200:
                        if response.status_code >= 500 or response.status_code == 408:
                            raise UncertainExecution(
                                "provider_unknown", "Provider outcome is unknown"
                            )
                        raise BridgeError("provider_rejected", "Grok API rejected the request")
                    async for line in bounded_lines(response):
                        if line == "data: [DONE]":
                            break
                        if not line.startswith("data: "):
                            continue
                        if len(line) > 1048576:
                            raise UncertainExecution("provider_protocol", "Grok event too large")
                        event = json.loads(line[6:])
                        event_id = event.get("id")
                        if response_id and event_id != response_id:
                            raise UncertainExecution(
                                "agent_identity", "Grok response identity changed"
                            )
                        response_id = event_id
                        if not isinstance(response_id, str):
                            continue
                        if not started:
                            started = True
                            await running(
                                {
                                    "agent": args.agent,
                                    "response_id": response_id,
                                    "event": "model_response_chunk",
                                }
                            )
                        for choice in event.get("choices", []):
                            content = choice.get("delta", {}).get("content") or ""
                            text.extend(content.encode()[: max(0, 65536 - len(text))])
                            finish = choice.get("finish_reason") or finish
        except (httpx.HTTPError, ValueError) as exc:
            raise UncertainExecution(
                "provider_disconnected", "Grok response cannot be confirmed"
            ) from exc
        if not started or not finish:
            raise UncertainExecution("provider_unconfirmed", "No Grok completion evidence")
        return {
            "success": finish == "stop",
            "text": text.decode("utf-8", "replace"),
            "evidence": {
                "agent": args.agent,
                "adapter": "grok_api",
                "response_id": response_id,
                "finish_reason": finish,
            },
            "scope": "model_turn",
            "project_completion_verified": False,
        }


class GrokACPAdapter:
    """ACP v1: no fs/terminal client capabilities, deny every permission request."""

    interface_version = "1"

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Grok executable must be configured explicitly")
        command = [
            config.executable,
            "--no-subagents",
            "--disable-web-search",
            "--permission-mode",
            "dontAsk",
            "--deny",
            "Bash",
            "--deny",
            "Edit",
            "--deny",
            "MCPTool",
            "--deny",
            "WebFetch",
            "--deny",
            "WebSearch",
            "agent",
            "--no-leader",
            "stdio",
        ]
        if config.model:
            command[1:1] = ["--model", config.model]
        with PathScope(roots).directory(args.cwd) as fd:
            process = await spawn_process(
                command,
                fd,
                env=agent_environment(config),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1048576,
            )
        session, started, text, counter = None, False, bytearray(), 0

        async def send(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()

        async def request(method, params):
            nonlocal counter, started
            counter += 1
            identifier = counter
            await send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
            while line := await process.stdout.readline():
                value = json.loads(line)
                if value.get("method") == "session/update":
                    params = value.get("params", {})
                    if not session or params.get("sessionId") != session:
                        raise UncertainExecution("agent_identity", "Unexpected Grok session update")
                    update = params.get("update", {})
                    kind = update.get("sessionUpdate")
                    if kind in {"agent_message_chunk", "tool_call", "agent_thought_chunk"}:
                        if not started:
                            started = True
                            await running(
                                {"agent": args.agent, "session_id": session, "event": kind}
                            )
                        content = update.get("content", {})
                        if kind == "agent_message_chunk" and content.get("type") == "text":
                            text.extend(
                                content.get("text", "").encode()[: max(0, 65536 - len(text))]
                            )
                elif "method" in value and "id" in value:
                    if value["method"] == "session/request_permission":
                        await send(
                            {
                                "jsonrpc": "2.0",
                                "id": value["id"],
                                "result": {"outcome": {"outcome": "cancelled"}},
                            }
                        )
                    else:
                        await send(
                            {
                                "jsonrpc": "2.0",
                                "id": value["id"],
                                "error": {"code": -32601, "message": "Capability not available"},
                            }
                        )
                elif value.get("id") == identifier:
                    if "error" in value:
                        raise UncertainExecution("agent_rpc", "Grok ACP returned an error")
                    return value.get("result", {})
            raise UncertainExecution("agent_disconnected", "Grok ACP disconnected")

        try:
            async with asyncio.timeout(args.timeout):
                await progress(
                    {"agent": args.agent, "pid": process.pid, "event": "process_spawned"}
                )
                init = await request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
                if init.get("protocolVersion") != 1:
                    raise BridgeError("agent_protocol", "Unsupported ACP version")
                methods = {item["id"] for item in init.get("authMethods", [])}
                method = "xai.api_key" if os.environ.get(config.api_key_env) else "cached_token"
                if method not in methods:
                    raise BridgeError("agent_auth", "No supported Grok authentication available")
                await request("authenticate", {"methodId": method, "_meta": {"headless": True}})
                new = await request("session/new", {"cwd": args.cwd, "mcpServers": []})
                session = new.get("sessionId")
                if not isinstance(session, str) or not session:
                    raise BridgeError("agent_protocol", "No Grok session identity")
                await progress(
                    {"agent": args.agent, "session_id": session, "event": "session_created"}
                )
                result = await request(
                    "session/prompt",
                    {"sessionId": session, "prompt": [{"type": "text", "text": args.prompt}]},
                )
                stop = result.get("stopReason")
                if not stop:
                    raise UncertainExecution("agent_unconfirmed", "Grok returned no stop reason")
                if not started:
                    await running(
                        {
                            "agent": args.agent,
                            "session_id": session,
                            "event": "prompt_response_observed",
                        }
                    )
                return {
                    "success": stop == "end_turn",
                    "text": text.decode("utf-8", "replace"),
                    "evidence": {
                        "agent": args.agent,
                        "adapter": "grok_acp",
                        "session_id": session,
                        "stop_reason": stop,
                    },
                    "scope": "agent_turn",
                    "project_completion_verified": False,
                }
        except (TimeoutError, ValueError, OSError) as exc:
            raise UncertainExecution(
                "agent_interrupted", "Grok execution cannot be confirmed"
            ) from exc
        finally:
            await reap_process(process)


class AgentManager:
    def __init__(self, config: Config, terminal: TerminalManager):
        self.config = config
        self.adapters: dict[str, AgentAdapter] = {
            "codex": CodexAdapter(terminal),
            "grok_api": GrokAPIAdapter(),
            "grok_acp": GrokACPAdapter(),
        }

    def register(self, kind: str, adapter: AgentAdapter) -> None:
        if kind in self.adapters or adapter.interface_version != "1":
            raise BridgeError(
                "adapter_version", "Duplicate adapter or unsupported interface version"
            )
        self.adapters[kind] = adapter

    def inventory(self, allowed: list[str]) -> dict:
        return {
            "agents": [
                {
                    "id": name,
                    "kind": config.kind,
                    **(
                        {
                            "sandbox_mode": config.sandbox_mode,
                            "project_rules_enabled": True,
                            "mcp_servers_enabled": False,
                        }
                        if config.kind == "codex"
                        else {}
                    ),
                    "executable_present": bool(
                        config.executable and Path(config.executable).is_file()
                    ),
                    "daemon_status": "unknown",
                    "session_status": "unknown",
                    "task_status": "unknown",
                }
                for name, config in self.config.agents.items()
                if name in allowed
            ]
        }

    async def execute(self, task, args, principal, running, progress):
        if args.agent not in principal.agents:
            raise BridgeError("agent_denied", "Agent identity not granted")
        config = self.config.agents.get(args.agent)
        if config is None or config.kind not in self.adapters:
            raise BridgeError("agent_unavailable", "Agent adapter is not configured")
        try:
            async with asyncio.timeout(args.timeout):
                return await self.adapters[config.kind].execute(
                    task,
                    args,
                    config,
                    principal.roots,
                    running,
                    progress,
                )
        except TimeoutError:
            raise UncertainExecution(
                "agent_timeout", "Agent completion could not be confirmed"
            ) from None
