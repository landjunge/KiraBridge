"""ThreadDesk write latency under concurrent large reads, through the real MCP gateway.

Runs an in-process Bridge with its own data directory and port, and the configured
ThreadDesk peer (``threaddesk.ui.mcp_stdio``) on an explicit COPY of a workspace.
Every write carries a unique marker; afterwards each one is read back and counted.
An unclear reply is reconciled with the same operation_id, never resent with a new one.

    python scripts/benchmark_threaddesk_writes.py --workspace COPY --threaddesk-source SRC \
        --note-threads a,b --board-threads c,d --big-thread e --big-board f
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.mcp_gateway.server import create_server
from kirabridge.mcp_gateway.timing import TIMING_KEY
from kirabridge.whiteboard_read import read_whiteboard

PRINCIPAL = "latency"
CAPABILITIES = ["threaddesk.read", "threaddesk.manage", "threaddesk.knowledge"]
CAPABILITIES += ["threaddesk.dynamic", "task.read"]


def bridge_config(workspace, source, state, port, timeout):
    config = Config(
        data_dir=str(state),
        port=port,
        concurrency=1,
        principals={
            PRINCIPAL: PrincipalConfig(
                capabilities=CAPABILITIES,
                roots=[str(state)],
                approval_mode="automatic",
                permission_level="full",
            )
        },
    )
    settings = config.threaddesk
    settings.enabled, settings.workspace, settings.storage = True, str(workspace), "json"
    settings.command, settings.args = sys.executable, ["-m", "threaddesk.ui.mcp_stdio"]
    settings.source_root, settings.timeout = str(source), timeout
    settings.dynamic_read_proxy = settings.dynamic_tool_proxy = True
    return config


def payload(result):
    if result.structuredContent is not None:
        value = result.structuredContent
        return value.get("result", value) if set(value) == {"result"} else value
    return json.loads(result.content[0].text)


def percentiles(values):
    if not values:
        return {}
    ordered = sorted(values)

    def at(share):
        return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)

    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 1),
        "p90": at(0.9),
        "p99": at(0.99),
        "max": round(ordered[-1], 1),
    }


async def run(args):
    workspace, source = Path(args.workspace).resolve(), Path(args.threaddesk_source).resolve()
    with tempfile.TemporaryDirectory(prefix="kb-td-latency-") as state:
        config = bridge_config(workspace, source, Path(state).resolve(), args.port, args.timeout)
        async with Bridge(config) as bridge:
            server = create_server(bridge, transport="stdio", principal=PRINCIPAL)
            async with create_connected_server_and_client_session(server._mcp_server) as client:
                return await workload(args, bridge, client, workspace)


async def workload(args, bridge, client, workspace):
    rows, reads, run_id = [], [], uuid.uuid4().hex[:8]
    done = asyncio.Event()

    async def tool(name, arguments):
        sent = time.time_ns()
        result = await client.call_tool(name, arguments)
        received = time.time_ns()
        timing = (result.meta or {}).get(TIMING_KEY, {}).get("daemon", {})
        return payload(result), sent, received, timing

    async def dynamic(name, arguments, operation_id=None):
        values = {"name": name, "arguments": arguments}
        if operation_id:
            values["operation_id"] = operation_id
        return await tool("threaddesk_dynamic_call", values)

    async def note_writer(thread_id):
        value, *_ = await dynamic("get_thread", {"id": thread_id})
        revision = value["value"]["revision"]
        for index in range(args.writes):
            marker = f"latency-{run_id}-{thread_id}-{index}"
            operation_id = marker.replace("latency-", "lat_")
            arguments = {
                "operation_id": operation_id,
                "action": "set_note",
                "id": thread_id,
                "expected_revision": revision,
                "data": {"append": True, "text": f"\n{marker}"},
            }
            value, sent, received, timing = await dynamic("thread_manage", arguments, operation_id)
            unclear, errors = 0, []
            while "task" not in value and len(errors) < 3:
                # Rejected before a durable task existed; the same operation_id stays safe.
                errors.append((value.get("error") or {}).get("code", "error"))
                await asyncio.sleep(1)
                value, _, received, timing = await dynamic("thread_manage", arguments, operation_id)
            if "task" not in value:
                raise RuntimeError(f"Write was not accepted: {json.dumps(value)[:400]}")
            while value["task"]["state"] not in {"completed", "failed", "unknown"}:
                # Unclear reply: reconcile the same durable task, never a new write.
                unclear += 1
                value, _, received, timing = await dynamic("thread_manage", arguments, operation_id)
            task = bridge.store.get(value["task"]["id"], PRINCIPAL)
            task["started"] = task["started"] or task["created"]
            task["finished"] = task["finished"] or time.time()
            receipt = value.get("value") or {}
            receipt = receipt.get("receipt", receipt) if receipt.get("reconciled") else receipt
            if isinstance(receipt.get("revision"), int):
                revision = receipt["revision"]
            rows.append(
                {
                    "kind": "thread_manage.set_note",
                    "thread_id": thread_id,
                    "marker": marker,
                    "state": task["state"],
                    "unclear_replies": unclear,
                    "rejected_before_task": errors,
                    "accept_ms": (task["started"] * 1e9 - sent) / 1e6,
                    "execute_store_ms": (task["finished"] - task["started"]) * 1000,
                    "receipt_ms": (received - task["finished"] * 1e9) / 1e6,
                    "total_ms": (received - sent) / 1e6,
                    "trace_id": timing.get("trace_id"),
                }
            )

    async def board_writer(thread_id):
        for index in range(args.writes):
            marker = f"latency-{run_id}-{thread_id}-{index}"
            values = {
                "thread_id": thread_id,
                "entry_type": "note",
                "content": marker,
                "actor": "latency-probe",
                "actor_type": "claude",
                "external_key": marker,
            }
            value, sent, received, timing = await tool("whiteboard_append", values)
            if "error" in value:
                # Unclear: the same external_key returns the stored entry, never a second one.
                value, sent, received, timing = await tool("whiteboard_append", values)
            started = timing.get("handler_started_unix_ns", sent)
            ready = timing.get("result_ready_unix_ns", received)
            rows.append(
                {
                    "kind": "whiteboard_append",
                    "thread_id": thread_id,
                    "marker": marker,
                    "entry_id": value.get("id"),
                    "state": "completed" if value.get("id") else "failed",
                    "accept_ms": (started - sent) / 1e6,
                    "execute_store_ms": (ready - started) / 1e6,
                    "receipt_ms": (received - ready) / 1e6,
                    "total_ms": (received - sent) / 1e6,
                }
            )

    async def reader(name, arguments, dynamic_read):
        while not done.is_set():
            started = time.perf_counter()
            if dynamic_read:
                await dynamic(name, arguments)
            else:
                await tool(name, arguments)
            reads.append({"tool": name, "ms": (time.perf_counter() - started) * 1000})

    readers = [
        asyncio.create_task(reader("get_thread", {"id": args.big_thread}, True)),
        asyncio.create_task(reader("whiteboard_read", {"thread_id": args.big_board}, False)),
    ]
    writers = [note_writer(item) for item in args.note_threads]
    writers += [board_writer(item) for item in args.board_threads]
    started = time.perf_counter()
    await asyncio.gather(*writers)
    elapsed = time.perf_counter() - started
    done.set()
    await asyncio.gather(*readers)
    return report(args, rows, reads, elapsed, workspace, run_id, await readback(rows, dynamic))


async def readback(rows, dynamic):
    notes = {}
    for thread_id in {row["thread_id"] for row in rows if row["kind"].startswith("thread")}:
        # Windowed reads: follow next_offset until the whole note has been read back.
        text, offset = "", 0
        while offset is not None:
            value, *_ = await dynamic("get_thread", {"id": thread_id, "offset": offset})
            text += value["value"].get("notes") or ""
            offset = value["value"].get("next_offset")
        notes[thread_id] = text
    return notes


def report(args, rows, reads, elapsed, workspace, run_id, notes):
    copies, missing = 0, 0
    for row in rows:
        if row["kind"].startswith("thread"):
            count = notes[row["thread_id"]].count(row["marker"])
        else:
            board = read_whiteboard(str(workspace), row["thread_id"], include_content=True)
            count, offset = 0, 0
            while True:
                count += sum(
                    entry["content"] == row["marker"] for entry in board.get("entries", [])
                )
                offset = board.get("next_offset")
                if offset is None:
                    break
                board = read_whiteboard(
                    str(workspace), row["thread_id"], include_content=True, offset=offset
                )
        missing += count == 0
        copies += max(0, count - 1)
    summary = {
        "run_id": run_id,
        "writes": len(rows),
        "elapsed_s": round(elapsed, 2),
        "states": {state: sum(r["state"] == state for r in rows) for state in {"completed"}}
        | {"other": sum(r["state"] != "completed" for r in rows)},
        "unclear_replies": sum(r.get("unclear_replies", 0) for r in rows),
        "rejected_before_task": sum(len(r.get("rejected_before_task", [])) for r in rows),
        "duplicates": copies,
        "missing_after_readback": missing,
        "concurrent_large_reads": len(reads),
        "phases": {
            kind: {
                phase: percentiles([r[phase] for r in rows if r["kind"] == kind])
                for phase in ("accept_ms", "execute_store_ms", "receipt_ms", "total_ms")
            }
            for kind in sorted({r["kind"] for r in rows})
        },
        "reads_ms": {
            name: percentiles([r["ms"] for r in reads if r["tool"] == name])
            for name in sorted({r["tool"] for r in reads})
        },
    }
    if args.rows:
        summary["rows"] = rows
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, help="A COPY of a ThreadDesk workspace")
    parser.add_argument("--threaddesk-source", required=True)
    parser.add_argument("--note-threads", type=lambda v: v.split(","), required=True)
    parser.add_argument("--board-threads", type=lambda v: v.split(","), required=True)
    parser.add_argument("--big-thread", required=True)
    parser.add_argument("--big-board", required=True)
    parser.add_argument("--writes", type=int, default=10, help="Writes per writer")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--port", type=int, default=18799, help="Isolated, never bound here")
    parser.add_argument("--rows", action="store_true")
    summary = asyncio.run(run(parser.parse_args(argv)))
    print(json.dumps(summary, indent=2))
    return 0 if not summary["duplicates"] and not summary["missing_after_readback"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
