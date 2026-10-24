"""Probe actual active adapter, authenticated backend and harmless temporary work.

Does not impersonate a ChatGPT Host, subscribe to events or start agents.
"""

import argparse
import asyncio
import json
import shlex
from pathlib import Path

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "operator access acceptance", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads((Path.home() / ".config/kirabridge/tunnel/kirabridge.yaml").read_text())
    command = next(c["command"] for c in profile["mcp"]["commands"] if c["channel"] == "main")
    child = await asyncio.create_subprocess_exec(
        *shlex.split(command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    seq = 0

    async def rpc(method, params):
        nonlocal seq
        seq += 1
        request = {
            "jsonrpc": "2.0",
            "id": seq,
            "method": method,
            "params": {"_meta": META, **params},
        }
        child.stdin.write((json.dumps(request) + "\n").encode())
        await child.stdin.drain()
        async with asyncio.timeout(20):
            while True:
                reply = json.loads(await child.stdout.readline())
                if reply.get("id") == seq:
                    break
        assert "error" not in reply, reply
        return reply["result"]

    async def call(name, arguments):
        result = await rpc("tools/call", {"name": name, "arguments": arguments})
        value = result.get("structuredContent")
        if value is None:
            value = json.loads(result["content"][0]["text"])
        assert not value.get("error"), value
        return value

    evidence = {
        "origin": "OPERATOR PROBE THROUGH ACTUAL PRODUCTION COMMAND; NOT CHATGPT HOST",
        "events_subscription_used": False,
        "event_test_started": False,
        "host_callback_simulated": False,
        "tasks": [],
    }
    try:
        listing = (await rpc("tools/list", {}))["tools"]
        schemas = {t["name"]: t["inputSchema"] for t in listing}
        for name in ("task_request", "task_submit", "action_request", "action_submit"):
            assert "completion_subscription" not in schemas[name]["properties"]
            assert schemas[name]["required"] == ["request"]
        evidence["task_schemas"] = {
            n: schemas[n]
            for n in ("task_request", "task_submit", "action_request", "action_submit")
        }
        evidence["loaded_policy"] = await call("policy_inspect", {})
        evidence["direct_read"] = await call(
            "read_query",
            {
                "query": {
                    "operation": "file.read",
                    "path": "/private/tmp/kirabridge-access-20261019-01/probe.txt",
                    "max_bytes": 64,
                }
            },
        )
        assert evidence["direct_read"]["text"] == "KIRABRIDGE_APP_FILE_OK\n"
        evidence["sessions"] = await call("session_catalog", {})
        for label, tool, operation, arguments in [
            (
                "move",
                "action_request",
                "file.move",
                {
                    "path": "/private/tmp/kirabridge-access-20261019-01/probe.txt",
                    "destination": "/private/tmp/kirabridge-access-20261019-01/moved.txt",
                },
            ),
            (
                "delete",
                "action_submit",
                "file.delete",
                {"path": "/private/tmp/kirabridge-access-20261019-01/moved.txt"},
            ),
        ]:
            task_id = "access-alias-" + label + "-20261019-01"
            request = {
                "task_id": task_id,
                "idempotency_key": task_id,
                "operation": operation,
                "arguments": arguments,
            }
            await call(tool, {"request": request})
            async with asyncio.timeout(10):
                while True:
                    task = await call("task_get", {"task_id": task_id})
                    if task["state"] not in ("queued", "created", "accepted", "running"):
                        break
                    await asyncio.sleep(0.05)
            assert task["state"] == "completed", task
            evidence["tasks"].append(
                {"tool": tool, "subscription_field_present": False, "result": task}
            )
        evidence["passed"] = True
    finally:
        child.stdin.close()
        await asyncio.wait_for(child.wait(), 10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "production_adapter_test_passed": True,
                "normal_task_schemas_without_subscription": True,
                "direct_file_read_passed": True,
                "action_request_move": "completed",
                "action_submit_delete": "completed",
                "session_transport": evidence["sessions"]["status"],
                "actual_chatgpt_host_scan_proven": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
