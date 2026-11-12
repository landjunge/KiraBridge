"""Task restrictions on the existing authenticated stdio proxy; no new authority.

Exact call grants intersect the operator toolset and current principal rights.
Adaptive coding uses the existing task_request path, explicitly allowed operations,
parent-bound child IDs, and the owner's existing filesystem scope. No OS sandbox
or protection from other processes of the same user is claimed.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from kirabridge.bridge_core.models import AgentToolGrant, BridgeError, TaskRequest, digest
from kirabridge.operations import OPERATIONS, READ_OPERATIONS, capability_for
from kirabridge.private_files import private_json

# Generic exact grants use the existing operation-to-capability contract.
_TOOL_OPERATIONS = {name.replace(".", "_"): name for name in OPERATIONS}
_TOOL_CAPABILITIES = {
    "bridge_epoch": "bridge.health",
    "bridge_health": "bridge.health",
    "task_get": "task.read",
    "task_events": "task.read",
    "task_request": None,
    "operation_catalog": "bridge.health",
    "policy_inspect": "policy.inspect",
    "read_query": None,
    "td_get_thread": "threaddesk.read",
    "whiteboard_read": "threaddesk.read",
    "td_command_query": "threaddesk.read",
}


class TeamSessionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: str
    work_id: str
    session_id: str
    generation: int = Field(ge=0)


class AgentTaskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_scope: TeamSessionScope | None = None
    owner: str
    task_id: str
    agent: str
    cwd: str
    arguments_sha256: str
    expires_at: float
    grants: list[AgentToolGrant] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    read_roots: list[str] = Field(default_factory=list)
    read_only: bool = True
    full_access: bool = False
    max_calls: int = Field(default=1, ge=1, le=4096)
    _calls: int = PrivateAttr(default=0)
    _used: dict[str, int] = PrivateAttr(default_factory=dict)
    _children: dict[str, str] = PrivateAttr(default_factory=dict)
    _entry_ids: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _note_pages: dict[str, int] = PrivateAttr(default_factory=dict)
    _pages: dict[str, tuple[str, int, int]] = PrivateAttr(default_factory=dict)
    _pending_reads: set[str] = PrivateAttr(default_factory=set)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    @classmethod
    def load(cls, path, owner):
        value = cls.model_validate(private_json(Path(path)))
        if value.owner != owner:
            raise BridgeError("agent_task_denied", "MCP policy owner differs from connection")
        return value

    def validate_task(self, task):
        if (
            time.time() >= self.expires_at
            or not isinstance(task, dict)
            or task.get("principal") != self.owner
            or task.get("id") != self.task_id
            or task.get("operation") != "agent.execute"
            or task.get("state") not in {"accepted", "running"}
            or digest(task.get("args")) != self.arguments_sha256
            or task.get("args", {}).get("agent") != self.agent
            or task.get("args", {}).get("cwd") != self.cwd
        ):
            raise BridgeError("agent_task_denied", "MCP task binding is no longer active")

    def permits_tool(self, tool):
        name = tool.name
        if name not in self.tools:
            return False
        cap = _TOOL_CAPABILITIES.get(name)
        if name in _TOOL_OPERATIONS:
            cap = capability_for(_TOOL_OPERATIONS[name])
        if cap is not None and cap not in self.capabilities:
            return False
        if name == "task_request":
            return bool(self.operations)
        if name == "read_query" and set(self.operations) & {"file.read", "file.list"}:
            return True
        if name in {"task_get", "task_events"} and self.operations:
            return "task.read" in self.capabilities
        if not any(grant.tool == name for grant in self.grants):
            return False
        annotations = tool.annotations
        return not self.read_only or bool(
            annotations
            and annotations.readOnlyHint is True
            and annotations.destructiveHint is not True
        )

    def _child(self, arguments):
        request = TaskRequest.model_validate((arguments or {}).get("request"))
        if (
            set(arguments) != {"request"}
            or request.parent_id != self.task_id
            or request.operation not in self.operations
            or request.operation not in OPERATIONS
            or capability_for(request.operation) not in self.capabilities
            or (self.read_only and request.operation not in READ_OPERATIONS)
            or request.operation == "agent.execute"
        ):
            raise BridgeError(
                "agent_task_denied", "Child request is outside the task operation grant"
            )
        # File operations are scoped by both these paths and the existing daemon's
        # PathScope. Adaptive profiles require principal roots inside cwd at creation.
        if not self.full_access:
            if request.operation not in {
                "file.read",
                "file.list",
                "file.write",
                "file.mkdir",
                "file.move",
                "file.delete",
            }:
                raise BridgeError(
                    "agent_task_denied", "Operation requires an explicit full profile"
                )
            for key in ("path", "source", "destination"):
                if key in request.arguments:
                    path = Path(request.arguments[key])
                    allowed_roots = (
                        [self.cwd, *self.read_roots]
                        if request.operation in READ_OPERATIONS
                        else [self.cwd]
                    )
                    if not path.is_absolute() or not any(
                        path.resolve().is_relative_to(Path(root)) for root in allowed_roots
                    ):
                        raise BridgeError("agent_task_denied", "Child path is outside task cwd")
        previous = self._children.get(request.task_id)
        if previous is not None:
            raise BridgeError("agent_task_denied", "Child attempt already dispatched; read its ID")
        self._children[request.task_id] = digest(request.model_dump())

    async def authorize(self, connection, name, arguments, *, definition=None):
        async with self._lock:
            if name not in self.tools or self._calls >= self.max_calls:
                raise BridgeError("agent_task_denied", "Tool is outside the task call budget")
            if definition is None or not self.permits_tool(definition):
                raise BridgeError("agent_task_denied", "Tool lacks a current permitted contract")
            response = await connection.call_tool("task_get", {"task_id": self.task_id})
            if response.isError:
                raise BridgeError("agent_task_denied", "MCP task owner cannot be confirmed")
            self.validate_task(response.structuredContent)
            if self.team_scope is not None:
                response = await connection.call_tool(
                    "team_session_get", {"team_id": self.team_scope.team_id}
                )
                data = response.structuredContent
                slot = data.get("session") if isinstance(data, dict) else None
                if (
                    response.isError
                    or not isinstance(slot, dict)
                    or any(
                        slot.get(k) != value
                        for k, value in {
                            "team_id": self.team_scope.team_id,
                            "work_id": self.team_scope.work_id,
                            "session_id": self.team_scope.session_id,
                            "generation": self.team_scope.generation,
                            "principal": self.owner,
                            "agent": self.agent,
                            "cwd": self.cwd,
                            "state": "active",
                        }.items()
                    )
                ):
                    raise BridgeError(
                        "agent_task_denied", "Team session lease is no longer current"
                    )
            if name == "read_query" and self.operations:
                from kirabridge.read_query import ReadQuery

                try:
                    query = ReadQuery.model_validate((arguments or {}).get("query"))
                except ValueError:
                    raise BridgeError("agent_task_denied", "Invalid scoped read query") from None
                if (
                    set(arguments or {}) != {"query"}
                    or query.operation not in {"file.read", "file.list"}
                    or query.operation not in self.operations
                    or capability_for(query.operation) not in self.capabilities
                ):
                    raise BridgeError("agent_task_denied", "Read operation exceeds the task grant")
                path = Path(query.path) if query.path else None
                if (
                    path is None
                    or not path.is_absolute()
                    or not any(
                        path.resolve().is_relative_to(Path(root))
                        for root in [self.cwd, *self.read_roots]
                    )
                ):
                    raise BridgeError("agent_task_denied", "Read path exceeds the task scope")
            elif (
                name == "whiteboard_read"
                and set(arguments or {}) == {"thread_id", "entry_id"}
                and arguments["entry_id"] in self._entry_ids.get(arguments["thread_id"], set())
            ):
                self._entry_ids[arguments["thread_id"]].remove(arguments["entry_id"])
            elif (
                name == "td_get_thread"
                and type((arguments or {}).get("offset")) is int
                and self._note_pages.get(
                    digest({k: v for k, v in arguments.items() if k != "offset"})
                )
                == arguments["offset"]
            ):
                self._note_pages.pop(digest({k: v for k, v in arguments.items() if k != "offset"}))
                self._pending_reads.add(digest({"tool": name, "arguments": arguments}))
            elif name == "task_request":
                self._child(arguments)
            elif name in {"task_get", "task_events"} and self.operations:
                if (arguments or {}).get("task_id") not in self._children:
                    raise BridgeError(
                        "agent_task_denied", "Only task-owned child results may be read"
                    )
            else:
                actual = arguments or {}
                base = {
                    k: v for k, v in actual.items() if k not in {"result_digest", "result_offset"}
                }
                explicit = next(
                    (
                        g
                        for g in self.grants
                        if g.tool == name and digest(g.arguments) == digest(actual)
                    ),
                    None,
                )
                continuation = name == "td_command_query" and actual != base and explicit is None
                key = digest({"tool": name, "arguments": base if continuation else actual})
                grant = next(
                    (
                        g
                        for g in self.grants
                        if g.tool == name
                        and digest(g.arguments) == digest(base if continuation else actual)
                    ),
                    None,
                )
                if continuation:
                    known = self._pages.get(key)
                    if (
                        grant is None
                        or not definition.annotations
                        or definition.annotations.readOnlyHint is not True
                        or known is None
                        or actual.get("result_digest") != known[0]
                        or type(actual.get("result_offset")) is not int
                        or actual["result_offset"] != known[1]
                    ):
                        raise BridgeError(
                            "agent_task_denied",
                            "Read continuation is not bound to an observed response",
                        )
                    # Dispatch consumes this observed next page. UNKNOWN cannot
                    # authorize a replay; only its successful response seeds more.
                    self._pages.pop(key)
                else:
                    if grant is None or self._used.get(key, 0) >= grant.calls:
                        raise BridgeError(
                            "agent_task_denied", "Arguments exceed the exact call grant"
                        )
                    self._used[key] = self._used.get(key, 0) + 1
                if (
                    name in {"td_command_query", "whiteboard_read", "td_get_thread"}
                    and definition.annotations
                    and definition.annotations.readOnlyHint is True
                ):
                    self._pending_reads.add(digest({"tool": name, "arguments": actual}))
            # Consume before dispatch; UNKNOWN never restores the original grant.
            self._calls += 1

    def observe_result(self, name, arguments, response):
        """Authorize only the native next page of this task's successful exact read.

        This state is local to the same proxy connection. It is not a new grant
        ledger, cannot seed writes and cannot be supplied by a model response.
        """
        actual = arguments or {}
        call = digest({"tool": name, "arguments": actual})
        if call not in self._pending_reads:
            return
        self._pending_reads.discard(call)
        data = response.structuredContent
        if name == "whiteboard_read":
            if (
                not response.isError
                and isinstance(data, dict)
                and "error" not in data
                and data.get("thread_id") == actual.get("thread_id")
                and set(actual) == {"thread_id"}
                and isinstance(data.get("entries"), list)
                and len(data["entries"]) <= 10000
            ):
                self._entry_ids[actual["thread_id"]] = {
                    row["id"]
                    for row in data["entries"]
                    if isinstance(row, dict)
                    and isinstance(row.get("id"), str)
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", row["id"])
                }
            return
        if name == "td_get_thread":
            value = data.get("value") if isinstance(data, dict) else None
            if (
                not response.isError
                and isinstance(data, dict)
                and data.get("success") is True
                and isinstance(value, dict)
                and value.get("id") == actual.get("id")
                and type(value.get("offset")) is int
                and value["offset"] == actual.get("offset", 0)
                and type(value.get("next_offset")) is int
                and type(value.get("total_chars")) is int
                and value["offset"] < value["next_offset"] <= value["total_chars"]
                and value["next_offset"] <= value["offset"] + actual.get("max_chars", 100000)
                and value.get("truncated") is True
            ):
                self._note_pages[digest({k: v for k, v in actual.items() if k != "offset"})] = (
                    value["next_offset"]
                )
            return
        if response.isError or not isinstance(data, dict) or data.get("success") is not True:
            return
        page = data.get("value")
        if not isinstance(page, dict):
            return
        base = {k: v for k, v in actual.items() if k not in {"result_digest", "result_offset"}}
        if (
            page.get("schema") != "threaddesk.command-result.v1"
            or page.get("encoding") != "json-text-codepoint-pages"
            or page.get("workspace_id") != base.get("workspace_id")
            or page.get("command") != base.get("command")
            or page.get("catalog_revision") != base.get("catalog_revision")
            or type(page.get("offset")) is not int
            or page.get("offset") != actual.get("result_offset", 0)
            or not isinstance(page.get("result_page"), str)
            or not isinstance(page.get("result_digest"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", page["result_digest"])
        ):
            return
        key = digest({"tool": name, "arguments": base})
        next_offset, total = page.get("next_offset"), page.get("total")
        if (
            type(next_offset) is int
            and type(total) is int
            and page["offset"] + len(page["result_page"]) == next_offset
            and page["offset"] < next_offset <= total
        ):
            self._pages[key] = (page["result_digest"], next_offset, total)
        else:
            self._pages.pop(key, None)
