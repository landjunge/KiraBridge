"""TEST ONLY: simulated host callback, actual SDK-2 stdio and existing MCP backend.

This entrypoint is never referenced by production profiles. It sends no webhooks.
"""

import argparse
import asyncio
import json
from pathlib import Path

from mcp.server.stdio import stdio_server
from serve import load_config, make_server


class SimulatedHost:
    allowed_hosts = frozenset({"callbacks.example.test"})

    async def post(self, url, body, headers):
        value = json.loads(body)
        if value.get("type") == "verification":
            return 200, json.dumps({"challenge": value["challenge"]}).encode()
        return 200, b"{}"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--sender-only", action="store_true")
    modes.add_argument("--external-sender", action="store_true")
    args = parser.parse_args()
    server, _, lifecycle = await make_server(
        load_config(str(args.config)),
        "local",
        args.state,
        SimulatedHost.allowed_hosts,
        sender=SimulatedHost(),
        external_sender=args.external_sender,
    )
    if args.sender_only:
        async with lifecycle(server) as worker:
            await worker
        return
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
