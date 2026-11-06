"""Synchronous, bounded reads; never dispatch work or attach interactive sessions."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input
from kirabridge.file_ranges import read_file_range
from kirabridge.filesystem_manager import PathScope
from kirabridge.permissions import state_exclusions


class ReadQuery(Input):
    operation: Literal[
        "file.read",
        "file.list",
        "terminal.output",
        "process.output",
        "session.catalog",
        "session.read",
        "platform.status",
        "task.observe",
        "native.read",
        "coordinator.status",
    ]
    path: str | None = Field(default=None, max_length=4096)
    task_id: str | None = Field(default=None, max_length=128)
    max_bytes: int = Field(default=32768, ge=1, le=524288)
    offset: int = Field(default=0, ge=0, le=2**63 - 1, strict=True)
    tail: bool = False
    encoding: Literal["utf-8", "base64"] = "utf-8"
    expected_identity: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    pane_id: str | None = Field(default=None, pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+)$")
    expected_pid: int | None = Field(default=None, gt=0)
    since: str = Field(default="", max_length=64, pattern=r"^$|[0-9a-f]{64}")
    check_helpers: bool = False
    limit: int = Field(default=100, ge=1, le=1000, strict=True)
    cursor: str = Field(default="", max_length=4096)
    stream: Literal["stdout", "stderr"] | None = None
    wait_seconds: float = Field(default=0.0, ge=0, le=18, allow_inf_nan=False)
    events_after: int = Field(default=0, ge=0, le=2**63 - 1, strict=True)
    native_operation: str | None = Field(default=None, max_length=64)
    arguments: dict | None = None

    @model_validator(mode="after")
    def selector(self):
        if self.operation == "coordinator.status":
            allowed = {"operation", "max_bytes"}
            if (
                any(
                    getattr(self, field) != type(self).model_fields[field].get_default()
                    for field in self.model_fields_set - allowed
                )
                or self.max_bytes > 65536
            ):
                raise ValueError("Coordinator status accepts only its bounded read budget")
            return self
        if self.operation == "native.read":
            from kirabridge.native_queries import native_arguments

            # Reject unrelated selectors rather than ignoring them. Use the
            # existing operation's typed schema for the inner arguments.
            allowed = {"operation", "native_operation", "arguments", "max_bytes"}
            if any(
                getattr(self, field) != type(self).model_fields[field].get_default()
                for field in self.model_fields_set - allowed
            ):
                raise ValueError("Native reads accept only their operation, arguments and budget")
            native_arguments(self.native_operation, self.arguments, self.max_bytes)
            return self
        if self.native_operation is not None or self.arguments is not None:
            raise ValueError("Native selectors require native.read")
        if self.max_bytes > 65536:
            raise ValueError("Non-native reads are limited to 65536 bytes")
        if (self.wait_seconds or self.events_after) and self.operation != "task.observe":
            raise ValueError("task observation selectors require task.observe")
        if self.check_helpers and self.operation != "platform.status":
            raise ValueError("helper permission diagnostics require platform.status")
        if self.encoding != "utf-8" and self.operation not in {"file.read", "process.output"}:
            raise ValueError("range encoding requires file.read or process.output")
        if self.expected_identity is not None and self.operation not in {
            "file.read",
            "file.list",
            "process.output",
        }:
            raise ValueError("identity requires a file, directory or process range")
        if (self.cursor or self.limit != 100) and self.operation != "file.list":
            raise ValueError("directory selectors require file.list")
        if self.stream is not None and self.operation != "process.output":
            raise ValueError("stream selector requires process.output")
        if self.operation.startswith("session."):
            if self.path or self.task_id or self.offset or self.tail:
                raise ValueError(
                    "session queries require exact catalog handles, not paths or tasks"
                )
            if self.operation == "session.read":
                if not self.pane_id or self.expected_pid is None:
                    raise ValueError("session.read requires pane_id and expected_pid")
            elif self.pane_id is not None or self.expected_pid is not None:
                raise ValueError("session.catalog does not accept a target")
            elif self.since:
                raise ValueError("since is only valid for session.read")
        elif self.pane_id is not None or self.expected_pid is not None:
            raise ValueError("terminal handles are only valid for session.read")
        elif self.operation == "platform.status":
            if self.path or self.task_id or self.offset or self.tail:
                raise ValueError("platform.status does not accept file/task selectors")
        elif self.operation == "task.observe":
            if not self.task_id or self.path is not None or self.offset or self.tail:
                raise ValueError("task.observe requires only an existing task_id and wait/cursor")
        elif self.operation == "terminal.output":
            if not self.task_id or self.path is not None or self.offset or self.tail:
                raise ValueError("terminal.output requires only task_id and max_bytes")
        elif self.operation == "process.output":
            if not self.task_id or self.path is not None or self.tail:
                raise ValueError("process.output requires task_id and forward range selectors")
        elif not self.path or self.task_id is not None:
            raise ValueError("file reads require path, not task_id")
        if self.operation == "file.list" and (self.offset or self.tail):
            raise ValueError("directory reads do not accept byte selectors")
        if self.tail and self.offset:
            raise ValueError("use either tail or offset")
        if self.since and self.operation != "session.read":
            raise ValueError("since is only valid for session.read")
        return self


async def read_query_async(bridge, principal: str, query: ReadQuery) -> dict:
    """Existing dictionary-shaped tool also works with cached client tool lists."""
    if query.operation == "coordinator.status":
        import json

        from kirabridge.autonext.status import coordinator_status

        value = coordinator_status(bridge, principal)
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > query.max_bytes:
            raise BridgeError("read_result_limit", "Coordinator status exceeds read budget")
        return value
    if query.operation == "native.read":
        return await bridge.native_queries.execute(
            principal, query.native_operation, query.arguments, max_bytes=query.max_bytes
        )
    if query.operation == "task.observe":
        from kirabridge.task_observation import observe_task

        return await observe_task(
            bridge, principal, query.task_id, query.wait_seconds, query.events_after
        )
    if query.operation == "platform.status":
        return await bridge.platform_status(principal, check_helpers=query.check_helpers)
    if query.operation == "session.catalog":
        return {
            "operation": query.operation,
            **await bridge.terminal_queries.execute(principal, query.operation, {}),
        }
    if query.operation == "session.read":
        result = await bridge.terminal_queries.execute(
            principal,
            query.operation,
            {
                "pane_id": query.pane_id,
                "expected_pid": query.expected_pid,
                "max_bytes": query.max_bytes,
                **({"since": query.since} if query.since else {}),
            },
        )
        return {"operation": query.operation, **result}
    return read_query(bridge, principal, query)


def read_query(bridge, principal: str, query: ReadQuery) -> dict:
    capability = (
        "process.inspect"
        if query.operation in {"terminal.output", "process.output"}
        else query.operation
    )
    policy = bridge.security.principal(principal, capability)
    if query.operation in {"file.read", "file.list"}:
        platform_operation = bridge.platform_operation(query.operation)
        if platform_operation is not None:
            bridge.macos.require(platform_operation)
    if query.operation in {"terminal.output", "process.output"}:
        task = bridge.task(principal, query.task_id)
        if task["operation"] not in {
            "terminal.execute",
            "terminal.visible",
            "admin.execute",
            "agent.execute",
            "system.report",
        }:
            raise BridgeError("invalid_operation", "Task has no terminal output")
        if query.operation == "process.output":
            return {
                "operation": query.operation,
                "state": task["state"],
                **bridge.terminal.read_output(
                    principal,
                    query.task_id,
                    query.stream or "stdout",
                    offset=query.offset,
                    max_bytes=query.max_bytes,
                    encoding=query.encoding,
                    expected_identity=query.expected_identity,
                ),
            }
        try:
            source = bridge.terminal.inspect(principal, query.task_id)
            origin = "managed_terminal_buffer"
        except BridgeError as exc:
            if exc.code != "not_found":
                raise
            source = task.get("result") or {}
            origin = "persisted_task_result"
        remaining, output = query.max_bytes, {}
        truncated = bool(
            source.get("truncated")
            or source.get("output_truncated")
            or (source.get("output_ref") or {}).get("truncated")
        )
        keys = ("stdout", "stderr") + (("terminal_output",) if "terminal_output" in source else ())
        for key in keys:
            raw = str(source.get(key, "")).encode("utf-8")
            # A clipped multibyte character must not expand the UTF-8 byte budget.
            output[key] = raw[:remaining].decode("utf-8", "ignore")
            truncated |= len(raw) > remaining
            remaining -= min(remaining, len(raw))
        return {
            "operation": query.operation,
            "task_id": query.task_id,
            "state": task["state"],
            "source": origin,
            **output,
            "bytes": query.max_bytes - remaining,
            "truncated": truncated,
            "output_available": source.get("output_available", any(key in source for key in keys)),
            "output_status": source.get("output_status", "available"),
            **(
                {"output_scope": source.get("output_scope", "captured visible screen")}
                if "terminal_output" in source
                else {}
            ),
            "exit_code": source.get("exit_code"),
            "scope": "owned Bridge task only; no external terminal attachment",
        }
    scope = PathScope(
        policy.roots + policy.read_roots, excluded=state_exclusions(bridge.config, policy)
    )
    if query.operation == "file.list":
        result = bridge.filesystem.list(
            scope,
            query.path,
            limit=query.limit,
            cursor=query.cursor,
            expected_identity=query.expected_identity,
        )
        return {
            "operation": query.operation,
            "path": query.path,
            **result,
        }
    return {
        "operation": query.operation,
        "path": query.path,
        **read_file_range(
            scope,
            query.path,
            query.max_bytes,
            offset=query.offset,
            tail=query.tail,
            encoding=query.encoding,
            expected_identity=query.expected_identity,
        ),
    }
