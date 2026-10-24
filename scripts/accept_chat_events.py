"""Real terminal + HTTP backend + MCP-2 stdio; HOST/CHAT CALLBACK IS SIMULATED.

Usage: .venv/bin/python scripts/accept_chat_events.py --adapter-python SDK2_PYTHON --output NEW_DIR
No installed config, model, tunnel or ChatGPT chat is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import shlex
import sqlite3
import sys
import time
from pathlib import Path

import httpx

from kirabridge.automatic_review_demo import isolated_http
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig

REPO = Path(__file__).resolve().parents[1]
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "SIMULATED-HOST", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


class Wire:
    def __init__(self, python, config, state):
        self.python, self.config, self.state = python, config, state
        self.seq = 0
        self.methods = []

    async def start(self):
        self.child = await asyncio.create_subprocess_exec(
            self.python,
            str(REPO / "integrations/chat-events/check_protocol.py"),
            "--config",
            str(self.config),
            "--state",
            str(self.state),
            "--external-sender",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def close(self):
        self.child.stdin.close()
        try:
            await asyncio.wait_for(self.child.wait(), 10)
        except TimeoutError:
            self.child.terminate()  # only this explicitly owned test child
            await asyncio.wait_for(self.child.wait(), 5)
            raise
        diagnostics = (await self.child.stderr.read()).decode()[-12000:]
        if diagnostics:
            print(diagnostics, file=sys.stderr)
        if self.child.returncode:
            # Test-only stderr has no real account credentials/config.
            raise RuntimeError("Isolated SDK2 child failed: " + diagnostics)

    async def rpc(self, method, params=None, *, allow_error=False):
        self.seq += 1
        self.methods.append(method)
        data = {
            "jsonrpc": "2.0",
            "id": self.seq,
            "method": method,
            "params": {**(params or {}), "_meta": META},
        }
        self.child.stdin.write((json.dumps(data) + "\n").encode())
        await self.child.stdin.drain()
        async with asyncio.timeout(15):
            while True:
                line = await self.child.stdout.readline()
                if not line:
                    error = (await self.child.stderr.read()).decode()[-4000:]
                    raise RuntimeError("Isolated SDK2 child closed: " + error)
                reply = json.loads(line)
                if reply.get("id") == self.seq:
                    if "error" in reply:
                        if allow_error:
                            return reply
                        raise RuntimeError(json.dumps(reply))
                    return reply["result"]

    async def call(self, name, arguments, **kwargs):
        return await self.rpc("tools/call", {"name": name, "arguments": arguments}, **kwargs)


class TunnelWire(Wire):
    """Existing tunnel binary, LOCAL in-memory control plane; no hosted tunnel."""

    def __init__(self, python, config, state, binary):
        super().__init__(python, config, state)
        self.binary = binary

    async def start(self):
        url_file = self.config.parent / "local-tunnel-url.json"
        url_file.unlink(missing_ok=True)
        self.log = (self.config.parent / "local-tunnel.log").open("w")
        command = shlex.join(
            [
                self.python,
                str(REPO / "integrations/chat-events/check_protocol.py"),
                "--config",
                str(self.config),
                "--state",
                str(self.state),
                "--external-sender",
            ]
        )
        self.child = await asyncio.create_subprocess_exec(
            self.binary,
            "dev",
            "proxy",
            "--mcp-command",
            command,
            "--duration",
            "45s",
            "--url-file",
            str(url_file),
            "--readiness-timeout",
            "10s",
            "--response-timeout",
            "15s",
            env={**os.environ, "MCP_STDIO_SEND_INITIALIZED_NOTIFICATION": "true"},
            stdout=self.log,
            stderr=self.log,
        )
        async with asyncio.timeout(15):
            while not url_file.exists():
                if self.child.returncode is not None:
                    raise RuntimeError("Local-only tunnel stopped; see local-tunnel.log")
                await asyncio.sleep(0.05)
        urls = json.loads(url_file.read_text())
        print("Local in-memory tunnel fields: " + ",".join(urls), flush=True)
        self.url = urls.get("mcp_url") or urls.get("url")
        if not self.url:
            raise RuntimeError("No MCP URL in local tunnel file: " + json.dumps(urls))
        self.http = httpx.AsyncClient(trust_env=False, timeout=20)

    async def close(self):
        if getattr(self, "http", None):
            await self.http.aclose()
        if self.child.returncode is None:
            self.child.terminate()  # only this explicitly owned local TEST proxy
        await asyncio.wait_for(self.child.wait(), 10)
        self.log.close()

    async def rpc(self, method, params=None, *, allow_error=False):
        self.seq += 1
        self.methods.append(method)
        response = await self.http.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": self.seq,
                "method": method,
                "params": {**(params or {}), "_meta": META},
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2026-07-28",
            },
        )
        response.raise_for_status()
        reply = response.json()
        if "error" in reply:
            if allow_error:
                return reply
            raise RuntimeError(json.dumps(reply))
        return reply["result"]


def delivery(state, task_id):
    if not (state / "events.sqlite3").exists():
        return None
    with sqlite3.connect(state / "events.sqlite3") as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM deliveries").fetchall()
        for row in rows:
            if json.loads(row["body"])["data"]["task_id"] == task_id:
                return dict(row)
    return None


async def wait_delivery(state, task_id):
    async with asyncio.timeout(15):
        while True:
            row = delivery(state, task_id)
            if row and row["state"] == "webhook_accepted":
                return row
            await asyncio.sleep(0.05)


async def run(args):
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir()
    state = root / "event-state"
    token_name = "KIRABRIDGE_ISOLATED_EVENTS_TEST_TOKEN"
    os.environ[token_name] = secrets.token_hex(32)
    config = Config(
        data_dir=str(root / "bridge-state"),
        concurrency=1,
        principals={
            "local": PrincipalConfig(
                capabilities=["terminal.execute", "task.read", "bridge.health"],
                roots=[str(workspace)],
                executables=[sys.executable],
                approval_mode="automatic",
                token_env=token_name,
            )
        },
    )
    bridge = Bridge(config)
    evidence = {
        "host": "SIMULATION; no ChatGPT callback",
        "chat_delivery": "NOT_VERIFIED",
        "actual_chat_receipt": False,
        "tunnel": "local in-memory control plane" if args.tunnel_client else "none; direct stdio",
        "tests": [],
        "tasks": [],
    }
    async with isolated_http(bridge) as backend_endpoint:
        config_file = root / "test-config.toml"
        policy = config.principals["local"]
        config_file.write_text(
            f"data_dir = {json.dumps(config.data_dir)}\nport = {config.port}\n"
            "concurrency = 1\n[principals.local]\n"
            + "\n".join(
                f"{key} = {json.dumps(getattr(policy, key))}"
                for key in ("capabilities", "roots", "executables", "approval_mode", "token_env")
            )
            + "\n"
        )
        config_file.chmod(0o600)
        wire = (
            TunnelWire(args.adapter_python, config_file, state, args.tunnel_client)
            if args.tunnel_client
            else Wire(args.adapter_python, config_file, state)
        )
        sender_log = (root / "simulated-sender.log").open("w")
        sender = await asyncio.create_subprocess_exec(
            args.adapter_python,
            str(REPO / "integrations/chat-events/check_protocol.py"),
            "--config",
            str(config_file),
            "--state",
            str(state),
            "--sender-only",
            stdout=sender_log,
            stderr=sender_log,
        )
        await wire.start()
        try:
            discover = await wire.rpc("server/discover")
            assert discover["capabilities"]["events"] == {}
            assert "2026-07-28" in discover["supportedVersions"]
            events = await wire.rpc("events/list")
            assert events["events"][0]["name"] == "kirabridge.task.completed"
            tools = await wire.rpc("tools/list")
            submit_tool = next(t for t in tools["tools"] if t["name"] == "task_request")
            assert "completion_subscription" not in submit_tool["inputSchema"]["properties"]
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                backend_catalog = (
                    await client.post(
                        backend_endpoint,
                        json={
                            "jsonrpc": "2.0",
                            "id": "catalog-compatibility",
                            "method": "tools/list",
                            "params": {},
                        },
                        headers={
                            "Authorization": "Bearer " + os.environ[token_name],
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": "2025-11-25",
                        },
                    )
                ).json()["result"]["tools"]
            for method in ("task_request", "task_submit"):
                original = next(t for t in backend_catalog if t["name"] == method)
                forwarded = next(t for t in tools["tools"] if t["name"] == method)
                assert original["inputSchema"] == forwarded["inputSchema"]
            evidence["normal_tool_schemas_unchanged"] = True
            evidence["normal_submissions_without_subscription"] = []
            for method in ("task_request", "task_submit"):
                task_id = "no-subscription-" + method
                ordinary = {
                    "task_id": task_id,
                    "idempotency_key": task_id,
                    "operation": "terminal.execute",
                    "arguments": {
                        "argv": [sys.executable, "-c", "print('NORMAL_TASK_WITHOUT_SUBSCRIPTION')"],
                        "cwd": str(workspace),
                        "timeout": 5,
                    },
                }
                normal = await wire.call(method, {"request": ordinary})
                assert not normal.get("isError"), normal
                final = await bridge.tasks.wait("local", task_id)
                assert final["state"] == "completed" and final["result"]["exit_code"] == 0
                assert final["result"]["stdout"] == "NORMAL_TASK_WITHOUT_SUBSCRIPTION\n"
                assert delivery(state, task_id) is None
                evidence["normal_submissions_without_subscription"].append(
                    {
                        "method": method,
                        "task_id": task_id,
                        "state": final["state"],
                        "stdout": final["result"]["stdout"],
                        "exit_code": 0,
                        "subscription_created": False,
                    }
                )
            evidence["tests"].append(
                "unchanged task schemas; both normal submit tools without subscription"
            )
            evidence["discovery"] = {
                "protocol": "2026-07-28",
                "capabilities": discover["capabilities"],
                "events": [e["name"] for e in events["events"]],
            }
            evidence["tests"].append("actual SDK2 server/discover + events/list + tools/list")
            for task_id, code, outcome in [
                ("events-fast", "print('EVENTS_FAST_REAL_TERMINAL')", "success"),
                (
                    "events-reconnect",
                    "import time; time.sleep(1); print('EVENTS_RECONNECT')",
                    "success",
                ),
                ("events-failure", "print('EVENTS_ERROR'); raise SystemExit(7)", "error"),
            ]:
                params = {
                    "name": "kirabridge.task.completed",
                    "arguments": {"task_id": task_id},
                    "delivery": {
                        "mode": "webhook",
                        "url": "https://callbacks.example.test/chat-A/" + task_id,
                        "secret": "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode(),
                    },
                }
                sub = await wire.rpc("events/subscribe", params)
                refreshed = await wire.rpc("events/subscribe", params)
                assert refreshed["id"] == sub["id"]
                request = {
                    "task_id": task_id,
                    "idempotency_key": task_id,
                    "operation": "terminal.execute",
                    "arguments": {
                        "argv": [sys.executable, "-c", code],
                        "cwd": str(workspace),
                        "timeout": 5,
                    },
                }
                rejected = await wire.call(
                    "task_request",
                    {"request": request, "completion_target": "push:wrong-subscription"},
                    allow_error=True,
                )
                assert "error" in rejected or rejected.get("isError")
                assert not bridge.store.db.execute(
                    "SELECT 1 FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                result = await wire.call(
                    "task_request", {"request": request, "completion_target": "push:" + sub["id"]}
                )
                assert not result.get("isError"), result
                if task_id == "events-reconnect":
                    await wire.close()
                    closed_at = time.time()
                    assert bridge.store.get(task_id)["state"] in {"queued", "accepted", "running"}
                    await bridge.tasks.wait("local", task_id)
                    offline_delivery = await wait_delivery(state, task_id)
                    assert offline_delivery["assistant_receipt"] is None
                    finished_at = bridge.store.get(task_id)["finished"]
                    with sqlite3.connect(state / "events.sqlite3") as journal:
                        accepted_at = journal.execute(
                            "SELECT at FROM observations WHERE kind='webhook_accepted' "
                            "AND event_id=?",
                            (offline_delivery["event_id"],),
                        ).fetchone()[0]
                    reconnect_at = time.time()
                    assert closed_at < finished_at <= accepted_at < reconnect_at
                    evidence["offline_delivery_timing"] = {
                        "frontend_closed_at": closed_at,
                        "task_finished_at": finished_at,
                        "simulated_webhook_accepted_at": accepted_at,
                        "reconnect_not_before": reconnect_at,
                        "ordering_verified": True,
                    }
                    evidence["tests"].append(
                        "persistent sender delivers AFTER frontend disconnect, BEFORE reconnect"
                    )
                    await wire.start()
                    await wire.rpc("server/discover")
                    again = await wire.rpc("events/subscribe", params)
                    assert again["id"] == sub["id"]
                    evidence["tests"].append(
                        "disconnect during real terminal; same durable subscription on restart"
                    )
                await bridge.tasks.wait("local", task_id)
                row = await wait_delivery(state, task_id)
                event = json.loads(row["body"])
                assert event["data"]["outcome"] == outcome
                assert event["data"]["subscription_id"] == sub["id"]
                assert row["assistant_receipt"] is None
                receipt = await wire.call(
                    "completion_chat_receipt",
                    {
                        "subscription_id": sub["id"],
                        "event_id": row["event_id"],
                        "task_id": task_id,
                        "receipt_token": event["data"]["receipt_token"],
                    },
                )
                value = receipt["structuredContent"]
                assert value["chat_ui_receipt_independently_verified"] is False
                # Same submission must not create another process/task.
                duplicate = await wire.call(
                    "task_request", {"request": request, "completion_target": "push:" + sub["id"]}
                )
                assert not duplicate.get("isError")
                stop = {
                    **params,
                    "delivery": {k: v for k, v in params["delivery"].items() if k != "secret"},
                }
                await wire.rpc("events/unsubscribe", stop)
                await wire.rpc("events/unsubscribe", stop)
                task = bridge.store.get(task_id)
                evidence["tasks"].append(
                    {
                        "task_id": task_id,
                        "state": task["state"],
                        "outcome": outcome,
                        "subscription_id": sub["id"],
                        "event_id": row["event_id"],
                        "notice_id": row["notice_id"],
                        "transport_state": row["state"],
                        "event_sha256": hashlib.sha256(row["body"].encode()).hexdigest(),
                        "process_evidence": task["result"],
                        "receipt_scope": value["receipt_scope"],
                        "chat_ui_receipt_independently_verified": False,
                    }
                )
                print(
                    f"{task_id}: real terminal {task['state']}; "
                    "simulated webhook accepted; CHAT UNVERIFIED",
                    flush=True,
                )
            evidence["methods"] = wire.methods
            evidence["tests"].extend(
                [
                    "fast real terminal completion",
                    "exitcode 7 propagated",
                    "bad subscription rejected BEFORE execution",
                    "duplicate submission no second task",
                    "unsubscribe idempotent",
                    "payload receipt explicitly does not prove chat UI",
                ]
            )
            assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 5
            evidence["local_protocol_passed"] = True
            evidence["elapsed_seconds"] = round(time.monotonic() - args.started, 3)
        finally:
            await wire.close()
            if sender.returncode is None:
                sender.terminate()  # only the explicitly owned test sender
            await asyncio.wait_for(sender.wait(), 10)
            sender_log.close()
    bridge.store.close()
    (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("Local protocol passed. Actual ChatGPT chat delivery NOT VERIFIED.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-python", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tunnel-client", help="Optional existing binary; local dev proxy only")
    args = parser.parse_args()
    args.started = time.monotonic()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
