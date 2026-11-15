"""Opt-in Events envelope for the existing connect command; no SDK upgrade.

The standalone sender must share this private journal. This process never starts
models, installs services, edits tunnel profiles, or invents a host subscription.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from serve import Backend  # noqa: E402

from kirabridge.bridge_core.config import load_config  # noqa: E402
from kirabridge.event_push import EventJournal, EventPush, WebhookSender  # noqa: E402
from kirabridge.mcp_gateway.event_envelope import EventEnvelope, stdio  # noqa: E402


async def main_async(args):
    config = load_config(str(args.config))
    policy = config.principals[args.principal]
    if not {"task.read", "message.read"} <= set(policy.capabilities):
        raise RuntimeError("existing_task_and_message_read_permissions_required")
    backend = Backend(config, args.principal)
    journal = EventJournal(args.state)

    push = EventPush(
        journal,
        config.state_path / "bridge.sqlite3",
        args.principal,
        WebhookSender(args.allow_callback_host),
        backend.authorize,
        authorize_message=backend.authorize_message,
    )
    child = args.child or [
        sys.executable,
        "-m",
        "kirabridge.cli",
        "--config",
        str(args.config),
        "--principal",
        args.principal,
        "connect",
    ]
    if child[0] == "--":
        child = child[1:]
    try:
        await stdio(EventEnvelope(push), child)
    finally:
        await backend.client.aclose()
        journal.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--principal", default="chatgpt")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--allow-callback-host", action="append", default=[])
    parser.add_argument("child", nargs=argparse.REMAINDER)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
