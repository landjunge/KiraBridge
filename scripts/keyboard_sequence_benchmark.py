"""Same-workload native key benchmark; effects are supplied by the owned harness."""

from __future__ import annotations

import asyncio
import hashlib
import math
import statistics
import time

TEXT = "Stern am"
EXPECTED_SHA256 = hashlib.sha256(TEXT.encode()).hexdigest()


def summary(values):
    """P95 nearest rank (ceil(.95*n)); include n and raw samples for small runs."""
    if not values:
        return {"count": 0, "total_ms": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "total_ms": sum(values),
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(0.95 * len(values)) - 1],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "p95_method": "nearest rank ceil(0.95*n); small n is not a population guarantee",
    }


def steps():
    return [
        {
            "key": {"named": "space"} if character == " " else {"character": character.lower()},
            "modifiers": ["shift"] if character.isupper() else [],
        }
        for character in TEXT
    ]


def receiver_matches(value):
    return (
        value.get("text_sha256") == EXPECTED_SHA256
        and value.get("utf8_bytes") == value.get("utf16_units") == 8
        and value.get("selection_utf16") == {"location": 8, "length": 0}
        and value.get("return_count") == 0
        and value.get("down_count") == value.get("up_count") == 8
        and value.get("event_counts", {}).get("key_down") == 8
        and value.get("event_counts", {}).get("key_up") == 8
        and value.get("event_records_dropped") == 0
    )


