"""Opt-in ACP-PAP host seam; Core, MCP authorization and receipts stay authoritative.

No default registration or dependency download occurs on import. The first host
supports bounded text/file reads; local writes and terminal RPC are unadvertised.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import time
from dataclasses import dataclass
from pathlib import Path

from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.mcp_gateway.agent_policy import AgentTaskPolicy
from kirabridge.permissions import state_exclusions

LIBRARY_COMMIT = "2bb65784bc9d6df64d0b1fe057fe8736843cd10a"
LIBRARY_WHEEL_SHA256 = "95ad56ee9255fbff0bb50f55b7fe58c26ce47d56a4c9afb3eb2f18ba98c7fe74"
_MODULE_HASHES = {
    "__init__.py": "155e1750d6ad205f6cea8b2ff44e513ce762607d5490d7b99c08c37fbcedf535",
    "client.py": "dde9232bc91e8a08590c2e2e0aac5b221a9eb4d24d00e57f322b75a201b3d71a",
    "discovery.py": "86f08c07db345ea2da92e25538b0dac0e86fcd2066225ac3640ee763cb6453e4",
}


def _pinned_sdk():
    try:
        pap = importlib.import_module("acp_pap")
        acp = importlib.import_module("acp")
        schema = importlib.import_module("acp.schema")
        if importlib.metadata.version("agent-client-protocol") != "1.0.0":
            raise ValueError("ACP SDK pin differs")
        package = Path(pap.__file__).parent
        if any(
            hashlib.sha256((package / name).read_bytes()).hexdigest() != expected
            for name, expected in _MODULE_HASHES.items()
        ):
            raise ValueError("ACP-PAP source pin differs")
    except (ImportError, OSError, ValueError, importlib.metadata.PackageNotFoundError):
        raise BridgeError(
            "acp_dependency_unavailable", "Install the reviewed local ACP-PAP wheel"
        ) from None
    return pap, acp, schema


@dataclass(frozen=True)
class ACPHostProfile:
    """Trusted operator inputs; task grants still pass through AgentTaskPolicy."""

    argv: tuple[str, ...] = ()
    read_roots: tuple[str, ...] = ()
    max_calls: int = 8
    max_file_bytes: int = 65536
    max_output_bytes: int = 65536


class _BoundClient:
    def __init__(self, adapter, task, args, connection, restriction, schema, progress):
        self.adapter, self.task, self.args = adapter, task, args
        self.connection, self.restriction = connection, restriction
        self.schema, self.progress = schema, progress
        self.binding = None
        self.text = []
        self.output_bytes = 0

    def validate(self, binding=None):
        current = self.adapter.bridge.store.get(self.task["id"], self.task["principal"])
        self.restriction.validate_task(current)
        if current["request_sha256"] != self.task["request_sha256"]:
            raise BridgeError("agent_identity", "The original Core request differs")
        if (
            current["lease_owner"] != self.adapter.bridge.tasks.owner
            or current["lease_until"] is None
            or current["lease_until"] <= time.time()
        ):
            raise BridgeError("agent_identity", "The existing Core execution lease is not owned")
        self.adapter.bridge.security.authorize(self.task["principal"], "agent.execute")
        principal = self.adapter.bridge.security.principal(self.task["principal"])
        if self.args.agent not in principal.agents:
            raise BridgeError("agent_denied", "Agent identity is no longer granted")
        self.adapter.bridge.teams.authorize_execution(current)
        if binding is not None and (self.binding is None or binding != self.binding):
            raise BridgeError("agent_identity", "ACP callback differs from the owned Core binding")
        return current

    async def session_update(self, session_id, update, *, pap_binding, **kwargs):
        self.validate(pap_binding)
        if session_id != pap_binding.session_id:
            raise BridgeError("agent_identity", "ACP session differs")
        if getattr(update, "session_update", None) == "agent_message_chunk":
            text = getattr(getattr(update, "content", None), "text", "")
            self.output_bytes += len(text.encode("utf-8"))
            if self.output_bytes > self.adapter.profile.max_output_bytes:
                raise BridgeError("agent_output_limit", "ACP response exceeds host capture budget")
            self.text.append(text)
        await self.progress(
            {
                "event": "acp_update",
                "task_id": self.task["id"],
                "session_id": session_id,
                "connection_id": pap_binding.connection_id,
                "update_type": getattr(update, "session_update", "unknown"),
            }
        )

    async def read_text_file(
        self, session_id, path, line=None, limit=None, *, pap_binding, **kwargs
    ):
        self.validate(pap_binding)
        if session_id != pap_binding.session_id:
            raise BridgeError("agent_identity", "ACP session differs")
        arguments = {
            "query": {
                "operation": "file.read",
                "path": path,
                "max_bytes": self.adapter.profile.max_file_bytes,
            }
        }
        definitions = {tool.name: tool for tool in await self.connection.list_tools()}
        await self.restriction.authorize(
            self.connection, "read_query", arguments, definition=definitions.get("read_query")
        )
        self.validate(pap_binding)
        response = await self.connection.call_tool("read_query", arguments)
        data = response.structuredContent
        if response.isError or not isinstance(data, dict) or data.get("error"):
            raise BridgeError(
                "agent_host_read_failed", "Existing host read facade rejected the call"
            )
        if data.get("truncated") or not data.get("text_lossless", False):
            raise BridgeError(
                "agent_host_read_limit", "Only complete bounded UTF-8 reads are supported"
            )
        text = data["text"]
        if line is not None or limit is not None:
            start = (line or 1) - 1
            text = "".join(
                text.splitlines(keepends=True)[start : None if limit is None else start + limit]
            )
        return self.schema.ReadTextFileResponse(content=text)

    async def request_permission(self, session_id, tool_call, options, *, pap_binding, **kwargs):
        self.validate(pap_binding)
        if self.adapter.permission_decider is not None:
            response = await self.adapter.permission_decider(pap_binding, tool_call, options)
            self.validate(pap_binding)
            return response
        rejected = next((option for option in options if option.kind == "reject_once"), None)
        if rejected is not None:
            return self.schema.RequestPermissionResponse(
                outcome=self.schema.AllowedOutcome(option_id=rejected.option_id)
            )
        return self.schema.RequestPermissionResponse(outcome=self.schema.DeniedOutcome())


class ACPHostAdapter:
    """Register explicitly with AgentManager.register('acp_pap_host', adapter).

    connection_for(owner) supplies an existing authenticated DaemonConnection.
    Neither the peer nor AgentInput supplies credentials, commands or profiles.
    """

    interface_version = "1"

    def __init__(
        self,
        bridge,
        connection_for,
        *,
        profile=None,
        events=None,
        permission_decider=None,
    ):
        self.bridge, self.connection_for = bridge, connection_for
        self.profile = profile or ACPHostProfile()
        self.events, self.permission_decider = events, permission_decider
        self.active = {}

    async def cancel(self, task_id):
        agent, session_id = self.active[task_id]
        await agent.cancel(session_id)

    async def execute(self, task, args, config, roots, running, progress):
        pap, acp, schema = _pinned_sdk()
        stored = self.bridge.store.get(task["id"], task["principal"])
        if (
            stored["operation"] != "agent.execute"
            or stored["args"] != task.get("args")
            or AgentInput.model_validate(stored["args"]).model_dump() != args.model_dump()
            or args.resume_session
            or args.local_tools
        ):
            raise BridgeError("agent_identity", "A fresh read-only owned Core task is required")
        if not config.executable or not Path(config.executable).is_absolute():
            raise BridgeError("agent_config", "An explicit host-selected executable is required")
        if (
            args.mcp_grants
            or set(args.mcp_operations) - {"file.read"}
            or args.mcp_operations
            and not config.bridge_tools
        ):
            raise BridgeError(
                "agent_tools_denied", "Host supports the existing scoped read operation"
            )
        principal = self.bridge.security.principal(stored["principal"], "agent.execute")
        for root in args.mcp_read_roots:
            PathScope(list(self.profile.read_roots)).split(root)
            PathScope([*principal.roots, *principal.read_roots]).split(root)
        restriction = AgentTaskPolicy(
            owner=stored["principal"],
            task_id=stored["id"],
            agent=args.agent,
            cwd=args.cwd,
            arguments_sha256=digest(stored["args"]),
            expires_at=time.time() + args.timeout,
            operations=args.mcp_operations,
            read_roots=args.mcp_read_roots,
            tools=["read_query"],
            capabilities=principal.capabilities,
            max_calls=self.profile.max_calls,
        )
        client = _BoundClient(
            self,
            stored,
            args,
            self.connection_for(stored["principal"]),
            restriction,
            schema,
            progress,
        )
        client.validate()
        grant_ref = digest(
            {
                "task": stored["id"],
                "owner": stored["principal"],
                "request": stored["request_sha256"],
                "grant": restriction.model_dump(),
            }
        )
        scope = PathScope(roots, excluded=state_exclusions(self.bridge.config, principal))
        with scope.directory(args.cwd):
            launch = pap.LaunchSpec(
                Path(config.executable),
                args=self.profile.argv,
                cwd=Path(args.cwd),
                env=self.bridge.terminal.environment,
            )
            capabilities = schema.ClientCapabilities.model_validate(
                {
                    "fs": {"readTextFile": "file.read" in args.mcp_operations},
                }
            )
            async with pap.connect(
                launch, host=client, capabilities=capabilities, events=self.events
            ) as agent:
                session = await agent.session(cwd=args.cwd, grant_ref=grant_ref)
                client.binding = agent.session_binding(session.session_id)
                client.validate(client.binding)
                self.active[stored["id"]] = (agent, session.session_id)
                try:
                    await running(
                        {
                            "event": "acp_host_started",
                            "pid": agent.pid,
                            "session_id": session.session_id,
                            "connection_id": agent.connection_id,
                            "request_sha256": stored["request_sha256"],
                            "grant_ref": grant_ref,
                            "automatic_retry": False,
                        }
                    )
                    client.validate(client.binding)
                    result = await agent.task(session.session_id, args.prompt, task_id=stored["id"])
                except acp.RequestError as error:
                    return {
                        "success": False,
                        "terminal_response": "rpc_error",
                        "rpc_error_code": error.code,
                        "session_id": session.session_id,
                    }
                except (ConnectionError, OSError) as error:
                    raise UncertainExecution(
                        "acp_host_interrupted", "ACP outcome is unknown"
                    ) from error
                finally:
                    self.active.pop(stored["id"], None)
                return {
                    "success": result.stop_reason == "end_turn",
                    "stop_reason": result.stop_reason,
                    "terminated": result.stop_reason == "cancelled",
                    "text": "".join(client.text),
                    "session_id": session.session_id,
                    "connection_id": agent.connection_id,
                    "request_sha256": stored["request_sha256"],
                    "grant_ref": grant_ref,
                    "delivery_failures": [
                        {
                            "target": failure.target,
                            "count": failure.count,
                            "error_type": failure.error_type,
                        }
                        for failure in result.delivery_failures
                    ],
                    "ingress_rejection_count": agent.ingress_rejection_count,
                    "library_commit": LIBRARY_COMMIT,
                    "evidence": {
                        "source": "acp_terminal_response",
                        "stop_reason": result.stop_reason,
                        "session_id": session.session_id,
                        "automatic_retry": False,
                    },
                }
