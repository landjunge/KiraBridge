"""Synthetic local-only task observation benchmark; never touches the installed service.

Run with PYTHONPATH=src python tests/bench_task_observation.py
--label before --output /tmp/result.json.
All bridge state/output fixtures live in a TemporaryDirectory. No worker, native
helper, MCP network, user terminal or clipboard is started.
"""

import argparse
import asyncio
import importlib.util
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import State, TaskRequest
from kirabridge.mcp_gateway.server import create_server
from kirabridge.task_observation import observe_submitted_task, observe_task


def summary(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


async def measure(label, rounds=30, *, observer_source=None, poll_only=False):
    records = []
    observe = observe_task
    submitted_observer = observe_submitted_task
    if observer_source is not None:
        spec = importlib.util.spec_from_file_location("task_observation_benchmark", observer_source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observe, submitted_observer = module.observe_task, module.observe_submitted_task
    with tempfile.TemporaryDirectory(prefix="kirabridge-task-observation-") as directory:
        directory = str(Path(directory).resolve())
        config = Config(
            data_dir=directory + "/state",
            principals={
                "chatgpt": PrincipalConfig(
                    approval_mode="automatic",
                    capabilities=[
                        "task.read",
                        "terminal.execute",
                        "file.write",
                        "session.input",
                        "session.inspect",
                    ],
                    roots=[directory],
                    executables=["/bin/echo"],
                )
            },
        )
        config.visible_handoffs.enabled = False
        bridge = Bridge(config)
        try:
            server = create_server(bridge, principal="chatgpt")
            task_get = server._tool_manager.get_tool("task_get").fn
            original_resolve = bridge.outputs.resolve_result
            count, resolver_ms = 0, 0.0

            def resolve(principal, value):
                nonlocal count, resolver_ms
                active = isinstance(value, dict) and value.get("output_codec") == 1
                started = time.perf_counter_ns()
                result = original_resolve(principal, value)
                if active:
                    count += 1
                    resolver_ms += (time.perf_counter_ns() - started) / 1_000_000
                return result

            bridge.outputs.resolve_result = resolve
            for size in () if poll_only else (32768, 4 * 1024 * 1024):
                task_id = f"synthetic-{size}"
                request = TaskRequest(
                    task_id=task_id,
                    idempotency_key=task_id,
                    operation="terminal.execute",
                    arguments={"argv": ["/bin/echo", "synthetic"], "cwd": directory},
                )
                bridge.prepare("chatgpt", request)
                bridge.store.claim_exact("synthetic-fixture", 30, task_id)
                bridge.store.transition(
                    task_id, State.RUNNING, {"synthetic": True}, owner="synthetic-fixture"
                )
                bridge.store.transition(
                    task_id,
                    State.COMPLETED,
                    {"synthetic": True},
                    result={"stdout": "x" * size, "stderr": "", "exit_code": 0},
                    owner="synthetic-fixture",
                )
                stored = bridge.store.get(task_id, "chatgpt", resolve_output=False)
                assert stored["result"]["output_codec"] == 1

                async def get(task_id=task_id):
                    return await task_get(task_id, None)

                async def observation(task_id=task_id):
                    return (await observe(bridge, "chatgpt", task_id))["task"]

                async def submitted(stored=stored):
                    return await submitted_observer(
                        bridge,
                        "chatgpt",
                        stored,
                        wait_seconds=2,
                        deadline=asyncio.get_running_loop().time() + 18,
                    )

                for name, action in (
                    ("chatgpt_task_get_completed", get),
                    ("task_observe_completed", observation),
                    ("submitted_completed_record", submitted),
                ):
                    durations, counts, resolver_times = [], [], []
                    for _ in range(rounds):
                        count, resolver_ms = 0, 0.0
                        started = time.perf_counter_ns()
                        result = await action()
                        durations.append((time.perf_counter_ns() - started) / 1_000_000)
                        counts.append(count)
                        resolver_times.append(resolver_ms)
                        assert result["state"] == "completed"
                        assert len(result["result"]["stdout"]) == size
                        assert result["result"]["output_available"]
                    records.append(
                        {
                            "path": name,
                            "payload_bytes": size,
                            "timings": summary(durations),
                            "output_resolutions_per_call": sorted(set(counts)),
                            "resolver_timings": summary(resolver_times),
                        }
                    )

            request = TaskRequest(
                task_id="synthetic-poll",
                idempotency_key="synthetic-poll",
                operation="file.write",
                arguments={"path": directory + "/never-written", "text": "synthetic"},
            )
            bridge.prepare("chatgpt", request)
            for completion_delay_ms in (0, 5, 16, 35, 60):
                durations, cpu_times, query_counts, total_queries = [], [], [], []
                for _ in range(rounds):
                    bridge.store.db.execute(
                        "UPDATE tasks SET state='running' WHERE id=?", (request.task_id,)
                    )

                    async def completed_after_delay(completion_delay_ms=completion_delay_ms):
                        await asyncio.sleep(completion_delay_ms / 1000)
                        bridge.store.db.execute(
                            "UPDATE tasks SET state='completed' WHERE id=?", (request.task_id,)
                        )

                    statements = []
                    bridge.store.db.set_trace_callback(statements.append)
                    completion = asyncio.create_task(completed_after_delay())
                    started = time.perf_counter_ns()
                    cpu_started = time.process_time_ns()
                    result = await observe(bridge, "chatgpt", request.task_id, wait_seconds=1)
                    cpu_times.append((time.process_time_ns() - cpu_started) / 1_000_000)
                    durations.append((time.perf_counter_ns() - started) / 1_000_000)
                    await completion
                    bridge.store.db.set_trace_callback(None)
                    query_counts.append(
                        sum(s.startswith("SELECT state FROM tasks") for s in statements)
                    )
                    total_queries.append(len(statements))
                    assert result["complete"] and not result["pending"]
                records.append(
                    {
                        "path": "completion_after_delay",
                        "completion_delay_ms": completion_delay_ms,
                        "timings": summary(durations),
                        "cpu_timings": summary(cpu_times),
                        "state_only_queries_per_call": sorted(set(query_counts)),
                        "all_sql_statements_per_call": sorted(set(total_queries)),
                    }
                )
        finally:
            bridge.store.close()
    return {
        "label": label,
        "scope": "synthetic temporary SQLite/OutputHistory; direct handler, no wire serialization",
        "cache": "warm same-process SQLite/OS; no result cache",
        "percentiles": "P50 median, P95 nearest rank",
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--observer-source", type=Path)
    parser.add_argument("--poll-only", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        measure(args.label, observer_source=args.observer_source, poll_only=args.poll_only)
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
