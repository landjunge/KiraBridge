"""Claude Code's native JSONL print protocol.

Default: text only, all local tools disabled. Coordinator mode (BP-CLI-01) is selected only
by an explicit `output_schema` naming a packaged AutoNext schema: a structured headless turn
in the fixed worktree. Its verifier role is technically read-only; budget goes through the
reserve/settle interface (fail closed until TollGate BP-TG-01 is bound).
"""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kirabridge.agent_manager.cli_support import BoundedText, bind_session, cli_environment
from kirabridge.agent_manager.grok_structured import ReviewVerdict, unique_object
from kirabridge.autonext.budget import FailClosedBudgetGate
from kirabridge.bridge_core.models import BridgeError, TerminalInput, UncertainExecution
from kirabridge.filesystem_manager import PathScope

READ_TOOLS = ("Read", "Grep", "Glob")
WRITE_TOOLS = ("Edit", "Write")
# Never available to either role (shell, notebooks, network, delegation, MCP).
DENIED_TOOLS = (
    "Bash",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "TodoWrite",
    "SlashCommand",
)
WRITE_CLASS = {"Bash", "Edit", "Write", "NotebookEdit", "MultiEdit"}
BILLING_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)


class TeamTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kirabridge_team: Literal["1"]
    result: str
    actions: list[str] = Field(max_length=0)


