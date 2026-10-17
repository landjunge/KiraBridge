from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, State, TaskRequest


def emit(value, *, stream=None):
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def parse_request(path: str) -> TaskRequest:
    if path == "-":
        source = sys.stdin.read(2097153)
    else:
        with open(path, encoding="utf-8") as file:
            source = file.read(2097153)
    if len(source.encode()) > 2097152:
        raise BridgeError("payload_limit", "Request file exceeds 2 MiB")
    return TaskRequest.model_validate_json(source)


async def execute(args) -> None:
    if args.command == "init":
        destination = Path(args.destination).expanduser().absolute()
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise BridgeError("config_init", "Workspace must be a directory")
        # JSON strings are valid TOML basic strings for ordinary filesystem paths.
        content = (
            "data_dir = " + json.dumps(str(destination.parent / ".kirabridge-state")) + "\n"
            "[principals.local]\n"
            'capabilities = ["bridge.health", "task.read", "task.cancel", '
            '"file.list", "file.read", "clipboard.info"]\n'
            "roots = [" + json.dumps(str(workspace)) + "]\n"
            "executables = []\nagents = []\n"
        )
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(content)
        emit({"config": str(destination), "workspace": str(workspace)})
        return
    config = load_config(args.config)
    if args.command == "serve" and args.transport == "http":
        config.validate_network()
    bridge = Bridge(config)
    try:
        if args.command == "serve":
            from kirabridge.mcp_gateway.server import create_server

            async with bridge:
                if args.transport == "stdio":
                    await create_server(bridge, principal=args.principal).run_stdio_async()
                else:
                    import uvicorn

                    from kirabridge.mcp_gateway.http import create_http_app

                    server = uvicorn.Server(
                        uvicorn.Config(
                            create_http_app(bridge),
                            host=config.host,
                            port=config.port,
                            ssl_certfile=config.tls_cert,
                            ssl_keyfile=config.tls_key,
                            access_log=False,
                            log_level="critical",
                            limit_concurrency=config.max_http_requests,
                            timeout_keep_alive=5,
                        )
                    )
                    await server.serve()
            return
        if args.command == "grant":
            request = parse_request(args.request)
            bridge.validate(request)
            # Bind the reviewed request to a one-use token. Never expose this authority over MCP.
            token = bridge.security.grant(args.principal, request, args.ttl)
            print(token)
        elif args.command in {"run", "retry"}:
            request = parse_request(args.request)
            bridge.validate(request)
            approval = os.environ.get("KIRABRIDGE_APPROVAL", "")
            if args.approve:
                approval = bridge.security.grant(args.principal, request)
            if args.command == "retry":
                bridge.tasks.retry(args.principal, args.original, request, approval)
            else:
                bridge.submit(args.principal, request, approval)
            owns_dispatcher = False
            try:
                await bridge.tasks.start()
                owns_dispatcher = True
            except BridgeError as exc:
                if exc.code != "already_running":
                    raise
            try:
                final = await bridge.tasks.wait(args.principal, request.task_id, args.wait)
                emit(final)
            finally:
                if owns_dispatcher:
                    await bridge.tasks.stop()
            if final["state"] != State.COMPLETED:
                raise SystemExit(3 if final["state"] == State.UNKNOWN else 2)
        elif args.command == "enqueue":
            request = parse_request(args.request)
            emit(bridge.submit(args.principal, request, os.environ.get("KIRABRIDGE_APPROVAL", "")))
        elif args.command == "task":
            emit(bridge.task(args.principal, args.task_id))
        elif args.command == "tasks":
            emit(bridge.list_tasks(args.principal, args.after, args.limit, args.state))
        elif args.command == "audit":
            emit(verify(bridge.store))
        elif args.command == "reconcile":
            # A local operator attests an inspected external result. Does not execute or retry.
            emit(bridge.tasks.reconcile(args.task_id, State(args.state), args.evidence))
        elif args.command == "doctor":
            from kirabridge.platform_adapters import current_platform

            emit(
                {
                    "python": sys.version.split()[0],
                    "platform": current_platform().name,
                    "database": "ok",
                    "schema": 1,
                    "audit": verify(bridge.store),
                    "agents": bridge.agents.inventory(list(config.agents)),
                    "chatgpt_integration": "unverified",
                }
            )
    finally:
        # __aexit__ also closes; sqlite close is idempotent.
        bridge.store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="KiraBridge private desktop bridge")
    parser.add_argument("--config", help="TOML policy file (or KIRABRIDGE_CONFIG)")
    parser.add_argument("--principal", default="local", help="Local CLI/stdio policy identity")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    init = sub.add_parser("init")
    init.add_argument(
        "destination", help="New private TOML file; existing files are never replaced"
    )
    init.add_argument("--workspace", required=True, help="Existing allowed workspace directory")
    for name in ("grant", "run", "enqueue", "retry"):
        command = sub.add_parser(name)
        command.add_argument("request", help="Exact version-1 request JSON file, or - for stdin")
        if name == "grant":
            command.add_argument("--ttl", type=int, default=300)
        elif name in {"run", "retry"}:
            if name == "retry":
                command.add_argument(
                    "--original", required=True, help="Proven not-started failed task"
                )
            command.add_argument(
                "--approve", action="store_true", help="Explicitly approve this exact request"
            )
            command.add_argument("--wait", type=float, default=3700)
    task = sub.add_parser("task")
    task.add_argument("task_id")
    tasks = sub.add_parser("tasks")
    tasks.add_argument("--after", type=int, default=0)
    tasks.add_argument("--limit", type=int, default=100)
    tasks.add_argument("--state", choices=[state.value for state in State])
    sub.add_parser("audit")
    sub.add_parser("doctor")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("task_id")
    reconcile.add_argument("--state", choices=["completed", "failed", "cancelled"], required=True)
    reconcile.add_argument(
        "--evidence", required=True, help="Reviewed result reference; no credentials"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL, stream=sys.stderr)
    try:
        asyncio.run(execute(args))
    except (BridgeError, ValidationError, OSError, ValueError, TimeoutError) as exc:
        code = exc.code if isinstance(exc, BridgeError) else "invalid_request"
        emit(
            {"error": {"code": code}}, stream=sys.stderr if args.command == "serve" else sys.stdout
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
