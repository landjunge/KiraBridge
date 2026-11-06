"""Opt-in native Grok verdicts; commentary never becomes a protocol envelope."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kirabridge.agent_manager.cli_support import bind_session, cli_environment
from kirabridge.bridge_core.models import BridgeError, TerminalInput, UncertainExecution
from kirabridge.filesystem_manager import PathScope


class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["pass", "fail"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(max_length=2000)


class NativeVerdictResult(BaseModel):
    # Native CLI metadata/text may evolve. Only these required typed receipt fields
    # are consumed; neither prose nor unknown metadata can generate agent actions.
    model_config = ConfigDict(extra="ignore", strict=True)
    stopReason: Literal["end_turn"]
    sessionId: str = Field(min_length=1, max_length=256)
    structuredOutput: ReviewVerdict


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class GrokStructuredAdapter:
    interface_version = "1"

    def __init__(self, terminal):
        self.terminal = terminal

    async def execute(
        self, task, args, config, roots, running, progress, *, before_spawn=None
    ) -> dict:
        if not config.executable:
            raise BridgeError("agent_config", "Grok executable must be explicitly configured")
        if (
            args.local_tools
            or config.sandbox_mode != "read-only"
            or config.bridge_tools
            or config.allow_local_tools
        ):
            raise BridgeError("agent_tools_denied", "Structured Grok review is strictly read-only")
        with PathScope(roots).directory(args.cwd):
            pass
        env = cli_environment(config, self.terminal)
        if any(
            os.environ.get(key) or env.get(key)
            for key in {"XAI_API_KEY", config.api_key_env}
            if key
        ):
            raise BridgeError(
                "agent_billing_unknown", "Structured Grok requires subscription login"
            )
        schema = files("kirabridge.autonext").joinpath("review_verdict.schema.json").read_text()
        with TemporaryDirectory(prefix="kirabridge-grok-review-") as temporary:
            prompt_path = Path(temporary).resolve() / "prompt.txt"
            fd = os.open(prompt_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(args.prompt)
            command = [
                config.executable,
                "--no-auto-update",
                "--no-leader",
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
                "--json-schema",
                schema,
                "--output-format",
                "json",
                "--prompt-file",
                str(prompt_path),
            ]
            if config.model:
                command += ["--model", config.model]

            async def spawned(evidence):
                await running({"agent": args.agent, **evidence})

            native = await self.terminal.execute(
                task["id"],
                task["principal"],
                TerminalInput(argv=command, cwd=args.cwd, timeout=args.timeout, max_output=1048576),
                roots,
                [config.executable],
                spawned,
                env=env,
                **({"before_spawn": before_spawn} if before_spawn is not None else {}),
            )
        if native["timed_out"] or native.get("terminated"):
            raise UncertainExecution("agent_timeout", "Grok verdict turn was interrupted")
        if native["exit_code"] != 0:
            raise BridgeError("agent_failed", "Native Grok verdict returned a nonzero exit code")
        if native.get("truncated"):
            raise UncertainExecution("agent_protocol", "Native Grok verdict output was truncated")
        try:
            payload = json.loads(native["stdout"], object_pairs_hook=unique_object)
            result = NativeVerdictResult.model_validate(payload)
            session = bind_session(None, result.sessionId)
        except (ValueError, TypeError, ValidationError):
            raise UncertainExecution(
                "agent_protocol", "Native Grok returned no strict structured verdict receipt"
            ) from None
        verdict = result.structuredOutput.model_dump()
        from kirabridge.capability_routing.evidence import native_metadata

        metadata = native_metadata("grok", native["stdout"], config.model)
        text = json.dumps({"kirabridge_team": "1", "result": json.dumps(verdict), "actions": []})
        await progress(
            {"agent": args.agent, "session_id": session, "event": "native_verdict_completed"}
        )
        return {
            "success": True,
            "text": text,
            "final_message": text,
            "evidence": {
                "agent": args.agent,
                "adapter": "grok_structured",
                "session_id": session,
                "turn_completed": True,
                "stop_reason": "end_turn",
                "native_result_received": True,
                "exit_code": native["exit_code"],
                "timed_out": False,
                "local_tools_enabled": False,
                "read_only_review": True,
                "structured_output_validated": True,
                **metadata,
            },
            "scope": "agent_turn",
            "project_completion_verified": False,
        }
