"""Bounded live logs and status for every CLI and agent this bridge runs.

One source per task: child stdout/stderr and adapter progress events are
appended from the central execution funnel, so a newly configured CLI or agent
adapter is covered without per-adapter logging code. Entries live in fixed
in-memory ring buffers with explicit cursors and drop counters. The hub is
observation only: it never attaches to a foreign process, reads unrelated
files, replays work, persists prompts or changes a task's state. Recording
failure is swallowed and can never fail the task it observes.

Durable evidence stays in the existing task records, audit trail and
hash-referenced output stores; this module is not a second audit source.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input

CHANNELS = ("stdout", "stderr", "events")
DEFAULT_MAX_SOURCES = 64
DEFAULT_MAX_LINES = 400
DEFAULT_MAX_BYTES = 131072
DEFAULT_MAX_LINE_CHARS = 4096
# Execution operations that can host a CLI or agent. Reads, clipboard or policy
# queries never create a source, so routine polling cannot exhaust the registry.
TRACKED_OPERATIONS = frozenset(
    {
        "terminal.execute",
        "terminal.visible",
        "admin.execute",
        "agent.execute",
        "handoff.start",
        "system.report",
    }
)


class LiveLogsInput(Input):
    """A status list, or one incremental cursor read on an owned source."""

    source_id: str | None = Field(default=None, min_length=1, max_length=128)
    cursor: int = Field(default=0, ge=0, le=2**63 - 1)
    max_lines: int = Field(default=200, ge=1, le=1000)
    max_bytes: int = Field(default=65536, ge=256, le=262144)
    channels: list[Literal["stdout", "stderr", "events"]] | None = Field(
        default=None, min_length=1, max_length=3
    )


@dataclass
class LogSource:
    source_id: str
    principal: str
    operation: str
    agent: str | None = None
    transport: str | None = None
    cwd: str | None = None
    pid: int | None = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    state: str = "running"
    exit_code: int | None = None
    error: str | None = None
    entries: deque = field(default_factory=deque)
    next_seq: int = 1
    dropped: int = 0
    lines: int = 0
    bytes: int = 0


class LiveLogHub:
    def __init__(self, config=None):
        self.max_sources = getattr(config, "max_sources", DEFAULT_MAX_SOURCES)
        self.max_lines = getattr(config, "max_lines_per_source", DEFAULT_MAX_LINES)
        self.max_bytes = getattr(config, "max_bytes_per_source", DEFAULT_MAX_BYTES)
        self.max_line_chars = getattr(config, "max_line_chars", DEFAULT_MAX_LINE_CHARS)
        self.enabled = bool(getattr(config, "enabled", True))
        self.sources: dict[str, LogSource] = {}
        self.dropped_sources = 0
        self.principal_conflicts = 0

    # -- registration -----------------------------------------------------

    def tracks(self, operation: str) -> bool:
        return self.enabled and operation in TRACKED_OPERATIONS

    def open(
        self,
        source_id: str,
        principal: str,
        *,
        operation: str | None = None,
        agent: str | None = None,
        transport: str | None = None,
        cwd: str | None = None,
        pid: int | None = None,
    ):
        """Register or enrich one owned source; never displaces a live source."""
        if not self.enabled or not isinstance(source_id, str) or not source_id:
            return None
        source = self.sources.get(source_id)
        if source is not None:
            if source.principal != principal:
                # A colliding task id from another principal must not observe or
                # overwrite this source.
                self.principal_conflicts += 1
                return None
            source.operation = operation or source.operation
            source.agent = agent or source.agent
            source.transport = transport or source.transport
            source.cwd = cwd or source.cwd
            source.pid = pid or source.pid
            source.updated = time.time()
            return source
        if len(self.sources) >= self.max_sources and not self._evict_closed():
            self.dropped_sources += 1
            return None
        source = LogSource(
            source_id=source_id,
            principal=principal,
            operation=operation or "process",
            agent=agent,
            transport=transport,
            cwd=cwd,
            pid=pid,
        )
        self.sources[source_id] = source
        return source

    def _evict_closed(self) -> bool:
        closed = [item for item in self.sources.values() if item.state != "running"]
        if not closed:
            return False
        oldest = min(closed, key=lambda item: (item.updated, item.created))
        del self.sources[oldest.source_id]
        return True

    # -- recording --------------------------------------------------------

    def append(self, source_id: str, principal: str, channel: str, value) -> None:
        """Record already-received output. Observation never raises into a task."""
        if not self.enabled or channel not in CHANNELS:
            return
        try:
            if isinstance(value, bytes):
                text = value.decode("utf-8", "replace")
            elif isinstance(value, str):
                text = value
            else:
                return
            source = self.sources.get(source_id)
            if source is None:
                source = self.open(source_id, principal)
            if source is None or source.principal != principal:
                return
            now = time.time()
            for line in text.splitlines():
                if not line:
                    continue
                self._entry(source, channel, line, now)
            source.updated = now
        except Exception:
            # A broken observer must never change the observed task's outcome.
            return

    def feed(self, source_id: str, principal: str, evidence) -> None:
        """Record one adapter/agent progress event as an `events` line."""
        if not isinstance(evidence, dict):
            return
        try:
            line = json.dumps(
                evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
            )
        except (TypeError, ValueError):
            return
        self.append(source_id, principal, "events", line)

    def _entry(self, source: LogSource, channel: str, line: str, now: float) -> None:
        if len(line) > self.max_line_chars:
            line = line[: self.max_line_chars] + f"…[+{len(line) - self.max_line_chars} chars]"
        size = len(line.encode("utf-8", "ignore"))
        source.entries.append((source.next_seq, channel, now, line, size))
        source.next_seq += 1
        source.lines += 1
        source.bytes += size
        while source.entries and (
            len(source.entries) > self.max_lines or source.bytes > self.max_bytes
        ):
            _seq, _channel, _at, _text, removed = source.entries.popleft()
            source.bytes -= removed
            source.dropped += 1

    def close(self, source_id: str, *, exit_code: int | None = None, error: str | None = None):
        source = self.sources.get(source_id)
        if source is None:
            return None
        if exit_code is not None:
            source.exit_code = exit_code
        if error is not None and source.error is None:
            source.error = error
        if source.state == "running":
            source.state = "failed" if source.error else "closed"
        source.updated = time.time()
        return source

    # -- reading ----------------------------------------------------------

    def _owned(self, principal: str, source_id: str) -> LogSource:
        source = self.sources.get(source_id)
        if source is None or source.principal != principal:
            raise BridgeError(
                "logs_unavailable", "No live log source is available for this principal"
            )
        return source

    def status(self, principal: str) -> dict:
        rows = [
            self._describe(source)
            for source in self.sources.values()
            if source.principal == principal
        ]
        rows.sort(key=lambda row: row["updated"], reverse=True)
        return {
            "sources": rows,
            "count": len(rows),
            "limits": self.limits(),
            "dropped_sources": self.dropped_sources,
            "scope": "in-memory live observation; not durable audit; text is never "
            "proof of successful execution",
        }

    def read(
        self,
        principal: str,
        source_id: str,
        *,
        cursor: int = 0,
        max_lines: int = 200,
        max_bytes: int = 65536,
        channels=None,
    ) -> dict:
        source = self._owned(principal, source_id)
        selected = [channel for channel in (channels or CHANNELS) if channel in CHANNELS]
        entries, used, next_cursor = [], 0, cursor
        for seq, channel, at, text, size in source.entries:
            if seq <= cursor or channel not in selected:
                continue
            if entries and (len(entries) >= max_lines or used + size > max_bytes):
                break
            entries.append({"seq": seq, "channel": channel, "at": at, "text": text})
            used += size
            next_cursor = seq
        earliest = source.entries[0][0] if source.entries else source.next_seq
        reset = bool(cursor < earliest - 1)
        remaining = sum(
            1
            for seq, channel, _at, _text, _size in source.entries
            if seq > next_cursor and channel in selected
        )
        return {
            "source_id": source_id,
            "state": source.state,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "earliest_cursor": earliest,
            "reset": reset,
            "dropped": source.dropped,
            "entries": entries,
            "lines_returned": len(entries),
            "bytes_returned": used,
            "lines_remaining": remaining,
            "bytes_available": source.bytes,
            "limits": self.limits(),
            "scope": "bounded live ring buffer; read again with next_cursor; a reset "
            "means older lines were dropped",
        }

    def summary(self, principal: str) -> dict:
        rows = [source for source in self.sources.values() if source.principal == principal]
        by_state: dict[str, int] = {}
        for source in rows:
            by_state[source.state] = by_state.get(source.state, 0) + 1
        return {
            "count": len(rows),
            "by_state": by_state,
            "running": sorted(source.source_id for source in rows if source.state == "running"),
            "dropped_sources": self.dropped_sources,
            "read_operation": "logs.live",
            "scope": "metadata only; call logs.live with a source_id for bounded text",
        }

    def _describe(self, source: LogSource) -> dict:
        channels = {channel: {"lines": 0, "bytes": 0} for channel in CHANNELS}
        for _seq, channel, _at, _text, size in source.entries:
            channels[channel]["lines"] += 1
            channels[channel]["bytes"] += size
        return {
            "source_id": source.source_id,
            "operation": source.operation,
            "agent": source.agent,
            "transport": source.transport,
            "cwd": source.cwd,
            "pid": source.pid,
            "state": source.state,
            "exit_code": source.exit_code,
            "error": source.error,
            "created": source.created,
            "updated": source.updated,
            "lines": len(source.entries),
            "bytes": source.bytes,
            "dropped": source.dropped,
            "channels": channels,
            "earliest_cursor": source.entries[0][0] if source.entries else source.next_seq,
            "next_cursor": source.next_seq - 1,
        }

    def limits(self) -> dict:
        return {
            "max_sources": self.max_sources,
            "max_lines_per_source": self.max_lines,
            "max_bytes_per_source": self.max_bytes,
            "max_line_chars": self.max_line_chars,
            "enabled": self.enabled,
            "durable": False,
        }
