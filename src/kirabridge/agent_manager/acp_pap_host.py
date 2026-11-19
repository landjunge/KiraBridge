"""Opt-in ACP-PAP host adapter (agent kind ``acp_pap``, default OFF).

One owned connection and one session per Core task. ``(connection_id, session_id)``
maps to the already owned task principal, request hash, canonical cwd and grant
record. Host callbacks resolve only the trusted ``pap_binding`` supplied by
``acp_pap``; peer-supplied paths go through the existing ``PathScope`` checks. No
second approval flow exists here. The prompt is sent at most once: timeout,
disconnect or cancellation after sending stays UNKNOWN and is never resent.

``acp_pap`` is an optional dependency and is imported lazily.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from kirabridge.agent_manager.cli_support import cli_environment
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution, digest
from kirabridge.filesystem_manager import FilesystemManager, PathScope

_READ_BYTES = 1048576  # Same page size as the existing file-read path.


@dataclass(frozen=True)
class OwnedTask:
    """Existing Core task ownership and grant record for one session."""

    task_id: str
    principal: str
    request_hash: str
    cwd: str
    roots: tuple[str, ...]
    grant_ref: str  # Opaque; the only grant identifier handed to acp_pap.


def _import_acp_pap():
    try:
        import acp_pap
    except ImportError:
        raise BridgeError(
            "agent_unavailable", "The optional acp_pap package is not installed"
        ) from None
    return acp_pap


class ACPPAPHostAdapter:
    interface_version = "1"

    def __init__(self, terminal=None, bridge_config=None):
        self.terminal = terminal
        self.bridge_config = bridge_config
        # (connection_id, session_id) -> owned task. Connection IDs are host-allocated,
        # so the same wire session ID on two connections never aliases.
        self.owned: dict[tuple[str, str], OwnedTask] = {}
        self._texts: dict[tuple[str, str], list[str]] = {}
        self._notify: dict[tuple[str, str], object] = {}

    # -- trusted lookup used by every host callback ---------------------------

    def _resolve(self, kwargs) -> tuple[tuple[str, str], OwnedTask]:
        from acp import RequestError

        binding = kwargs.get("pap_binding")
        key = (getattr(binding, "connection_id", None), getattr(binding, "session_id", None))
        record = self.owned.get(key)
        if record is None or binding.grant_ref != record.grant_ref or binding.cwd != record.cwd:
            raise RequestError.invalid_params({"reason": "unowned_session"})
        return key, record

    # -- SDK Client callbacks (only advertised/implemented ones) ---------------

    async def session_update(self, session_id, update, **kwargs):
        key, record = self._resolve(kwargs)
        kind = getattr(update, "session_update", None)
        content = getattr(update, "content", None)
        text = getattr(content, "text", None)
        if kind == "agent_message_chunk" and isinstance(text, str):
            self._texts[key].append(text)
        await self._notify[key]({"event": kind or "session_update", "task_id": record.task_id})

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        from acp.schema import DeniedOutcome, RequestPermissionResponse

        key, record = self._resolve(kwargs)
        # No MCP/tool grant is carried into this first package: never approve.
        await self._notify[key](
            {
                "event": "permission_denied",
                "permission_source": "adapter_policy",
                "task_id": record.task_id,
                "reason": "no_tool_grant",
            }
        )
        return RequestPermissionResponse(outcome=DeniedOutcome())

    async def read_text_file(self, session_id, path, **kwargs):
        from acp import RequestError
        from acp.schema import ReadTextFileResponse

        _, record = self._resolve(kwargs)
        try:
            # Existing host policy: absolute path inside the principal's roots, no symlinks.
            page = FilesystemManager().read(PathScope(list(record.roots)), path, _READ_BYTES)
        except BridgeError as error:
            raise RequestError.invalid_params({"reason": error.code}) from None
        return ReadTextFileResponse(content=page["text"])

    # -- execution ------------------------------------------------------------

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        acp_pap = _import_acp_pap()
        from acp.schema import ClientCapabilities, FileSystemCapabilities

        if not all(isinstance(task.get(k), str) and task[k] for k in ("id", "principal")):
            raise BridgeError("agent_identity", "ACP-PAP requires an owned Core task")
        if task.get("args") is not None and (
            AgentInput.model_validate(task["args"]).model_dump() != args.model_dump()
        ):
            raise BridgeError("agent_identity", "ACP-PAP request differs from its owned Core task")
        if args.local_tools or args.mcp_grants or args.mcp_operations or args.mcp_read_roots:
            raise BridgeError(
                "agent_tools_denied", "The ACP-PAP host adapter has no tool or MCP scope yet"
            )
        if not config.executable:
            raise BridgeError("agent_config", "ACP-PAP requires an executable")
        with PathScope(roots).directory(args.cwd):
            pass  # Existing root/symlink policy for the task cwd.
        cwd = str(Path(args.cwd).resolve())
        request_hash = digest(task["args"] if task.get("args") is not None else args.model_dump())
        record = OwnedTask(
            task["id"],
            task["principal"],
            request_hash,
            cwd,
            tuple(roots),
            digest({"task": task["id"], "owner": task["principal"], "request": request_hash}),
        )
        binding = {"agent": args.agent, "task_id": task["id"], "owner": task["principal"]}
        started = False

        async def notify(event):
            nonlocal started
            if not started and event.get("event") != "permission_denied":
                started = True
                await running({**binding, **event})
            else:
                await progress({**binding, **event})

        launch = acp_pap.LaunchSpec(
            Path(config.executable),
            args=tuple(config.acp_pap_args),
            cwd=Path(cwd),
            env=cli_environment(config, self.terminal),
        )
        key = None
        prompt_sent = False
        try:
            async with acp_pap.connect(
                launch,
                host=self,
                capabilities=ClientCapabilities(fs=FileSystemCapabilities(read_text_file=True)),
            ) as agent:
                try:
                    session = await agent.session(cwd=cwd, grant_ref=record.grant_ref)
                except Exception as error:
                    raise BridgeError(
                        "acp_pap_session_failed", "ACP-PAP session creation failed; no prompt sent"
                    ) from error
                key = (agent.connection_id, session.session_id)
                self.owned[key] = record
                self._texts[key] = []
                self._notify[key] = notify
                prompt_sent = True
                try:
                    result = await agent.task(session.session_id, args.prompt, task_id=task["id"])
                except asyncio.CancelledError:
                    raise  # The caller's deadline/cancel; the outcome stays UNKNOWN upstream.
                except Exception as error:
                    raise UncertainExecution(
                        "agent_interrupted", "ACP-PAP completion is unknown; do not replay"
                    ) from error
                failures = [
                    {
                        "task_id": task["id"],
                        "session_id": f.session_id,
                        "target": f.target,
                        "count": f.count,
                        "error_type": f.error_type,
                        "message": f.message,
                    }
                    for f in result.delivery_failures
                ]
                for failure in failures:
                    try:
                        await progress({**binding, "event": "delivery_failure", **failure})
                    except Exception:
                        pass  # Kept in the result evidence below; never erases the response.
                text = "".join(self._texts[key])
        except asyncio.CancelledError:
            raise
        except (BridgeError, UncertainExecution):
            raise
        except Exception as error:
            if not prompt_sent:
                raise BridgeError(
                    "acp_pap_handshake_failed", "ACP-PAP handshake failed; no prompt sent"
                ) from error
            raise UncertainExecution(
                "agent_interrupted", "ACP-PAP completion is unknown; do not replay"
            ) from error
        finally:
            if key is not None:
                for table in (self.owned, self._texts, self._notify):
                    table.pop(key, None)
        stop = result.stop_reason
        return {
            "success": stop == "end_turn",
            "text": text,
            "final_message": text,
            "evidence": {
                **binding,
                "adapter": "acp_pap",
                "cwd": cwd,
                "request_sha256": request_hash,
                "session_id": result.session_id,
                "stop_reason": stop,
                "delivery_failures": failures,
                "local_tools_enabled": False,
                "effective_model_status": "unknown",
            },
            "scope": "agent_turn",
            "project_completion_verified": False,
        }
