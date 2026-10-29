"""Synchronous, bounded reads; never dispatch work or attach interactive sessions."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input
from kirabridge.file_ranges import read_file_range
from kirabridge.filesystem_manager import PathScope
from kirabridge.permissions import state_exclusions


class ReadQuery(Input):
    operation: Literal[
        "file.read", "file.list", "terminal.output", "session.catalog", "session.read"
    ]
    path: str | None = Field(default=None, max_length=4096)
    task_id: str | None = Field(default=None, max_length=128)
    max_bytes: int = Field(default=32768, ge=1, le=65536)
    offset: int = Field(default=0, ge=0, le=2**63 - 1, strict=True)
    tail: bool = False
    encoding: Literal["utf-8", "base64"] = "utf-8"
    expected_identity: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    pane_id: str | None = Field(default=None, pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+)$")
    expected_pid: int | None = Field(default=None, gt=0)
    since: str = Field(default="", max_length=64, pattern=r"^$|[0-9a-f]{64}")

    @model_validator(mode="after")
    def selector(self):
        if self.operation != "file.read" and (
            self.encoding != "utf-8" or self.expected_identity is not None
        ):
            raise ValueError("file range encoding and identity require file.read")
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
        elif self.operation == "terminal.output":
            if not self.task_id or self.path is not None or self.offset or self.tail:
                raise ValueError("terminal.output requires only task_id and max_bytes")
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
    capability = "process.inspect" if query.operation == "terminal.output" else query.operation
    policy = bridge.security.principal(principal, capability)
    if query.operation == "terminal.output":
        task = bridge.task(principal, query.task_id)
        if task["operation"] not in {
            "terminal.execute",
            "terminal.visible",
            "admin.execute",
            "agent.execute",
        }:
            raise BridgeError("invalid_operation", "Task has no terminal output")
        try:
            source = bridge.terminal.inspect(principal, query.task_id)
            origin = "managed_terminal_buffer"
        except BridgeError as exc:
            if exc.code != "not_found":
                raise
            source = task.get("result") or {}
            origin = "persisted_task_result"
        remaining, output, truncated = query.max_bytes, {}, False
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
        result = bridge.filesystem.list(scope, query.path)
        entries = result["entries"][:100]
        return {
            "operation": query.operation,
            "path": query.path,
            "entries": entries,
            "truncated": result["truncated"] or len(result["entries"]) > 100,
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