async def run_key_rounds(
    *,
    call,
    fixture_command,
    bridge,
    app,
    nonce,
    rounds,
    mode,
    record,
    task_ids,
    responses,
    metadata=None,
):
    if not 5 <= rounds <= 25 or mode not in {"single", "sequence", "both"}:
        raise ValueError("Use 5–25 same-workload rounds and an explicit key mode")
    samples, last_sequence = [], None

    async def rpc(tool, label, request):
        identifier = f"keybench-{label}-{nonce}"
        arguments = {"request": request, "task_id": identifier, "idempotency_key": identifier}
        task_ids.append(identifier)  # Reserve before dispatch; no mutation is retried.
        started = time.perf_counter_ns()
        result = await call(tool, arguments)
        elapsed = (time.perf_counter_ns() - started) / 1e6
        responses.add(identifier)
        if result.get("state") != "completed":
            raise RuntimeError(f"Native key task is {result.get('state')}; stop without replay")
        record(
            "key_rpc",
            {
                "task_id": identifier,
                "tool": tool,
                "elapsed_ms": elapsed,
                "mcp_meta": (metadata or {}).get(identifier),
            },
        )
        row = bridge.store.db.execute(
            "SELECT id,state,created,accepted,started,finished FROM tasks WHERE id=?", (identifier,)
        ).fetchone()
        record("key_task_stages", dict(row))
        record("key_task_events", bridge.events("acceptance", identifier))
        return result, elapsed, arguments

    async def snapshot_until_complete():
        async with asyncio.timeout(3):
            while True:  # noqa: ASYNC110 -- receiver readback never reposts an input
                value = await fixture_command("snapshot")
                if receiver_matches(value):
                    return value
                await asyncio.sleep(0.01)

    for round_index in range(rounds):
        modes = (
            [mode]
            if mode != "both"
            else (["single", "sequence"] if round_index % 2 == 0 else ["sequence", "single"])
        )
        for selected in modes:
            initial = await fixture_command("reset")
            if initial["utf8_bytes"] or initial["down_count"] or initial["up_count"]:
                raise RuntimeError("Owned receiver reset did not produce an empty event stream")
            rpc_times = []
            started = time.perf_counter_ns()
            if selected == "single":
                for index, step in enumerate(steps()):
                    _, elapsed, _ = await rpc(
                        "keyboard_control",
                        f"{round_index}-single-{index}",
                        {"app": app, "scope": "app", **step},
                    )
                    rpc_times.append(elapsed)
            else:
                result, elapsed, arguments = await rpc(
                    "keyboard_sequence",
                    f"{round_index}-sequence",
                    {"app": app, "steps": steps()},
                )
                if (
                    result["result"].get("completed_steps") != 8
                    or result["result"].get("post_calls_returned") != 16
                ):
                    raise RuntimeError("Sequence receipt does not contain eight complete key pairs")
                rpc_times.append(elapsed)
                last_sequence = arguments
            rpc_complete_ns = time.perf_counter_ns()
            after = await snapshot_until_complete()
            end_ns = time.perf_counter_ns()
            if after["clipboard_generation"] != initial["clipboard_generation"]:
                raise RuntimeError("Clipboard generation changed during owned key round")
            sample = {
                "round": round_index,
                "mode": selected,
                "keys": 8,
                "tool_calls": len(rpc_times),
                "native_key_downs": 8,
                "native_key_ups": 8,
                "rpc_elapsed_ms": (rpc_complete_ns - started) / 1e6,
                "receiver_readback_ms": (end_ns - rpc_complete_ns) / 1e6,
                "end_to_end_ms": (end_ns - started) / 1e6,
                "rpc_samples_ms": rpc_times,
                "receiver": after,
            }
            record("same_workload_key_round", sample)
            samples.append(sample)
    if last_sequence is not None:
        # Only repeat an already completed, exact request under its original stable IDs.
        # A duplicate should return its receipt, never post or append a key again.
        before_duplicate = await fixture_command("snapshot")
        duplicate = await call("keyboard_sequence", last_sequence)
        after_duplicate = await fixture_command("snapshot")
        checks = ("text_sha256", "utf8_bytes", "down_count", "up_count", "event_sequence")
        if duplicate.get("state") != "completed" or any(
            before_duplicate[key] != after_duplicate[key] for key in checks
        ):
            raise RuntimeError("Completed idempotency probe reposted input or changed its state")
        record("completed_sequence_idempotency", {"same_request": True, "reposted_keys": 0})
    result = {
        "scope": "owned native receiver through local HTTP MCP; no voice/cloud model timing",
        "rounds": samples,
        "summary": {},
    }
    for selected in ("single", "sequence"):
        selected_samples = [sample for sample in samples if sample["mode"] == selected]
        if selected_samples:
            result["summary"][selected] = {
                "round_end_to_end": summary([x["end_to_end_ms"] for x in selected_samples]),
                "rpc": summary([v for x in selected_samples for v in x["rpc_samples_ms"]]),
                "tool_calls": sum(x["tool_calls"] for x in selected_samples),
                "native_key_pairs": 8 * len(selected_samples),
            }
    return result


def stable_permission_observations(value):
    """Exclude only OS probe observation time; retain permissions/revisions/identity."""
    if isinstance(value, dict):
        return {
            key: stable_permission_observations(item)
            for key, item in value.items()
            if key != "observed_at"
        }
    if isinstance(value, list):
        return [stable_permission_observations(item) for item in value]
    return value


async def run_read_rounds(*, call, repeat=10, record):
    """Same four read-only operations on a private backend; never save their contents."""
    if not 10 <= repeat <= 100:
        raise ValueError("Read-only comparison requires 10–100 observations per tool")
    tools = ["bridge_health", "clipboard_info", "policy_inspect", "operation_catalog"]
    samples = []
    for index in range(repeat):
        # Rotate domain order rather than letting one domain always benefit from warmup.
        for tool in tools[index % len(tools) :] + tools[: index % len(tools)]:
            started = time.perf_counter_ns()
            value = await call(tool, {})
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if value.get("error"):
                raise RuntimeError("Read-only tool returned an error")
            sample = {"tool": tool, "index": index, "elapsed_ms": elapsed}
            record("read_tool_sample", sample)
            samples.append(sample)
    return {
        "scope": "private loopback backend with same grants; no voice/cloud model timing",
        "samples": samples,
        "summary": {
            tool: summary([x["elapsed_ms"] for x in samples if x["tool"] == tool]) for tool in tools
        },
    }
