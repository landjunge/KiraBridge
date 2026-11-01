"""Actual isolated HTTP/background/profiler acceptance of an installed candidate.

Run with the exact candidate interpreter and -I. No production config, service,
clipboard, window, historical task or OS permission request is used.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.operations_service import installed_source_sha
from kirabridge.platform_adapters.macos.system_identity import installed_native_contract


def require(value, label):
    if not value:
        raise RuntimeError(label)


def save(root, name, value):
    with (root / name).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def remaining_live_session_members(session_id):
    observed = subprocess.run(
        ["/bin/ps", "-axo", "pid=,stat="],
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    )
    members = []
    for raw in observed.stdout.splitlines():
        fields = raw.split()
        require(len(fields) == 2, "Process census row is malformed")
        pid, status = int(fields[0]), fields[1]
        try:
            if os.getsid(pid) == session_id and not status.startswith("Z"):
                members.append(pid)
        except ProcessLookupError:
            pass
    return members


async def main(args):
    os.umask(0o077)
    require(sys.platform == "darwin", "macOS acceptance only")
    root = Path(args.root).absolute()
    require(not root.exists(), "Use a fresh acceptance root; reconcile previous attempts")
    root.mkdir(parents=True, mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    evidence = {
        "scope": "isolated real HTTP Core and freshly owned processes only",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "package": kirabridge.__file__,
        "version": kirabridge.__version__,
        "source_sha256": installed_source_sha(),
        "source_commit": args.commit,
        "production_paths_used": False,
        "original_tasks_replayed": False,
        "checks": [],
        "passed": False,
    }
    require(kirabridge.__version__ == args.expected_version, "Exact candidate version required")
    require(evidence["source_sha256"] == args.source_sha256, "Candidate source differs")
    contract = installed_native_contract(kirabridge.__file__)
    require(contract.get("expected_commit") == args.commit, "Managed candidate pin differs")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    token = secrets.token_urlsafe(48)
    local_token = secrets.token_urlsafe(48)
    os.environ["KIRABRIDGE_P0_ACCEPT_CHATGPT_TOKEN"] = token
    os.environ["KIRABRIDGE_P0_ACCEPT_LOCAL_TOKEN"] = local_token
    capabilities = [
        "bridge.health",
        "terminal.execute",
        "session.inspect",
        "session.input",
        "system.report",
        "process.inspect",
        "task.read",
    ]
    policy = PrincipalConfig(
        capabilities=capabilities,
        roots=[str(workspace)],
        terminal_roots=[str(workspace)],
        executables=["/bin/sleep", "/usr/sbin/system_profiler"],
        permission_level="full",
        token_env="KIRABRIDGE_P0_ACCEPT_CHATGPT_TOKEN",
    )
    config = Config(
        host="127.0.0.1",
        port=port,
        data_dir=str(root / "state"),
        principals={
            "chatgpt": policy,
            "local": policy.model_copy(
                update={"token_env": "KIRABRIDGE_P0_ACCEPT_LOCAL_TOKEN"}, deep=True
            ),
        },
    )
    bridge = Bridge(config)
    server = uvicorn.Server(
        uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
    )
    try:
        async with bridge:
            require(bridge.tasks.native.timeout == 30, "Unmodified admission budget required")
            serving = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.01)
                async with MCPClientPool(call_timeout=8) as client:
                    await client.connect(
                        Peer("candidate", url=f"http://127.0.0.1:{port}/mcp", token=token)
                    )

                    async def call(tool, arguments):
                        result = await client.call("candidate", tool, arguments)
                        value = result.structuredContent
                        if isinstance(value, dict) and isinstance(value.get("error"), dict):
                            evidence["last_call_error"] = {
                                "tool": tool,
                                "code": value["error"].get("code"),
                            }
                        require(
                            not result.isError
                            and isinstance(value, dict)
                            and not value.get("error"),
                            "MCP call failed: " + tool,
                        )
                        return value

                    async def task(task_id):
                        # Task failures intentionally contain an error field.
                        result = await client.call("candidate", "task_get", {"task_id": task_id})
                        value = result.structuredContent
                        require(
                            not result.isError
                            and isinstance(value, dict)
                            and value.get("id") == task_id,
                            "Task read failed",
                        )
                        return value

                    async def settle(task_id, budget, *, cross_admission=False):
                        deadline = time.monotonic() + budget
                        crossed = False
                        while True:
                            value = await task(task_id)
                            elapsed = time.monotonic() - starts[task_id]
                            if value["state"] in {"completed", "failed", "unknown", "cancelled"}:
                                return value, crossed
                            require(
                                time.monotonic() < deadline, "Own acceptance task did not settle"
                            )
                            if cross_admission and elapsed > 30.5:
                                require(value["state"] == "running", "Process lost after admission")
                                crossed = True
                            await asyncio.sleep(0.5)

                    health = await call("bridge_health", {})
                    require(
                        health["runtime"]["source_tree_sha256"] == args.source_sha256
                        and health["dispatcher_active"],
                        "Actual HTTP Core source/health differs",
                    )
                    evidence["runtime"] = health["runtime"]
                    starts = {}
                    nonce = secrets.token_hex(6)
                    sleep_id = "p0-accept-sleep35-" + nonce
                    sleep_request = {
                        "task_id": sleep_id,
                        "idempotency_key": sleep_id,
                        "operation": "terminal.execute",
                        "arguments": {
                            "argv": ["/bin/sleep", "35"],
                            "cwd": str(workspace),
                            "background": True,
                            "timeout": 45,
                            "max_output": 128,
                        },
                    }
                    starts[sleep_id] = time.monotonic()
                    admitted = await call("action_request", {"request": sleep_request})
                    admission_seconds = time.monotonic() - starts[sleep_id]
                    require(
                        admitted["state"] == "running"
                        and admitted["delivery"]["status"] == "process_started"
                        and admitted["result"] is None
                        and "terminal_input_attempted" not in admitted["evidence"],
                        "Managed admission is not a recorded process start",
                    )
                    final, crossed = await settle(sleep_id, 50, cross_admission=True)
                    require(
                        crossed
                        and final["state"] == "completed"
                        and final["result"]["exit_code"] == 0
                        and not final["result"]["timed_out"],
                        "Actual35s background process failed",
                    )
                    repeat = await call("action_request", {"request": sleep_request})
                    require(repeat["state"] == "completed", "Existing ID did not remain completed")
                    events = bridge.store.db.execute(
                        "SELECT evidence FROM events WHERE task_id=? AND state='running'",
                        (sleep_id,),
                    ).fetchall()
                    require(
                        sum(
                            json.loads(row[0]).get("evidence_type") == "local_process_spawned"
                            for row in events
                        )
                        == 1,
                        "Repeated ID caused another spawn",
                    )
                    save(root, "sleep35-task.private.json", final)
                    evidence["checks"].append(
                        {
                            "name": "background35s_with45s_runtime_and30s_admission",
                            "passed": True,
                            "admission_seconds": admission_seconds,
                            "seconds": time.monotonic() - starts[sleep_id],
                            "pid": final["result"]["pid"],
                            "crossed_admission_budget_while_running": crossed,
                            "spawn_count_after_id_reuse": 1,
                        }
                    )
                    for budget in (60, 1):
                        task_id = f"p0-accept-applications-{budget}-" + nonce
                        starts[task_id] = time.monotonic()
                        submitted = await call(
                            "action_request",
                            {
                                "request": {
                                    "task_id": task_id,
                                    "idempotency_key": task_id,
                                    "operation": "system.report",
                                    "arguments": {
                                        "report": "applications",
                                        "detail": "mini",
                                        "timeout": budget,
                                        "max_output": 128,
                                    },
                                }
                            },
                        )
                        require(submitted["id"] == task_id, "Own report admission differs")
                        final, _ = await settle(task_id, budget + 10)
                        save(root, f"applications-{budget}-task.private.json", final)
                        result = final.get("result") or {}
                        require(final["state"] != "unknown", "Report cleanup remained unknown")
                        details = {
                            "name": f"applications_{budget}s",
                            "state": final["state"],
                            "seconds": time.monotonic() - starts[task_id],
                            "pid": result.get("pid"),
                        }
                        streams = result.get("output_ranges", {}).get("streams", {})
                        if budget == 60:
                            require(
                                final["state"] == "completed"
                                and result["exit_code"] == 0
                                and not result["timed_out"]
                                and streams["stdout"]["complete"],
                                "Full Applications report did not complete",
                            )
                            expected_bytes = streams["stdout"]["bytes"]
                            require(
                                type(expected_bytes) is int
                                and 0 < expected_bytes <= 64 * 1024 * 1024,
                                "Report stream size is invalid",
                            )
                            output, offset, identity, pages = bytearray(), 0, None, 0
                            while True:
                                pages += 1
                                require(pages <= 1025, "Report page budget exceeded")
                                page = bridge.process_outputs.read(
                                    "chatgpt",
                                    task_id,
                                    "stdout",
                                    offset=offset,
                                    max_bytes=65536,
                                    encoding="base64",
                                    expected_identity=identity,
                                )
                                identity = page["identity"]
                                chunk = base64.b64decode(page["data_base64"], validate=True)
                                next_offset = page["next_offset"]
                                require(
                                    len(chunk) <= 65536
                                    and type(next_offset) is int
                                    and next_offset == offset + len(chunk)
                                    and next_offset <= expected_bytes,
                                    "Report page offsets or bytes differ",
                                )
                                output.extend(chunk)
                                offset = next_offset
                                if page["eof"]:
                                    require(offset == expected_bytes, "Premature report EOF")
                                    break
                                require(
                                    chunk and offset < expected_bytes,
                                    "Report page made no progress",
                                )
                            require(
                                hashlib.sha256(output).hexdigest() == streams["stdout"]["sha256"],
                                "Full persisted report SHA differs",
                            )
                            parsed = json.loads(output)
                            require(
                                isinstance(parsed.get("SPApplicationsDataType"), list),
                                "Invalid JSON report",
                            )
                            details.update(
                                bytes=len(output),
                                applications=len(parsed["SPApplicationsDataType"]),
                            )
                        else:
                            require(
                                final["state"] == "failed"
                                and result.get("timed_out") is True
                                and streams["stdout"]["complete"] is False
                                and streams["stdout"]["error"] == "timeout",
                                "Short report timeout was misclassified",
                            )
                            require(
                                details["seconds"] < budget + 6, "Cleanup exceeded original budget"
                            )
                        remaining = remaining_live_session_members(result["pid"])
                        require(not remaining, "Owned report session has surviving members")
                        require(task_id not in bridge.terminal.sessions, "Report session leaked")
                        details.update(passed=True, live_session_members_after_cleanup=remaining)
                        evidence["checks"].append(details)
                    require(not bridge.terminal.sessions, "Owned process sessions remain")
                    require(not bridge.process_outputs._writers, "Owned output writers remain")
                    require(
                        bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0,
                        "Background acceptance created mailbox messages",
                    )
            finally:
                server.should_exit = True
                try:
                    await asyncio.wait_for(serving, 10)
                finally:
                    sock.close()
        evidence["owned_core_shutdown"] = True
        evidence["passed"] = True
    except BaseException as error:
        evidence["error"] = {"type": type(error).__name__, "code": getattr(error, "code", None)}
        raise
    finally:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(root, "evidence.json", evidence)
        print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--expected-version", default="0.8.0rc23")
    args = parser.parse_args()
    require(re.fullmatch(r"[a-f0-9]{40}", args.commit), "Explicit commit required")
    require(re.fullmatch(r"[a-f0-9]{64}", args.source_sha256), "Explicit source hash required")
    require(
        re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[1-9][0-9]*)?", args.expected_version),
        "Explicit release version required",
    )
    asyncio.run(main(args))
