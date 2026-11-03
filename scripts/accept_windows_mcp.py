"""Interactive Windows guest acceptance: real authenticated MCP to real key events.

Run once with a NEW output filename. Exactly one eight-key sequence targets this
process's own receiver window. Its completed task is then resubmitted unchanged
to check durable idempotence. Negative controls use fresh IDs with no eligible
input: a stale target identity, followed by a revoked capability. No clipboard,
host-Mac input, production config, credentials or external connector is used.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import secrets
import socket
import statistics
import tempfile
import threading
import time
from pathlib import Path

TERMINAL_STATES = {"completed", "failed", "unknown", "cancelled", "blocked", "withdrawn"}


def load_receiver():
    source = Path(__file__).with_name("accept_windows_keyboard.py")
    spec = importlib.util.spec_from_file_location("kirabridge_windows_guest_receiver", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Windows receiver fixture is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Receiver()


def snapshot(receiver):
    with receiver.lock:
        events = [dict(event) for event in receiver.events]
    return receiver.text(), events


def task_summary(task):
    result = task.get("result")
    error = task.get("error")
    return {
        "id": task.get("id"),
        "state": task.get("state"),
        "error_code": error.get("code") if isinstance(error, dict) else None,
        "result": result,
    }


async def run_mcp(receiver, report):
    import httpx
    import uvicorn

    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.bridge_core.config import Config, PrincipalConfig
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer
    from kirabridge.mcp_gateway.http import create_http_app

    nonce = secrets.token_hex(8)
    environment_key = "KIRABRIDGE_GUEST_ACCEPTANCE_" + nonce.upper()
    if environment_key in os.environ:
        raise RuntimeError("Fresh guest authentication variable unexpectedly exists")
    token = secrets.token_urlsafe(48)
    os.environ[environment_key] = token
    root = Path(tempfile.mkdtemp(prefix="kirabridge-win-mcp-"))
    report["isolated_state_dir"] = str(root / "state")
    report["state_retained_for_original_task_reconciliation"] = True
    policy = PrincipalConfig(
        approval_mode="automatic",
        client_type="operator",
        token_env=environment_key,
        capabilities=[
            "bridge.health",
            "task.read",
            "windows.keyboard.inspect",
            "windows.keyboard.sequence",
        ],
    )
    configuration = Config(
        data_dir=str(root / "state"), concurrency=1, principals={"local": policy}
    )
    socket_handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        socket_handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    socket_handle.bind(("127.0.0.1", 0))
    socket_handle.listen(64)
    configuration.port = socket_handle.getsockname()[1]
    endpoint = f"http://127.0.0.1:{configuration.port}/mcp"
    report["endpoint_scope"] = "Ephemeral localhost port, inside guest only"
    tool_samples = report["tool_samples"]
    bridge, serving, server = None, None, None
    started = time.monotonic_ns()
    try:
        bridge = Bridge(configuration)
        application = create_http_app(bridge)

        class CountingHTTP:
            def __init__(self, app):
                self.app, self.counts = app, {}

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    method = scope.get("method", "unknown")
                    self.counts[method] = self.counts.get(method, 0) + 1
                return await self.app(scope, receive, send)

        counted = CountingHTTP(application)
        server = uvicorn.Server(uvicorn.Config(counted, log_level="critical", access_log=False))
        async with bridge:
            serving = asyncio.create_task(server.serve(sockets=[socket_handle]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                            raise RuntimeError("Guest HTTP server stopped before readiness")
                        await asyncio.sleep(0.01)
                async with httpx.AsyncClient(trust_env=False) as probe:
                    status = (await probe.get(endpoint, timeout=3)).status_code
                if status != 401:
                    raise RuntimeError("Unauthenticated guest HTTP request was not rejected")
                report["unauthenticated_http_status"] = status
                async with MCPClientPool(call_timeout=15) as clients:
                    connect_started = time.monotonic_ns()
                    await clients.connect(Peer("guest", url=endpoint, token=token))
                    report["connect_initialize_catalog_ms"] = (
                        time.monotonic_ns() - connect_started
                    ) / 1e6

                    async def call(tool, arguments, *, label):
                        begin = time.monotonic_ns()
                        item = {"tool": tool, "label": label, "completed": False}
                        tool_samples.append(item)
                        try:
                            reply = await clients.call("guest", tool, arguments)
                            value = reply.structuredContent
                            if not isinstance(value, dict):
                                raise RuntimeError(f"{label}: structured MCP result missing")
                            if reply.isError:
                                raise RuntimeError(f"{label}: MCP transport/tool error")
                            item["completed"] = True
                            item["task_state"] = value.get("state")
                            item["error_code"] = (value.get("error") or {}).get("code")
                            return value
                        finally:
                            item["elapsed_ms"] = (time.monotonic_ns() - begin) / 1e6

                    async def finished_task(task, task_id):
                        # Only observe this original ID. Never create a replacement on timeout.
                        deadline = time.monotonic() + 8
                        while task.get("state") not in TERMINAL_STATES:
                            if task.get("error") or time.monotonic() >= deadline:
                                raise RuntimeError(f"Original task unresolved: {task_id}")
                            task = await call(
                                "task_get", {"task_id": task_id}, label="same_id_read"
                            )
                            if task.get("state") not in TERMINAL_STATES:
                                await asyncio.sleep(0.02)
                        return task

                    async def submit(operation, arguments, task_id, label):
                        request = {
                            "task_id": task_id,
                            "idempotency_key": task_id,
                            "operation": operation,
                            "arguments": arguments,
                        }
                        initial = await call("task_request", {"request": request}, label=label)
                        return request, await finished_task(initial, task_id)

                    # Read-only samples, no physical repetition and no omitted warm-up.
                    for _index in range(5):
                        health = await call("bridge_health", {}, label="health_read_only")
                        if not health.get("dispatcher_active"):
                            raise RuntimeError("Guest dispatcher is not running")
                        report["runtime_version"] = health.get("version")

                    await asyncio.to_thread(receiver.set_layout, "00000409")
                    inspection_id = "win_mcp_inspect_" + nonce
                    _, inspection = await submit(
                        "windows.keyboard.inspect", {}, inspection_id, "inspect_foreground"
                    )
                    if inspection.get("state") != "completed":
                        raise RuntimeError("Guest foreground inspection did not complete")
                    target = inspection["result"]["target"]
                    if int(target["hwnd"]) != receiver.hwnd or target["pid"] != os.getpid():
                        raise RuntimeError("Own receiver is not the exact inspected foreground")
                    for field in ("hwnd", "process_created_100ns", "keyboard_layout"):
                        if not isinstance(target[field], str):
                            raise RuntimeError(
                                "Opaque Windows identity lost decimal-string contract"
                            )
                    before_text, before_events = snapshot(receiver)
                    steps = [{"character": "s", "modifiers": ["shift"]}]
                    steps.extend(
                        {"named": "space"} if character == " " else {"character": character}
                        for character in "tern am"
                    )
                    sequence_id = "win_mcp_sequence_" + nonce
                    request, sequence = await submit(
                        "windows.keyboard.sequence",
                        {"target": target, "steps": steps},
                        sequence_id,
                        "eight_real_keys",
                    )
                    report["sequence_task"] = task_summary(sequence)
                    if sequence.get("state") != "completed":
                        raise RuntimeError("Original keyboard task did not complete; never replay")
                    native = sequence["result"]
                    if (
                        native.get("completed_keys") != 8
                        or native.get("inserted_events") != 18
                        or native.get("native_calls") != 8
                        or not native.get("physical_key_events")
                        or native.get("receiver_processing_confirmed") is not False
                    ):
                        raise RuntimeError("Native insertion evidence is not eight real key pairs")
                    expected_order = [("down", 0x10), ("down", 0x53), ("up", 0x53), ("up", 0x10)]
                    for key in (0x54, 0x45, 0x52, 0x4E, 0x20, 0x41, 0x4D):
                        expected_order.extend((("down", key), ("up", key)))
                    deadline = time.monotonic() + 3
                    while True:
                        text, events = snapshot(receiver)
                        received = [
                            event for event in events if event["tag"] == native["event_tag"]
                        ]
                        if text == before_text + "Stern am" and len(received) >= 18:
                            break
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Windows receiver did not acknowledge exact text/events"
                            )
                        await asyncio.sleep(0.01)
                    if [(event["kind"], event["vk"]) for event in received] != expected_order:
                        raise RuntimeError("Windows receiver down/up order is not exact")
                    if len(events) != len(before_events) + 18:
                        raise RuntimeError("Unexpected additional keyboard events reached receiver")
                    report["receiver_ack"] = {
                        "text": "Stern am",
                        "text_exact": True,
                        "events": received,
                        "down_up_order_exact": True,
                        "event_count": 18,
                    }

                    readback = await call(
                        "task_get", {"task_id": sequence_id}, label="completed_readback"
                    )
                    if readback.get("state") != "completed" or readback.get("result") != native:
                        raise RuntimeError("Separate completed-task readback differs")
                    stable = snapshot(receiver)
                    transition_count = bridge.store.db.execute(
                        "SELECT count(*) FROM events WHERE task_id=?", (sequence_id,)
                    ).fetchone()[0]
                    replay = await call(
                        "task_request", {"request": request}, label="same_completed_id"
                    )
                    if replay.get("state") != "completed" or replay.get("result") != native:
                        raise RuntimeError("Same completed task did not return its original result")
                    await asyncio.sleep(0.15)
                    if (
                        snapshot(receiver) != stable
                        or bridge.store.db.execute(
                            "SELECT count(*) FROM events WHERE task_id=?", (sequence_id,)
                        ).fetchone()[0]
                        != transition_count
                    ):
                        raise RuntimeError(
                            "Completed-task replay generated input or new transitions"
                        )
                    report["same_completed_task_idempotence"] = {
                        "task_id": sequence_id,
                        "additional_receiver_events": 0,
                        "additional_task_transitions": 0,
                        "result_exact": True,
                    }

                    wrong_id = "win_mcp_stale_target_" + nonce
                    wrong_target = {**target, "hwnd": str(int(target["hwnd"]) + 1)}
                    _, refused = await submit(
                        "windows.keyboard.sequence",
                        {"target": wrong_target, "steps": [{"character": "x"}]},
                        wrong_id,
                        "stale_target_negative",
                    )
                    if (
                        refused.get("state") not in {"failed", "unknown"}
                        or (refused.get("error") or {}).get("code") != "windows_target_changed"
                    ):
                        raise RuntimeError("Stale-target control did not fail before native input")
                    await asyncio.sleep(0.05)
                    if snapshot(receiver) != stable:
                        raise RuntimeError("Stale-target control generated receiver input")
                    report["stale_target_control"] = {
                        "task_id": wrong_id,
                        "state": refused["state"],
                        "error_code": "windows_target_changed",
                        "additional_receiver_events": 0,
                        "state_scope": "No receiver input; conservative unknown is never replayed",
                    }

                    revoked_id = "win_mcp_revoked_" + nonce
                    configuration.principals["local"].capabilities.remove(
                        "windows.keyboard.sequence"
                    )
                    revoked = await call(
                        "task_request",
                        {
                            "request": {
                                "task_id": revoked_id,
                                "idempotency_key": revoked_id,
                                "operation": "windows.keyboard.sequence",
                                "arguments": {"target": target, "steps": [{"character": "x"}]},
                            },
                        },
                        label="permission_revoked_negative",
                    )
                    if (revoked.get("error") or {}).get("code") != "forbidden":
                        raise RuntimeError("Revoked permission was not rejected")
                    await asyncio.sleep(0.05)
                    if (
                        snapshot(receiver) != stable
                        or bridge.store.db.execute(
                            "SELECT count(*) FROM tasks WHERE id=?", (revoked_id,)
                        ).fetchone()[0]
                        != 0
                    ):
                        raise RuntimeError(
                            "Revoked-permission control admitted work or generated input"
                        )
                    report["permission_revocation_control"] = {
                        "task_id": revoked_id,
                        "error_code": "forbidden",
                        "persisted_tasks": 0,
                        "additional_receiver_events": 0,
                    }
            finally:
                server.should_exit = True
                if serving is not None:
                    await asyncio.wait_for(serving, 10)
                report["http_requests_by_method"] = counted.counts
    finally:
        socket_handle.close()
        # The generated token never leaves memory and never replaces a real variable.
        os.environ.pop(environment_key, None)
        report["total_mcp_phase_ms"] = (time.monotonic_ns() - started) / 1e6
        report["tool_call_attempts"] = len(tool_samples)
        health_samples = [
            sample["elapsed_ms"]
            for sample in tool_samples
            if sample["label"] == "health_read_only" and sample["completed"]
        ]
        if len(health_samples) == 5:
            report["read_only_health_latency"] = {
                "n": 5,
                "p50_ms": statistics.median(health_samples),
                "p95_ms": sorted(health_samples)[math.ceil(0.95 * len(health_samples)) - 1],
                "p95_scope": "Nearest rank; n=5 means sample maximum, not a tail forecast",
                "warmup_omitted": False,
            }
        report["physical_sequence_latency_quantiles"] = {
            "n": 1 if report.get("receiver_ack") else 0,
            "p50_p95_reported": False,
            "reason": "One physical sequence; no repeated input merely to manufacture percentiles",
        }


def worker(receiver, output):
    report = {
        "scope": "Real guest localhost authenticated MCP -> persistent task -> Win32 -> receiver",
        "passed": False,
        "clipboard_used": False,
        "host_mac_input": False,
        "production_credentials_used": False,
        "external_chatgpt_cloud_measured": False,
        "tool_samples": [],
        "automatic_input_retry": False,
    }
    try:
        if not receiver.ready.wait(5):
            raise RuntimeError("Own Windows receiver was not ready")
        asyncio.run(run_mcp(receiver, report))
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if hasattr(error, "provider_error"):
            report["provider_error"] = error.provider_error
    finally:
        try:
            output.seek(0)
            output.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
            output.truncate()
            output.flush()
            os.fsync(output.fileno())
        finally:
            if receiver.hwnd:
                receiver.user.PostMessageW(receiver.hwnd, 0x8002, 0, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if os.name != "nt":
        parser.error("Run only inside an interactive Windows guest")
    try:
        output = arguments.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Output already exists; reconcile that original run instead of replaying")
    with output:
        output.write('{"state":"started","passed":false,"automatic_input_retry":false}\n')
        output.flush()
        os.fsync(output.fileno())
        receiver = load_receiver()
        thread = threading.Thread(target=worker, args=(receiver, output), daemon=True)
        thread.start()
        receiver.run()
        thread.join(timeout=10)
        if thread.is_alive() or receiver.error:
            raise SystemExit(receiver.error or "Guest MCP worker did not stop")
    report = json.loads(arguments.output.read_text(encoding="utf-8"))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
