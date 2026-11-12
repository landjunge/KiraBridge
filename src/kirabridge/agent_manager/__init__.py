from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Protocol

import httpx

from kirabridge.agent_manager.acp import ACPClient
from kirabridge.agent_manager.claude import ClaudeCodeAdapter
from kirabridge.agent_manager.cli_support import login_identity
from kirabridge.agent_manager.copilot import CopilotCLIAdapter
from kirabridge.agent_manager.gemini import GeminiAdapter
from kirabridge.agent_manager.grok_structured import GrokStructuredAdapter
from kirabridge.agent_manager.opencode import OpenCodeAdapter
from kirabridge.agent_manager.opencode_acp import OpenCodeACPAdapter
from kirabridge.agent_manager.opencode_http import OpenCodeHTTPAdapter
from kirabridge.agent_manager.opencode_http_v2 import OpenCodeHTTPV2Adapter
from kirabridge.agent_manager.qwen_acp import QwenACPAdapter
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


def agent_environment(config: AgentConfig, terminal: TerminalManager | None = None) -> dict:
    env = terminal.environment.copy() if terminal else minimal_environment()
    env["HOME"] = str(Path.home())
    env.update(login_identity())
    for key in (config.api_key_env, "CODEX_API_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class CodexAdapter:
    interface_version = "1"

    def __init__(self, terminal: TerminalManager, bridge_config=None):
        self.terminal = terminal
        self.bridge_config = bridge_config

    async def execute(
        self,
        task,
        args,
        config,
        roots,
        running,
        progress,
        *,
        owned_resume_session=None,
        handoff_reply=False,
        before_spawn=None,
    ) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Codex executable must be configured explicitly")
        if owned_resume_session is not None:
            try:
                if str(uuid.UUID(owned_resume_session)) != owned_resume_session:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise BridgeError(
                    "agent_identity", "An exact owned session UUID is required"
                ) from None
        session, completed, failed, started = owned_resume_session, False, False, False
        messages: list[str] = []
        message_bytes = 0
        provider_error = None

        async def event(line: str):
            nonlocal session, completed, failed, started, message_bytes, provider_error
            try:
                value = json.loads(line)
            except ValueError:
                return
            kind = value.get("type")
            if kind in {"error", "turn.failed"}:
                error = value.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                categories = {
                    "insufficient_quota": "quota_exhausted",
                    "quota_exceeded": "quota_exhausted",
                    "rate_limit_exceeded": "rate_limit",
                    "invalid_api_key": "authentication",
                    "authentication_error": "authentication",
                }
                if isinstance(code, str) and code in categories:
                    from kirabridge.bridge_core.models import digest

                    provider_error = {
                        "provider": "codex",
                        "code": code,
                        "category": categories[code],
                        "source": "codex_jsonl",
                        "event": kind,
                        "event_sha256": digest(value),
                    }
                    await progress(
                        {
                            "agent": args.agent,
                            "session_id": session,
                            "event": "provider_error_observed",
                            "provider_error": provider_error,
                        }
                    )
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
        bridge_enabled = bool(config.bridge_tools and self.bridge_config)
        if bridge_enabled:
            from kirabridge.agent_manager.full_access import bridge_server

            spec = bridge_server(self.bridge_config._source_path, args.agent)
            position = command.index("mcp_servers={}")
            command[position] = "mcp_servers.kirabridge.command=" + json.dumps(spec["command"])
            command += ["-c", "mcp_servers.kirabridge.args=" + json.dumps(spec["args"])]
        if owned_resume_session is not None:
            command += ["resume", "--json", "--ignore-user-config", "--skip-git-repo-check"]
        if handoff_reply:
            command += [
                "--output-schema",
                str(Path(__file__).with_name("handoff_reply.schema.json")),
            ]
        if config.model:
            command += ["--model", config.model]
        if config.output_schema:
            schema = Path(config.output_schema)
            if not schema.is_absolute() or not schema.is_file():
                raise BridgeError("agent_schema", "Explicit output schema is unavailable")
            command += ["--output-schema", str(schema)]
        if owned_resume_session is not None:
            command += [owned_resume_session]
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
            env=agent_environment(config, self.terminal),
            stdin=args.prompt.encode(),
            line_callback=event,
            **({"before_spawn": before_spawn} if before_spawn is not None else {}),
        )
        evidence = {
            "agent": args.agent,
            "adapter": "codex",
            "sandbox_mode": config.sandbox_mode,
            "pid": result["pid"],
            "project_rules_enabled": True,
            "mcp_servers_enabled": bridge_enabled,
            "session_id": session,
            "exit_code": result["exit_code"],
            "turn_completed": completed,
            "turn_failed": failed,
            "timed_out": result["timed_out"],
            "terminated": result["terminated"],
            "provider_error": provider_error,
        }
        if not completed and not failed:
            await progress(evidence)
            raise UncertainExecution("agent_unconfirmed", "No Codex turn completion evidence")
        if not started:
            await running({**evidence, "event": "terminal_response_observed"})
        return {
            "evidence": evidence,
            "text": "\n".join(messages),
            "final_message": messages[-1] if messages else "",
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
                        uncertain = response.status_code >= 500 or response.status_code == 408
                        exc = (
                            UncertainExecution("provider_unknown", "Provider outcome is unknown")
                            if uncertain
                            else BridgeError("provider_rejected", "Grok API rejected the request")
                        )
                        exc.provider_error = {
                            "provider": "xai",
                            "source": "provider_http_status",
                            "http_status": response.status_code,
                            "category": {
                                401: "authentication",
                                403: "authentication",
                                429: "rate_limit",
                            }.get(response.status_code, "provider"),
                        }
                        # HTTP 429 is rate limiting, not evidence of exhausted quota.
                        raise exc
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
    """ACP v1: text by default; local tools require config, principal and task opt-in."""

    interface_version = "1"

    def __init__(self, terminal: TerminalManager | None = None, bridge_config=None):
        self.terminal = terminal
        self.bridge_config = bridge_config

    async def execute(
        self,
        task,
        args,
        config,
        roots,
        running,
        progress,
        *,
        before_spawn=None,
        resume_session=None,
    ) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Grok executable must be configured explicitly")
        local_tools = config.allow_local_tools and args.local_tools
        bridge_enabled = bool(config.bridge_tools and self.bridge_config)
        command = [
            config.executable,
            "--no-subagents",
            "--disable-web-search",
            "--permission-mode",
            "dontAsk",
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
        if bridge_enabled:
            command = [
                config.executable,
                "--permission-mode",
                "bypassPermissions",
                "agent",
                "--no-leader",
                "stdio",
            ]
        # No arbitrary MCP attachment, even for a development task. Receivers never
        # opt in through message text; their AgentInput keeps local_tools=False.
        if local_tools:
            command[1:1] = ["--allow", "Bash", "--allow", "Edit", "--allow", "Read"]
        else:
            command[1:1] = ["--deny", "Bash", "--deny", "Edit"]
        if config.model:
            command[1:1] = ["--model", config.model]
        with PathScope(roots).directory(args.cwd) as fd:
            if before_spawn is not None:
                before_spawn()
            process = await spawn_process(
                command,
                fd,
                env=agent_environment(config, self.terminal),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1048576,
            )
        session = None

        async def on_activity(kind):
            await running({"agent": args.agent, "session_id": session, "event": kind})

        async def on_request(method, params):
            if method != "session/request_permission":
                return None
            bound_permission = (
                bool(session)
                and params.get("sessionId") == session
                and params.get("toolCall", {}).get("kind")
                in {"read", "edit", "delete", "move", "search", "execute"}
            )
            selected = next(
                (
                    option.get("optionId")
                    for option in params.get("options", [])
                    if isinstance(option, dict)
                    and option.get("kind") == "allow_once"
                    and isinstance(option.get("optionId"), str)
                ),
                None,
            )
            return {
                "outcome": {
                    "outcome": "selected",
                    "optionId": selected,
                }
                if local_tools and bound_permission and selected
                else {"outcome": "cancelled"}
            }

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
                method = "xai.api_key" if os.environ.get(config.api_key_env) else "cached_token"
                if method not in methods:
                    raise BridgeError("agent_auth", "No supported Grok authentication available")
                await client.request(
                    "authenticate", {"methodId": method, "_meta": {"headless": True}}, args.timeout
                )
                servers = []
                if bridge_enabled:
                    from kirabridge.agent_manager.full_access import bridge_server

                    spec = bridge_server(self.bridge_config._source_path, args.agent)
                    servers = [{"name": "kirabridge", **spec, "env": []}]
                if resume_session is not None:
                    session = client.bind_session(resume_session)
                    await client.request(
                        "session/load",
                        {"sessionId": session, "cwd": args.cwd, "mcpServers": servers},
                        args.timeout,
                    )
                    client.reset_text()
                    await progress(
                        {"agent": args.agent, "session_id": session, "event": "session_resumed"}
                    )
                else:
                    new = await client.request(
                        "session/new", {"cwd": args.cwd, "mcpServers": servers}, args.timeout
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
                    raise UncertainExecution("agent_unconfirmed", "Grok returned no stop reason")
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
                    "evidence": {
                        "agent": args.agent,
                        "adapter": "grok_acp",
                        "session_id": session,
                        "session_resumed": resume_session is not None,
                        "stop_reason": stop,
                        "local_tools": local_tools,
                        "mcp_servers_enabled": bridge_enabled,
                    },
                    "scope": "agent_turn",
                    "project_completion_verified": False,
                }
        except TimeoutError:
            await client.cancel()
            raise UncertainExecution(
                "agent_interrupted", "Grok execution cannot be confirmed"
            ) from None
        except (ValueError, OSError) as exc:
            raise UncertainExecution(
                "agent_interrupted", "Grok execution cannot be confirmed"
            ) from exc
        finally:
            await client.aclose()
            await reap_process(process)


class AgentManager:
    def __init__(self, config: Config, terminal: TerminalManager):
        self.config = config
        self.adapters: dict[str, AgentAdapter] = {
            "codex": CodexAdapter(terminal, config),
            "grok_api": GrokAPIAdapter(),
            "grok_acp": GrokACPAdapter(terminal, config),
            "qwen_acp": QwenACPAdapter(terminal, config),
            "grok_structured": GrokStructuredAdapter(terminal),
            "opencode": OpenCodeAdapter(terminal),
            "opencode_acp": OpenCodeACPAdapter(terminal),
            "opencode_http": OpenCodeHTTPAdapter(),
            "opencode_http_v2": OpenCodeHTTPV2Adapter(),
            "gemini_cli": GeminiAdapter(terminal),
            "claude_code": ClaudeCodeAdapter(terminal),
            "copilot_cli": CopilotCLIAdapter(terminal),
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
                            "mcp_servers_enabled": config.bridge_tools,
                        }
                        if config.kind == "codex"
                        else {}
                    ),
                    "executable_present": bool(
                        config.executable and Path(config.executable).is_file()
                    ),
                    **(
                        {
                            "execution_mode": "native_full_access"
                            if config.bridge_tools
                            else "isolated_text_only",
                            "supports_local_tools": config.allow_local_tools
                            and config.bridge_tools,
                            "supports_owned_resume": False,
                            "authentication_status": "unknown",
                        }
                        if config.kind
                        in {"opencode", "opencode_http", "gemini_cli", "claude_code", "copilot_cli"}
                        else {}
                    ),
                    **(
                        {
                            "execution_mode": "task_scoped_mcp"
                            if config.bridge_tools
                            else "isolated_text_only",
                            "supports_local_tools": config.allow_local_tools
                            and config.bridge_tools,
                            "supports_owned_resume": True,
                            "resume_scope": "sealed_idle_team_session",
                            "mcp_tools": config.qwen_mcp_tools,
                        }
                        if config.kind == "qwen_acp"
                        else {}
                    ),
                    "executable_runnable": bool(
                        config.executable
                        and Path(config.executable).is_file()
                        and os.access(config.executable, os.X_OK)
                    ),
                    "adapter_available": config.kind in self.adapters,
                    "daemon_status": "unknown",
                    "session_status": "unknown",
                    "task_status": "unknown",
                }
                for name, config in self.config.agents.items()
                if name in allowed
            ]
        }

    async def execute(
        self,
        task,
        args,
        principal,
        running,
        progress,
        *,
        owned_resume_session=None,
        handoff_reply=False,
        separate_managed=False,
        visible_binding=None,
    ):
        if args.agent not in principal.agents:
            raise BridgeError("agent_denied", "Agent identity not granted")
        config = self.config.agents.get(args.agent)
        if config is None or config.kind not in self.adapters:
            raise BridgeError("agent_unavailable", "Agent adapter is not configured")
        if guard := getattr(self, "worktree_guard", None):
            guard(task, args)
        if (
            self.config.visible_handoffs.enabled
            and not separate_managed
            and config.kind not in {"opencode_http", "opencode_http_v2"}
        ):
            if owned_resume_session is not None or handoff_reply or args.resume_session:
                raise BridgeError(
                    "visible_owned_resume_unsupported",
                    "A provider-owned managed resume cannot replace the assigned visible "
                    "CLI session",
                )
            if getattr(self, "visible_handoffs", None) is None:
                raise BridgeError(
                    "visible_route_unavailable", "Visible handoff service is required"
                )
            return await self.visible_handoffs.execute(
                task, args, running, progress, binding_override=visible_binding
            )
        if separate_managed and (guard := getattr(self, "managed_routing_guard", None)):
            guard(task, args)
        full_access = (
            principal.permission_level is not None
            and config.bridge_tools
            and config.allow_local_tools
            and "agent.local_tools" in principal.capabilities
        )
        if full_access and config.kind in {"grok_acp", "opencode_http", "opencode_http_v2"}:
            args = args.model_copy(update={"local_tools": True})
        if args.local_tools and (
            (config.kind not in {"grok_acp", "qwen_acp"} and not full_access)
            or not config.allow_local_tools
            or "agent.local_tools" not in principal.capabilities
        ):
            raise BridgeError(
                "agent_tools_denied",
                "Local agent tools require explicit operator and principal permission",
            )
        if args.resume_session and owned_resume_session is not None:
            raise BridgeError(
                "agent_resume_unsupported", "A turn cannot resume two different sessions"
            )
        resume_session = args.resume_session
        qwen_proof = None
        if resume_session is not None:
            if config.kind == "codex":
                owned_resume_session = resume_session
            elif config.kind in {"grok_acp", "opencode_http", "opencode_http_v2"}:
                pass
            elif config.kind == "qwen_acp":
                guard = getattr(self, "qwen_session_guard", None)
                if not separate_managed or guard is None:
                    raise BridgeError("team_task_required", "Qwen resume needs sealed team proof")
                qwen_proof = guard(task, args)
            elif config.kind in {"opencode", "opencode_acp"}:
                raise BridgeError(
                    "agent_resume_unsupported",
                    "OpenCode CLI/ACP resume has no persisted session store in the "
                    "isolated profile",
                )
            else:
                raise BridgeError(
                    "agent_resume_unsupported",
                    "This adapter cannot resume a provider session",
                )
        if (owned_resume_session is not None or handoff_reply) and config.kind != "codex":
            raise BridgeError(
                "agent_resume_unsupported", "Owned workflow continuation requires Codex"
            )
        extra = {"owned_session_proof": qwen_proof} if qwen_proof else {}
        if owned_resume_session is not None or handoff_reply:
            extra.update(
                {"owned_resume_session": owned_resume_session, "handoff_reply": handoff_reply}
            )
        if resume_session is not None and config.kind in {
            "grok_acp",
            "opencode_acp",
            "opencode",
            "opencode_http",
            "opencode_http_v2",
            "qwen_acp",
        }:
            extra["resume_session"] = resume_session
        try:
            async with asyncio.timeout(args.timeout):
                if full_access and config.kind in {
                    "opencode",
                    "gemini_cli",
                    "claude_code",
                    "copilot_cli",
                }:
                    if resume_session is not None:
                        raise BridgeError(
                            "agent_resume_unsupported",
                            "Full-access execution cannot resume a text session",
                        )
                    from kirabridge.agent_manager.full_access import FullAccessAdapter

                    return await FullAccessAdapter(
                        self.adapters[config.kind].terminal,
                        self.config._source_path,
                        principal.permission_level,
                    ).execute(task, args, config, principal.roots, running, progress)
                return await self.adapters[config.kind].execute(
                    task,
                    args,
                    config,
                    principal.roots,
                    running,
                    progress,
                    **extra,
                )
        except TimeoutError:
            raise UncertainExecution(
                "agent_timeout", "Agent completion could not be confirmed"
            ) from None
