"""Qwen Code 0.27.2 policy and lifecycle on the shared ACP stdio transport.

Task-owned MCP turns and explicitly proven owned-session recovery are supported.
Never authenticate, adopt an interactive session, retry a prompt, or infer acceptance.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from kirabridge.agent_manager.acp import ACPClient
from kirabridge.agent_manager.cli_support import cli_environment
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import reap_process, spawn_process


class QwenACPAdapter:
    interface_version = "1"

    def __init__(self, terminal=None, bridge_config=None):
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
        resume_session=None,
        before_spawn=None,
        recovery_binding=None,
        owned_session_proof=None,
    ) -> dict:
        if (resume_session is not None or args.resume_session) and owned_session_proof is None:
            raise BridgeError(
                "agent_resume_unsupported",
                "Qwen ACP resume has no verified persisted owner/task/CWD binding",
            )
        if owned_session_proof is not None:
            from kirabridge.agent_manager.qwen_session import QwenTeamSession

            if (
                not isinstance(owned_session_proof, QwenTeamSession)
                or recovery_binding is not None
                or resume_session != owned_session_proof.session_id
            ):
                raise BridgeError("agent_resume_denied", "Exclusive Qwen team proof required")
            owned_session_proof.validate_effect(task, args, config)
        if args.local_tools and (
            not config.allow_local_tools
            or not config.bridge_tools
            or config.sandbox_mode == "read-only"
        ):
            raise BridgeError(
                "agent_tools_denied", "Qwen coding requires its explicit MCP write profile"
            )
        if not config.executable or not config.model or not config.qwen_auth_type:
            raise BridgeError(
                "agent_config", "Qwen requires an executable and the existing model/auth selection"
            )
        if not all(isinstance(task.get(k), str) and task[k] for k in ("id", "principal")):
            raise BridgeError("agent_identity", "Qwen requires an owned Core task")
        if task.get("args") is not None and (
            AgentInput.model_validate(task["args"]).model_dump() != args.model_dump()
        ):
            raise BridgeError("agent_identity", "Qwen request differs from its owned Core task")
        if recovery_binding is not None:
            from kirabridge.agent_manager.qwen_recovery import QwenRecoveryBinding

            if not isinstance(recovery_binding, QwenRecoveryBinding):
                raise BridgeError(
                    "agent_recovery_denied", "Explicit typed recovery binding required"
                )
            recovery_binding.validate_effect(task, args, config)
        mcp_enabled = config.bridge_tools and bool(config.qwen_mcp_tools)
        if bool(config.bridge_tools) != bool(config.qwen_mcp_tools):
            raise BridgeError("agent_config", "Qwen MCP requires an explicit metadata tool profile")
        if (args.mcp_grants or args.mcp_operations) and not mcp_enabled:
            raise BridgeError("agent_tools_denied", "Task MCP grants require the configured bridge")
        if args.timeout > config.qwen_max_timeout:
            raise BridgeError(
                "agent_budget_denied", "Qwen timeout exceeds the configured operator ceiling"
            )
        timeout = args.timeout
        command = [
            config.executable,
            "--acp",
            "--bare",
            "--safe-mode",
            "--approval-mode",
            "default" if mcp_enabled else "plan",
            "--max-session-turns",
            str(config.qwen_max_session_turns),
            "--max-tool-calls",
            str(config.qwen_max_tool_calls) if mcp_enabled else "0",
            "--max-wall-time",
            str(max(1, math.ceil(timeout))),
            "--auth-type",
            config.qwen_auth_type,
            "--model",
            config.model,
        ]
        # Bare mode registers only these builtins in 0.27.2. Explicitly deny
        # them even when the single task-scoped MCP call is enabled.
        command += [
            "--exclude-tools",
            "read_file",
            "edit",
            "notebook_edit",
            "run_shell_command",
            "get_goal",
            "update_goal",
            "propose_goal",
            "exec",
            "structured_output",
        ]
        env = cli_environment(config, self.terminal)
        resources = ExitStack()
        servers = []
        try:
            if mcp_enabled:
                from kirabridge.agent_manager.qwen_mcp import task_server

                servers = [
                    resources.enter_context(
                        task_server(
                            self.bridge_config,
                            task,
                            args,
                            timeout,
                            team_scope=owned_session_proof.policy_scope()
                            if owned_session_proof
                            else None,
                        )
                    )
                ]
            with PathScope(roots).directory(args.cwd) as fd:
                if before_spawn is not None:
                    before_spawn()
                if owned_session_proof is not None:
                    owned_session_proof.validate_effect(task, args, config)
                process = await spawn_process(
                    command,
                    fd,
                    env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=1048576,
                )
        except BaseException:
            resources.close()
            raise
        client = ACPClient(process)
        session = None
        prompt_sent = False
        turn_result = None
        partial_observation = None
        binding = {
            "agent": args.agent,
            "task_id": task["id"],
            "owner": task["principal"],
            "cwd": str(Path(args.cwd).resolve()),
        }

        async def activity(kind):
            await running({**binding, "session_id": client.session_id, "event": kind})

        async def request(method, params):
            if method == "session/request_permission":
                if not prompt_sent:
                    return {"outcome": {"outcome": "cancelled"}}
                tool = params.get("toolCall", {}) if isinstance(params, dict) else {}
                name = tool.get("_meta", {}).get("toolName", "")
                prefix = "mcp__kirabridge__"
                name = name[len(prefix) :] if name.startswith(prefix) else name
                if name not in config.qwen_mcp_tools:
                    name = None
                # The private scoped proxy is the single argument/grant gate.
                # Duplicating exact-args matching here rejects native read pages
                # and makes an adapter decision look like a user cancellation.
                allowed = (
                    mcp_enabled
                    and client.session_id
                    and params.get("sessionId") == client.session_id
                    and name in config.qwen_mcp_tools
                )
                option = (
                    next(
                        (
                            o.get("optionId")
                            for o in params.get("options", [])
                            if isinstance(o, dict)
                            and o.get("kind") == "allow_once"
                            and o.get("optionId") == "proceed_once"
                        ),
                        None,
                    )
                    if allowed
                    else None
                )
                if not option:
                    await progress(
                        {
                            **binding,
                            "session_id": client.session_id,
                            "event": "permission_denied",
                            "permission_source": "adapter_policy",
                            "reason": "session_or_tool_not_granted"
                            if not allowed
                            else "allow_once_not_offered",
                            "arguments_sha256": digest(tool.get("rawInput")),
                        }
                    )
                return {
                    "outcome": {"outcome": "selected", "optionId": option}
                    if option
                    else {"outcome": "cancelled"}
                }
            # No fs, terminal or vendor-extension capabilities are advertised/granted.
            return None

        client.on_activity = activity
        client.on_request = request
        client.start()
        try:
            async with asyncio.timeout(timeout):
                await progress({**binding, "pid": process.pid, "event": "process_spawned"})
                init = await client.request(
                    "initialize", {"protocolVersion": 1, "clientCapabilities": {}}, timeout
                )
                if not isinstance(init, dict) or init.get("protocolVersion") != 1:
                    raise BridgeError("agent_protocol", "Qwen requires ACP v1")
                info = init.get("agentInfo", {})
                if info.get("name") != "qwen-code" or info.get("version") != "0.27.2":
                    raise BridgeError("agent_version", "Qwen ACP requires verified version 0.27.2")
                await progress({**binding, "event": "acp_initialized", "version": "0.27.2"})
                if recovery_binding is not None or owned_session_proof is not None:
                    if init.get("agentCapabilities", {}).get("loadSession") is not True:
                        raise BridgeError(
                            "agent_resume_unsupported", "Qwen did not negotiate session/load"
                        )
                    if owned_session_proof:
                        owned_session_proof.validate_effect(task, args, config)
                    target = owned_session_proof or recovery_binding
                    session = client.bind_session(target.session_id)
                    client.on_activity = None
                    new = await client.request(
                        "session/load",
                        {"sessionId": session, "cwd": args.cwd, "mcpServers": servers},
                        timeout,
                    )
                    client.begin_turn()
                    client.on_activity = activity
                    await client.request(
                        "session/set_mode",
                        {"sessionId": session, "modeId": "default" if mcp_enabled else "plan"},
                        timeout,
                    )
                    state = await client.request(
                        "qwen/status/session/context", {"sessionId": session}, timeout
                    )
                    expected_model = config.model + "(" + config.qwen_auth_type + ")"
                    if (
                        state.get("state", {}).get("models", {}).get("currentModelId")
                        != expected_model
                    ):
                        raise BridgeError(
                            "agent_recovery_denied", "Recovered Qwen model readback differs"
                        )
                    if state.get("state", {}).get("modes", {}).get("currentModeId") != (
                        "default" if mcp_enabled else "plan"
                    ):
                        raise BridgeError(
                            "agent_recovery_denied", "Recovered Qwen mode readback differs"
                        )
                    await progress(
                        {
                            **binding,
                            "session_id": session,
                            "event": "session_loaded",
                            **(
                                {"recovery_of": recovery_binding.original_core_task_id}
                                if recovery_binding
                                else {
                                    "team_id": owned_session_proof.team_id,
                                    "session_generation": owned_session_proof.generation,
                                }
                            ),
                        }
                    )
                else:
                    new = await client.request(
                        "session/new", {"cwd": args.cwd, "mcpServers": servers}, timeout
                    )
                    session = client.bind_session(new.get("sessionId"))
                    await progress({**binding, "session_id": session, "event": "session_created"})
                selected_effort = None
                if config.qwen_reasoning_effort:
                    selected_effort = await self._set_effort(
                        client, session, new, config.qwen_reasoning_effort, timeout
                    )
                await progress(
                    {
                        **binding,
                        "session_id": session,
                        "event": "session_settings_confirmed",
                        "session_reasoning_effort": selected_effort,
                        "mode": "default" if mcp_enabled else "plan",
                    }
                )
                if mcp_enabled:
                    await self._mcp_ready(client, session, args.cwd, timeout, progress, binding)
                if owned_session_proof:
                    owned_session_proof.validate_effect(task, args, config)
                prompt_sent = True
                result = await client.request(
                    "session/prompt",
                    {
                        "sessionId": session,
                        "prompt": [
                            {
                                "type": "text",
                                "text": (
                                    args.prompt
                                    + "\nKiraBridge task scope: "
                                    + json.dumps(
                                        {
                                            "task_id": task["id"],
                                            "cwd": args.cwd,
                                            "operations": args.mcp_operations,
                                            "protocol_arguments": [
                                                {
                                                    k: g.arguments[k]
                                                    for k in (
                                                        "version",
                                                        "workspace_id",
                                                        "catalog_revision",
                                                        "command",
                                                        "operation_id",
                                                    )
                                                    if k in g.arguments
                                                }
                                                for g in args.mcp_grants
                                            ],
                                        }
                                    )
                                    if mcp_enabled
                                    else args.prompt
                                ),
                            }
                        ],
                    },
                    timeout,
                )
                stop = result.get("stopReason") if isinstance(result, dict) else None
                if not isinstance(stop, str) or not stop:
                    raise UncertainExecution("agent_unconfirmed", "Qwen returned no stop reason")
                if not client.started:
                    await activity("prompt_response_observed")
                turn_result = {
                    "success": stop == "end_turn",
                    "text": client.text,
                    "final_message": client.text,
                    "evidence": {
                        **binding,
                        "adapter": "qwen_acp",
                        "pid": process.pid,
                        "version": "0.27.2",
                        "requested_model": config.model,
                        "session_reasoning_effort": selected_effort,
                        "requested_effort": config.qwen_reasoning_effort,
                        "effective_model_status": "unknown",
                        "session_id": session,
                        "session_resumed": recovery_binding is not None
                        or owned_session_proof is not None,
                        **(
                            {
                                "team_id": owned_session_proof.team_id,
                                "session_generation": owned_session_proof.generation,
                            }
                            if owned_session_proof
                            else {}
                        ),
                        **(
                            {"recovery_of": recovery_binding.original_core_task_id}
                            if recovery_binding
                            else {}
                        ),
                        "stop_reason": stop,
                        "local_tools_enabled": False,
                        "mcp_servers_enabled": mcp_enabled,
                        "max_session_turns": config.qwen_max_session_turns,
                        "max_tool_calls": config.qwen_max_tool_calls if mcp_enabled else 0,
                        "output_truncated": client.truncated,
                    },
                    "scope": "agent_turn",
                    "project_completion_verified": False,
                }
                await progress(
                    {
                        **turn_result["evidence"],
                        "event": "agent_turn_observed",
                        "observed_result": turn_result,
                    }
                )
                return turn_result
        except (TimeoutError, UncertainExecution, OSError, ValueError) as exc:
            if prompt_sent and client.text:
                partial_observation = {
                    **binding,
                    "session_id": client.session_id,
                    "text": client.text,
                    "output_truncated": client.truncated,
                    "completion_verified": False,
                    "stop_reason": None,
                    "error_code": getattr(exc, "code", type(exc).__name__),
                }
                try:
                    await progress(
                        {
                            "event": "agent_partial_observation",
                            **binding,
                            "unconfirmed_observation": partial_observation,
                        }
                    )
                except Exception:
                    pass  # Observation failure must not replace the primary UNKNOWN.
            await client.cancel()
            if not prompt_sent:
                error = BridgeError(
                    "qwen_handshake_failed",
                    "Qwen ACP handshake/session creation failed; no prompt sent",
                )
                error.provider_error = getattr(exc, "provider_error", None)
                raise error from exc
            if isinstance(exc, UncertainExecution):
                raise
            raise UncertainExecution(
                "agent_interrupted", "Qwen ACP completion is unknown; do not replay"
            ) from None
        finally:
            original_error = sys.exc_info()[1]
            await client.aclose()
            try:
                # Qwen 0.27.2 drains its MCP pool for up to eight seconds.
                # Keep the shared five-second default for all other providers.
                await reap_process(process, cleanup_timeout=15, census_timeout=2)
            except Exception as cleanup_error:
                try:
                    await progress(
                        {
                            **binding,
                            "session_id": client.session_id,
                            "event": "cleanup_unconfirmed",
                            "pid": process.pid,
                            "original_error_code": getattr(original_error, "code", None),
                            "cleanup_error_code": getattr(cleanup_error, "code", "cleanup_error"),
                            "cleanup_cause_type": type(cleanup_error.__cause__).__name__,
                            "cleanup_diagnostic": getattr(
                                cleanup_error, "cleanup_diagnostic", None
                            ),
                            "observed_result": turn_result,
                            "unconfirmed_observation": partial_observation,
                        }
                    )
                except Exception:
                    # A failed observation write must not replace either failure.
                    pass
                if original_error is None:
                    raise
                # Preserve the primary exception and keep cleanup separately.
                original_error.provider_error = {
                    **(getattr(original_error, "provider_error", None) or {}),
                    "cleanup_error_code": getattr(cleanup_error, "code", "cleanup_error"),
                }
            finally:
                resources.close()

    async def _mcp_ready(self, client, session, cwd, timeout, progress, binding):
        """0.27.2 connects explicit MCP servers in the background after session/new.

        Inspect native status without invoking a model or exporting server config.
        Never send a task to a model whose scoped tools have not actually loaded.
        """
        deadline = time.monotonic() + min(30, timeout / 2)
        observed = None
        while time.monotonic() < deadline:
            status = await client.request(
                "qwen/status/session/resources", {"sessionId": session}, timeout
            )
            if status.get("sessionId") != session or str(
                Path(status.get("workspaceCwd", "")).resolve()
            ) != str(Path(cwd).resolve()):
                raise BridgeError(
                    "agent_identity", "Qwen MCP status differs from the bound session"
                )
            mcp = status.get("mcp", {})
            servers = mcp.get("servers", [])
            server = next((s for s in servers if s.get("name") == "kirabridge"), {})
            state = {
                k: server.get(k) for k in ("name", "status", "mcpStatus", "toolCount", "errorKind")
            }
            state["discovery_state"] = mcp.get("discoveryState")
            if state != observed:
                await progress(
                    {
                        **binding,
                        "session_id": session,
                        "event": "mcp_discovery_observed",
                        "mcp": state,
                    }
                )
                observed = state
            if server.get("mcpStatus") == "connected":
                usage = await client.request(
                    "qwen/status/session/context_usage",
                    {"sessionId": session, "detail": True},
                    timeout,
                )
                entries = usage.get("usage", {}).get("mcpTools", [])
                names = [t.get("name") for t in entries if isinstance(t, dict) and t.get("name")]
                if names:
                    await progress(
                        {**binding, "session_id": session, "event": "mcp_ready", "mcp_tools": names}
                    )
                    return
            if mcp.get("discoveryState") == "completed":
                raise BridgeError(
                    "agent_mcp_unavailable", "Qwen scoped MCP tools did not connect; no prompt sent"
                )
            await asyncio.sleep(0.2)
        raise BridgeError(
            "agent_mcp_unavailable", "Qwen MCP discovery deadline elapsed; no prompt sent"
        )

    async def _set_effort(self, client, session, new, effort, timeout):
        option = next(
            (o for o in new.get("configOptions", []) if o.get("category") == "thought_level"), None
        )
        if option is None or effort not in {o.get("value") for o in option.get("options", [])}:
            raise BridgeError(
                "agent_selection_unsupported", "Requested Qwen reasoning effort is unavailable"
            )
        changed = await client.request(
            "session/set_config_option",
            {"sessionId": session, "configId": option["id"], "value": effort},
            timeout,
        )
        state = await client.request("qwen/status/session/context", {"sessionId": session}, timeout)
        for options in [
            changed.get("configOptions", []),
            state.get("state", {}).get("configOptions", []),
        ]:
            matched = next((o for o in options if o.get("id") == option["id"]), {})
            if matched.get("currentValue") != effort:
                raise BridgeError(
                    "agent_selection_unsupported", "Qwen reasoning effort readback differs"
                )
        return effort