class ClaudeCodeAdapter:
    interface_version = "1"

    def __init__(self, terminal, budget=None):
        self.terminal = terminal
        # Callable returning the current BudgetGate; the default is fail-closed.
        self.budget = budget or FailClosedBudgetGate

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Claude Code executable must be explicit")
        if args.local_tools:
            raise BridgeError("agent_tools_unsupported", "Claude Code currently supports text only")
        if config.output_schema:
            return await self._structured_turn(
                task, args, config, roots, running, progress, self._role(config)
            )
        with PathScope(roots).directory(args.cwd):
            pass

        session = None
        started = False
        terminal_result = None
        output = BoundedText()

        async def mark_running(event):
            nonlocal started
            if not started:
                started = True
                await running({"agent": args.agent, "session_id": session, "event": event})

        async def event(line):
            nonlocal session, terminal_result
            try:
                value = json.loads(line)
            except ValueError:
                return
            if not isinstance(value, dict):
                return
            kind = value.get("type")
            if value.get("session_id") is not None:
                session = bind_session(session, value["session_id"])
            if kind == "system" and value.get("subtype") == "init":
                if any(value.get(key) for key in ("tools", "mcp_servers", "plugins")):
                    raise UncertainExecution(
                        "agent_tools_unexpected", "Claude Code reported disabled capabilities"
                    )
                if session:
                    await progress({"agent": args.agent, "session_id": session, "event": "init"})
            elif kind == "assistant" and session:
                if (
                    value.get("error")
                    or value.get("isApiErrorMessage")
                    or value.get("is_api_error_message")
                ):
                    return
                message = value.get("message")
                if not isinstance(message, dict):
                    return
                content = message.get("content", [])
                if not isinstance(content, list):
                    return
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") in {"tool_use", "server_tool_use"}:
                        raise UncertainExecution(
                            "agent_tools_unexpected", "Claude Code requested a disabled tool"
                        )
                await mark_running("assistant_message")
            elif kind == "result" and session:
                if terminal_result is not None:
                    raise UncertainExecution("agent_protocol", "Duplicate Claude Code result")
                subtype = value.get("subtype")
                if subtype not in {
                    "success",
                    "error_during_execution",
                    "error_max_turns",
                    "error_max_budget_usd",
                    "error_max_structured_output_retries",
                }:
                    raise UncertainExecution("agent_protocol", "Unknown Claude Code result subtype")
                success = subtype == "success" and value.get("is_error") is False
                terminal_result = {"subtype": subtype, "success": success}
                if success:
                    text = value.get("result")
                    if not isinstance(text, str):
                        raise UncertainExecution("agent_protocol", "Claude Code result has no text")
                    await mark_running("native_result_observed")
                    output.append(text)

        command = [
            config.executable,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--safe-mode",
            "--setting-sources",
            "",
            "--settings",
            '{"disableAllHooks":true}',
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
        ]
        if config.model:
            command += ["--model", config.model]

        async def spawned(evidence):
            await progress({"agent": args.agent, **evidence})

        # Native @file and leading /command preprocessing must not inspect files
        # before the tool policy applies. The model receives reconstructible text.
        prompt = "KiraBridge text-only request, decode this JSON string as the user text:\n"
        prompt += json.dumps(args.prompt, ensure_ascii=True).replace("@", "\\u0040")
        # A private empty cwd also excludes repository context before tool policy
        # evaluation. Safe mode still preserves the CLI's own cached authentication.
        with TemporaryDirectory(prefix="kirabridge-claude-") as workspace:
            result = await self.terminal.execute(
                task["id"],
                task["principal"],
                TerminalInput(argv=command, cwd=workspace, timeout=args.timeout),
                [workspace],
                [config.executable],
                spawned,
                env=cli_environment(config, self.terminal),
                stdin=prompt.encode("utf-8"),
                line_callback=event,
            )
        if result["timed_out"] or result.get("terminated"):
            raise UncertainExecution(
                "agent_timeout", "Claude Code was interrupted; outcome is unknown"
            )
        if terminal_result is None:
            raise UncertainExecution("agent_unconfirmed", "No native Claude Code result received")
        success = terminal_result["success"] and result["exit_code"] == 0
        return {
            "success": success,
            "text": output.text if success else "",
            "final_message": output.text if success else "",
            "evidence": {
                "agent": args.agent,
                "adapter": "claude_code",
                "session_id": session,
                "result_subtype": terminal_result["subtype"],
                "native_result_received": True,
                "exit_code": result["exit_code"],
                "timed_out": False,
                "local_tools_enabled": False,
                "mcp_servers_enabled": False,
                "customizations_enabled": False,
                "workspace_isolated": True,
                "session_persisted": False,
                "output_truncated": output.truncated,
            },
            "scope": "model_turn",
            "project_completion_verified": False,
        }

    @staticmethod
    def _role(config):
        """Role comes only from a packaged schema, never from model or board text."""
        path = Path(config.output_schema)
        base = files("kirabridge.autonext")
        for role, name in (("verifier", "review_verdict"), ("worker", "team_turn")):
            packaged = Path(str(base.joinpath(name + ".schema.json")))
            if path.is_absolute() and path.resolve() == packaged.resolve():
                return role
        raise BridgeError("agent_schema", "Only packaged AutoNext schemas select coordinator mode")

    def allowed_tools(self, config, role) -> tuple[str, ...]:
        if role == "worker" and config.sandbox_mode == "workspace-write":
            return READ_TOOLS + WRITE_TOOLS
        return READ_TOOLS

    async def _structured_turn(self, task, args, config, roots, running, progress, role) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Claude Code executable must be explicit")
        if (
            args.local_tools
            or config.bridge_tools
            or config.allow_local_tools
            or config.sandbox_mode not in {"read-only", "workspace-write"}
            or (role == "verifier" and config.sandbox_mode != "read-only")
        ):
            raise BridgeError("agent_tools_denied", "Claude coordinator role exceeds its scope")
        with PathScope(roots).directory(args.cwd):
            pass
        cwd = Path(args.cwd).resolve(strict=True)
        env = cli_environment(config, self.terminal)
        if any(os.environ.get(key) or env.get(key) for key in BILLING_ENV):
            raise BridgeError(
                "agent_billing_unknown", "Claude coordinator requires subscription login"
            )
        allowed = self.allowed_tools(config, role)
        schema_name = "review_verdict" if role == "verifier" else "team_turn"
        schema = files("kirabridge.autonext").joinpath(schema_name + ".schema.json").read_text()
        session = None
        result_event = None

        async def event(line):
            nonlocal session, result_event
            try:
                value = json.loads(line)
            except ValueError:
                return
            if not isinstance(value, dict):
                return
            if value.get("session_id") is not None:
                session = bind_session(session, value["session_id"])
            kind = value.get("type")
            if kind == "system" and value.get("subtype") == "init":
                tools = value.get("tools")
                if (
                    not isinstance(tools, list)
                    or set(tools) - set(allowed)
                    or any(value.get(key) for key in ("mcp_servers", "plugins"))
                ):
                    raise UncertainExecution(
                        "agent_tools_unexpected", "Claude Code reported unapproved capabilities"
                    )
                await progress({"agent": args.agent, "session_id": session, "event": "init"})
            elif kind == "assistant":
                message = value.get("message")
                content = message.get("content", []) if isinstance(message, dict) else []
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") in {
                        "tool_use",
                        "server_tool_use",
                    }:
                        self._check_tool_use(block, allowed, cwd)
            elif kind == "result":
                if result_event is not None:
                    raise UncertainExecution("agent_protocol", "Duplicate Claude Code result")
                result_event = value

        command = [
            config.executable,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--safe-mode",
            "--setting-sources",
            "",
            "--settings",
            '{"disableAllHooks":true}',
            "--tools",
            ",".join(allowed),
            "--disallowedTools",
            ",".join(DENIED_TOOLS + tuple(t for t in WRITE_TOOLS if t not in allowed)),
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
            "--json-schema",
            schema,
        ]
        if config.model:
            command += ["--model", config.model]

        async def spawned(evidence):
            await running({"agent": args.agent, **evidence})

        # Prevent native @file preprocessing: only the JSON tail after the first line
        # carries untrusted text, and @ is an equivalent JSON escape.
        head, sep, tail = args.prompt.partition("\n")
        prompt = head + sep + tail.replace("@", "\\u0040")
        gate = self.budget()
        reservation = gate.reserve(
            {
                "cli": "claude",
                "role": role,
                "agent": args.agent,
                "task_id": task["id"],
                "timeout_seconds": args.timeout,
            }
        )
        outcome, pending = "unknown", None
        try:
            native = await self.terminal.execute(
                task["id"],
                task["principal"],
                TerminalInput(argv=command, cwd=str(cwd), timeout=args.timeout, max_output=1048576),
                roots,
                [config.executable],
                spawned,
                env=env,
                stdin=prompt.encode("utf-8"),
                line_callback=event,
            )
            if not (native["timed_out"] or native.get("terminated")) and result_event:
                bad = (
                    result_event.get("subtype") != "success"
                    or result_event.get("is_error") is not False
                    or native["exit_code"] != 0
                )
                outcome = "failed" if bad else "completed"
        except BaseException as error:
            pending = error
            if isinstance(error, BridgeError) and not isinstance(error, UncertainExecution):
                outcome = "failed"
            raise
        finally:
            try:
                gate.settle(reservation, outcome)
            except Exception:
                if pending is None:
                    raise UncertainExecution(
                        "agent_budget_settlement", "Budget settlement failed; outcome unknown"
                    ) from None
        if native["timed_out"] or native.get("terminated"):
            raise UncertainExecution(
                "agent_timeout", "Claude Code was interrupted; outcome is unknown"
            )
        if result_event is None:
            raise UncertainExecution("agent_unconfirmed", "No native Claude Code result received")
        if (
            result_event.get("subtype") != "success"
            or result_event.get("is_error") is not False
            or native["exit_code"] != 0
        ):
            raise BridgeError("agent_failed", "Native Claude Code turn did not succeed")
        try:
            output = result_event["structured_output"]
            payload = json.loads(json.dumps(output), object_pairs_hook=unique_object)
            if role == "verifier":
                verdict = ReviewVerdict.model_validate(payload).model_dump()
                text = json.dumps(
                    {"kirabridge_team": "1", "result": json.dumps(verdict), "actions": []}
                )
            else:
                text = json.dumps(TeamTurn.model_validate(payload).model_dump())
        except (KeyError, ValueError, TypeError, ValidationError):
            raise UncertainExecution(
                "agent_protocol", "Claude Code returned no strict structured result"
            ) from None
        await progress(
            {"agent": args.agent, "session_id": session, "event": "native_result_observed"}
        )
        return {
            "success": True,
            "text": text,
            "final_message": text,
            "evidence": {
                "agent": args.agent,
                "adapter": "claude_headless",
                "role": role,
                "session_id": session,
                "sandbox_mode": config.sandbox_mode,
                "tools": list(allowed),
                "turn_completed": True,
                "native_result_received": True,
                "exit_code": native["exit_code"],
                "timed_out": False,
                "local_tools_enabled": False,
                "write_tools_enabled": any(t in WRITE_TOOLS for t in allowed),
                "mcp_servers_enabled": False,
                "structured_output_validated": True,
                "session_persisted": False,
            },
            "scope": "agent_turn",
            "project_completion_verified": False,
        }

    @staticmethod
    def _check_tool_use(block, allowed, cwd):
        name = block.get("name")
        if name in WRITE_CLASS and name not in allowed:
            raise BridgeError("agent_write_denied", "Write-class tool request rejected")
        if name not in allowed:
            raise UncertainExecution(
                "agent_tools_unexpected", "Claude Code requested an unapproved tool"
            )
        if name in WRITE_TOOLS:
            data = block.get("input")
            target = data.get("file_path") if isinstance(data, dict) else None
            if not isinstance(target, str) or not Path(target).is_absolute():
                raise BridgeError("agent_write_denied", "Write target must be absolute")
            resolved = Path(os.path.realpath(target))
            if resolved != cwd and cwd not in resolved.parents:
                raise BridgeError("agent_write_denied", "Write target outside the fixed worktree")
