"""Read-only discovery from the ACTIVE production command; no simulated callbacks.

This is an operator probe, not proof that ChatGPT rescanned or processed an event.
"""

import argparse
import asyncio
import json
import shlex
from pathlib import Path


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = Path.home() / ".config/kirabridge/tunnel/kirabridge.yaml"
    data = json.loads(profile.read_text())
    command = next(c["command"] for c in data["mcp"]["commands"] if c["channel"] == "main")
    if "serve.py" not in command or "--external-sender" not in command:
        raise RuntimeError("Expected activated production frontend, not test adapter")
    child = await asyncio.create_subprocess_exec(
        *shlex.split(command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    methods = ["server/discover", "events/list", "tools/list"]
    output = {
        "origin": "LOCAL OPERATOR READ-ONLY PROBE OF ACTIVE PRODUCTION COMMAND",
        "host_recognition_proven": False,
        "callbacks_simulated": False,
        "subscription_created": False,
        "task_submitted": False,
        "responses": {},
    }
    try:
        for index, method in enumerate(methods):
            request = {
                "jsonrpc": "2.0",
                "id": f"operator-activation-probe-{index}",
                "method": method,
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientInfo": {
                            "name": "KiraBridge operator read-only probe",
                            "version": "1",
                        },
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            }
            child.stdin.write((json.dumps(request) + "\n").encode())
            await child.stdin.drain()
            async with asyncio.timeout(15):
                while True:
                    reply = json.loads(await child.stdout.readline())
                    if reply.get("id") == request["id"]:
                        break
            if "error" in reply:
                raise RuntimeError(json.dumps(reply["error"]))
            output["responses"][method] = reply["result"]
        assert output["responses"]["server/discover"]["capabilities"]["events"] == {}
        assert (
            output["responses"]["events/list"]["events"][0]["name"] == "kirabridge.task.completed"
        )
        assert any(
            t["name"] == "completion_chat_receipt"
            for t in output["responses"]["tools/list"]["tools"]
        )
        output["production_discovery_passed"] = True
    finally:
        child.stdin.close()
        await asyncio.wait_for(child.wait(), 10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: output[k]
                for k in [
                    "production_discovery_passed",
                    "host_recognition_proven",
                    "callbacks_simulated",
                    "subscription_created",
                    "task_submitted",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
