"""Visible, isolated completion acceptance; Grok/provider errors stay simulated in tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path

from kirabridge.audit_manager import verify
from kirabridge.automatic_review_demo import isolated_http
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, Config, PrincipalConfig, load_config
from kirabridge.completion_client import CompletionClient
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


async def probe_installed():
    config = load_config()
    async with MCPClientPool() as client:
        endpoint = peer(config, "chatgpt")
        await client.connect(endpoint)
        session = client.sessions[endpoint.id]
        capabilities = session.get_server_capabilities().model_dump(exclude_none=True)
        tools = [tool.name for tool in (await session.list_tools()).tools]
        return {
            "scope": "actual installed chatgpt principal; read-only MCP handshake",
            "capabilities": capabilities,
            "completion_tools_available": all(
                t in tools for t in ("completion_receive", "completion_ack")
            ),
            "mcp_events_advertised": "events" in capabilities,
            "chatgpt_unsolicited_assistant_delivery": "not_verified",
            "callback_subscription_supplied_by_host": False,
        }


async def run(root, codex, probe):
    root = root.resolve()
    root.mkdir(mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text(
        "# Completion acceptance\nRead-only task. Do not start agents, access MCP/network, "
        "or modify any files. Return only the requested short response.\n"
    )
    token_name = "KIRABRIDGE_COMPLETION_DEMO_" + secrets.token_hex(8).upper()
    token = secrets.token_hex(32)
    os.environ[token_name] = token
    config = Config(
        data_dir=str(root / "state"),
        concurrency=1,
        principals={
            "local": PrincipalConfig(
                approval_mode="automatic",
                token_env=token_name,
                capabilities=["terminal.execute", "agent.execute", "task.read", "task.cancel"],
                roots=[str(workspace)],
                executables=[sys.executable],
                agents=["codex"],
            )
        },
        agents={
            "codex": AgentConfig(
                kind="codex", executable=str(codex.resolve()), sandbox_mode="read-only"
            )
        }
        if codex
        else {},
    )
    data = {
        "scope": "actual local callback and terminal output; not ChatGPT autonomous wake-up",
        "receipts": [],
        "submissions": [],
        "tool_calls": [],
        "real_grok_calls": 0,
    }

    def save():
        (root / "evidence.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def log(event, **fields):
        print(
            json.dumps({"at": time.time(), "event": event, **fields}, ensure_ascii=False),
            flush=True,
        )

    if probe:
        data["installed_connection_probe"] = await probe_installed()
        log("installed_connection_probe", **data["installed_connection_probe"])
    bridge = Bridge(config)
    try:
        async with isolated_http(bridge) as endpoint, MCPClientPool() as sender:
            endpoint_peer = Peer("completion-demo", url=endpoint, token=token)
            await sender.connect(endpoint_peer)
            for task_id, code, timeout in [
                ("immediate", "print('REAL_FAST_RESULT')", 3),
                ("longer", "import time;print('REAL_START');time.sleep(2);print('REAL_END')", 5),
                ("error", "print('REAL_ERROR_CASE');raise SystemExit(7)", 3),
                ("timeout", "import time;time.sleep(30)", 0.2),
                ("codex", None, 120),
            ]:
                if task_id == "codex" and codex is None:
                    continue
                target = "assistant-" + task_id
                request = {
                    "task_id": task_id,
                    "idempotency_key": task_id,
                    "operation": "agent.execute" if task_id == "codex" else "terminal.execute",
                    "arguments": {
                        "agent": "codex",
                        "prompt": "Dies ist ein echter begrenzter Abschlussbenachrichtigungs-Test. "
                        "Keine Tools verwenden, keine Agenten starten. "
                        "Antworte nur: CODEX_COMPLETION_CONFIRMED.",
                        "cwd": str(workspace),
                        "timeout": timeout,
                    }
                    if task_id == "codex"
                    else {
                        "argv": [sys.executable, "-c", code],
                        "cwd": str(workspace),
                        "timeout": timeout,
                    },
                }
                callback_values = []

                def callback(notice, callback_values=callback_values):
                    callback_values.append(notice)
                    data["receipts"].append(notice)
                    log("completion_callback_received", notice=notice)
                    save()

                async with CompletionClient(endpoint_peer) as listener:
                    original = listener.pool.call

                    async def trace(identity, tool, arguments, original=original):
                        data["tool_calls"].append(tool)
                        return await original(identity, tool, arguments)

                    listener.pool.call = trace
                    waiting = None
                    if task_id != "immediate":
                        waiting = asyncio.create_task(
                            listener.listen(target, callback, once=True, timeout=timeout + 30)
                        )
                    value = await sender.call(
                        endpoint_peer.id,
                        "task_request",
                        {"request": request, "completion_target": target},
                    )
                    if value.isError or (value.structuredContent or {}).get("error"):
                        raise RuntimeError("Submission rejected")
                    data["submissions"].append(value.structuredContent)
                    log("submitted", task_id=task_id, state=value.structuredContent["state"])
                    if task_id == "immediate":
                        # Controlled race: prove completion precedes the very first listener.
                        await bridge.tasks.wait("local", task_id, 5)
                        data["immediate_finished_before_listener"] = True
                        waiting = asyncio.create_task(
                            listener.listen(target, callback, once=True, timeout=10)
                        )
                    await waiting
                    assert len(callback_values) == 1
                    assert not bridge.completions.receive("local", target)["notices"]
                    log(
                        "consumer_acknowledged", task_id=task_id, notice_id=callback_values[0]["id"]
                    )
                    # For one case prove redelivery after connection loss without reexecution.
                    if task_id == "error":
                        archived = callback_values[0]
                        again = await sender.call(
                            endpoint_peer.id,
                            "task_request",
                            {"request": request, "completion_target": target},
                        )
                        assert again.structuredContent["id"] == task_id
                        assert not bridge.completions.receive("local", target)["notices"]
                        log("duplicate_submission_no_new_completion", notice_id=archived["id"])
            # Separate unacknowledged delivery across a real reconnect.
            request = {
                "task_id": "reconnect",
                "idempotency_key": "reconnect",
                "operation": "terminal.execute",
                "arguments": {
                    "argv": [sys.executable, "-c", "print('RECONNECT_ONCE')"],
                    "cwd": str(workspace),
                    "timeout": 3,
                },
            }
            await sender.call(
                endpoint_peer.id,
                "task_request",
                {"request": request, "completion_target": "reconnect"},
            )
            first = await sender.call(
                endpoint_peer.id, "completion_receive", {"target": "reconnect", "wait_seconds": 5}
            )
            pending = first.structuredContent["notices"][0]
            await sender.disconnect(endpoint_peer.id)
            reconnected = []
            async with CompletionClient(endpoint_peer) as listener:
                value = await listener.listen("reconnect", reconnected.append, once=True, timeout=5)
            assert value["id"] == pending["id"] and value["receipt"] == pending["receipt"]
            data["reconnect_receipt_stable"] = True
            data["receipts"].append(value)
            log("reconnected_receipt_verified", notice_id=value["id"])
            data["tasks"] = [
                bridge.store.get(row[0], "local")
                for row in bridge.store.db.execute("SELECT id FROM tasks ORDER BY created")
            ]
            data["acknowledged"] = [
                dict(row)
                for row in bridge.store.db.execute(
                    "SELECT id,acknowledged FROM completion_notices ORDER BY seq"
                )
            ]
            data["audit"] = verify(bridge.store)
            data["no_task_status_polling_by_consumer"] = "task_get" not in data["tool_calls"]
            data["passed"] = (
                data["audit"]["valid"]
                and all(row["acknowledged"] for row in data["acknowledged"])
                and data["no_task_status_polling_by_consumer"]
            )
            save()
            assert data["passed"]
            log(
                "acceptance_passed",
                completions=len(data["receipts"]),
                outcomes=[n["payload"]["outcome"] for n in data["receipts"]],
                chatgpt_unsolicited_delivery="not_verified",
            )
    finally:
        os.environ.pop(token_name, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--real-codex", type=Path)
    parser.add_argument("--probe-installed", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.root, args.real_codex, args.probe_installed))


if __name__ == "__main__":
    main()
