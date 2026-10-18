from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
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
    if args.command == "setup":
        from kirabridge.local_runtime import setup

        emit(setup(args.workspace, Path(args.config) if args.config else None))
        return
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
    if args.command == "readiness":
        from kirabridge.local_runtime import peer
        from kirabridge.mcp_gateway.client import MCPClientPool
        from kirabridge.readiness import ReadinessInput, runtime_snapshot

        requirements = ReadinessInput(read_paths=args.read_path, executables=args.executable)
        async with MCPClientPool(call_timeout=10) as pool:
            await pool.connect(peer(config, args.principal))
            response = await pool.call("daemon", "bridge_readiness", requirements.model_dump())
        result = response.structuredContent or {"error": {"code": "invalid_readiness"}}
        expected = runtime_snapshot(config)
        actual = result.get("runtime", {})
        matches = bool(actual) and all(
            actual.get(key) == expected[key]
            for key in [
                "config_path",
                "config_sha256",
                "effective_config_sha256",
                "source_tree_sha256",
            ]
        )
        result["service_matches_local_config_and_source"] = matches
        emit(result)
        if (
            not matches
            or result.get("requested_prerequisites_ready") is False
            or result.get("error")
        ):
            raise SystemExit(1)
        return
    if args.command == "message":
        from kirabridge.local_runtime import peer
        from kirabridge.mcp_gateway.client import MCPClientPool
        from kirabridge.message_manager import MessageSend

        tool = {
            "send": "message_send",
            "receive": "message_receive",
            "ack": "message_ack",
            "get": "message_get",
            "conversation": "conversation_get",
            "status": "message_channel_status",
        }[args.action]
        payload = {}
        if args.action == "send":
            payload["message"] = MessageSend(
                recipient=args.recipient,
                conversation_id=args.conversation,
                idempotency_key=args.key,
                body=args.text,
                kind=args.kind,
                reply_to=args.reply_to,
                task_id=args.task_id,
                dispatch=not args.inbox_only,
                request_reply=False if args.no_reply else None,
            ).model_dump()
        elif args.action in {"get", "ack"}:
            payload["message_id"] = args.message_id
            if args.action == "ack":
                payload["receipt"] = args.receipt
        elif args.action == "receive":
            payload = {"after": args.after, "limit": args.limit, "wait_seconds": args.wait}
        elif args.action == "conversation":
            payload["conversation_id"] = args.conversation
        async with MCPClientPool(call_timeout=30) as pool:
            await pool.connect(peer(config, args.principal))
            result = await pool.call("daemon", tool, payload)
            emit(result.structuredContent or {"error": {"code": "invalid_channel_response"}})
            if result.isError or (result.structuredContent or {}).get("error"):
                raise SystemExit(1)
        return
    if args.command in {"approvals", "approval-server"}:
        from kirabridge.console_runtime import open_console, serve_console
        from kirabridge.local_runtime import default_config

        config_path = Path(args.config).absolute() if args.config else default_config()
        if args.command == "approvals":
            emit(open_console(config_path))
        else:
            await serve_console(config, config_path)
        return
    if args.command == "chatgpt":
        from kirabridge.chatgpt_setup import wizard
        from kirabridge.local_runtime import default_config

        emit(
            wizard(
                config,
                Path(args.config).absolute() if args.config else default_config(),
                args.action,
            )
        )
        return
    if args.command in {"status", "service", "connect"}:
        from kirabridge.local_runtime import daemon_health, default_config, install_service

        if args.command == "connect":
            from kirabridge.mcp_gateway.proxy import connect_stdio

            await connect_stdio(config, args.principal)
        elif args.command == "service":
            if args.action == "install":
                emit(
                    install_service(
                        Path(args.config).absolute() if args.config else default_config()
                    )
                )
            else:
                emit(await daemon_health(config, args.principal))
        else:
            emit(await daemon_health(config, args.principal))
        return
    if args.command == "serve" and args.transport == "http":
        from kirabridge.local_runtime import load_service_credentials

        load_service_credentials(config)
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
            await run_request(
                bridge,
                args.principal,
                request,
                args.wait,
                args.approve,
                args.original if args.command == "retry" else None,
            )
        elif args.command in {"ls", "read", "write", "exec", "ask", "clipboard"}:
            policy = config.principals.get(args.principal)
            if not policy or not policy.roots:
                raise BridgeError("workspace_missing", "Configure an allowed workspace first")
            root = policy.roots[0]
            if args.command in {"ls", "read", "write"}:
                path = str(Path(args.path or root).expanduser().absolute())
                operation = {"ls": "file.list", "read": "file.read", "write": "file.write"}[
                    args.command
                ]
                arguments = {"path": path}
                if args.command == "write":
                    arguments.update(text=args.text, overwrite=args.overwrite)
            elif args.command == "exec":
                argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
                operation, arguments = (
                    "terminal.execute",
                    {"argv": argv, "cwd": args.cwd or root, "timeout": args.timeout},
                )
            elif args.command == "ask":
                operation, arguments = (
                    "agent.execute",
                    {
                        "agent": args.agent,
                        "prompt": args.prompt,
                        "cwd": args.cwd or root,
                        "timeout": args.timeout,
                    },
                )
            else:
                operation = "clipboard." + args.action
                arguments = {"text": args.text} if args.action == "write" else {}
            identifier = "local-" + uuid.uuid4().hex
            request = TaskRequest(
                task_id=identifier,
                idempotency_key=identifier,
                operation=operation,
                arguments=arguments,
            )
            await run_request(bridge, args.principal, request, 3700, True)
        elif args.command == "pending":
            rows = bridge.store.db.execute(
                "SELECT id FROM tasks WHERE state='created' ORDER BY created LIMIT 100"
            )
            emit(
                {
                    "requests": [bridge.store.get(row[0]) for row in rows],
                    "approve_command": "kirabridge approve TASK_ID",
                }
            )
        elif args.command == "approve":
            approved = bridge.tasks.approve(args.task_id)
            emit(approved)
        elif args.command == "deny":
            task = bridge.store.get(args.task_id)
            if task["state"] not in {State.CREATED, State.QUEUED}:
                raise BridgeError("state_conflict", "Only pending or queued requests can be denied")
            bridge.store.transition(
                args.task_id,
                State.CANCELLED,
                {"source": "local_operator_rejection"},
                expected_states={State.CREATED, State.QUEUED},
            )
            emit(bridge.store.get(args.task_id))
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
                    "schema": 2,
                    "audit": verify(bridge.store),
                    "agents": bridge.agents.inventory(list(config.agents)),
                    "chatgpt_integration": "unverified",
                }
            )
    finally:
        # __aexit__ also closes; sqlite close is idempotent.
        bridge.store.close()


async def run_request(bridge, principal, request, wait, approve, original=None):
    bridge.validate(request)
    approval = (
        bridge.security.grant(principal, request)
        if approve
        else os.environ.get("KIRABRIDGE_APPROVAL", "")
    )
    if original:
        bridge.tasks.retry(principal, original, request, approval)
    else:
        bridge.submit(principal, request, approval)
    owns_dispatcher = False
    try:
        await bridge.tasks.start()
        owns_dispatcher = True
    except BridgeError as exc:
        if exc.code != "already_running":
            raise
    try:
        final = await bridge.tasks.wait(principal, request.task_id, wait)
        emit(final)
    finally:
        if owns_dispatcher:
            await bridge.tasks.stop()
    if final["state"] != State.COMPLETED:
        raise SystemExit(3 if final["state"] == State.UNKNOWN else 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="KiraBridge private desktop bridge")
    parser.add_argument("--config", help="TOML policy file (or KIRABRIDGE_CONFIG)")
    parser.add_argument("--principal", default="local", help="Local CLI/stdio policy identity")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="Create private local policy, credentials and CLI command")
    setup.add_argument("--workspace", default=str(Path.home() / "workspace/KiraBridge"))
    sub.add_parser("status", help="Query the running local daemon")
    readiness = sub.add_parser(
        "readiness", help="Check requested prerequisites on the loaded daemon"
    )
    readiness.add_argument("--read-path", action="append", default=[])
    readiness.add_argument("--executable", action="append", default=[])
    sub.add_parser("connect", help="Forward MCP stdio to the authenticated local daemon")
    message = sub.add_parser("message", help="Authenticated addressed agent messaging")
    message_actions = message.add_subparsers(dest="action", required=True)
    send = message_actions.add_parser("send")
    send.add_argument("recipient")
    send.add_argument("text")
    send.add_argument("--conversation", required=True)
    send.add_argument("--key", required=True, help="Stable idempotency key for this exact message")
    send.add_argument(
        "--kind", choices=["question", "answer", "work", "result", "note"], default="question"
    )
    send.add_argument("--reply-to")
    send.add_argument("--task-id")
    send.add_argument("--inbox-only", action="store_true", help="Do not invoke a managed agent")
    send.add_argument("--no-reply", action="store_true")
    receive = message_actions.add_parser("receive")
    receive.add_argument("--after", type=int, default=0)
    receive.add_argument("--limit", type=int, default=20)
    receive.add_argument("--wait", type=float, default=0)
    get = message_actions.add_parser("get")
    get.add_argument("message_id")
    ack = message_actions.add_parser("ack")
    ack.add_argument("message_id")
    ack.add_argument("--receipt", required=True)
    conversation = message_actions.add_parser("conversation")
    conversation.add_argument("conversation")
    message_actions.add_parser("status")
    sub.add_parser("approvals", help="Open the private local approval page in your browser")
    sub.add_parser("approval-server", help="Run the loopback-only local approval interface")
    chatgpt = sub.add_parser("chatgpt", help="Local account linking for a private ChatGPT tunnel")
    chatgpt.add_argument("action", choices=["setup", "status"])
    service = sub.add_parser("service")
    service.add_argument("action", choices=["install", "status"])
    sub.add_parser("pending", help="Review requests awaiting local approval")
    approve = sub.add_parser("approve", help="Approve exactly one previously reviewed pending task")
    approve.add_argument("task_id")
    deny = sub.add_parser("deny", help="Reject one pending or queued request without executing it")
    deny.add_argument("task_id")
    for name in ("ls", "read", "write"):
        command = sub.add_parser(name)
        command.add_argument("path", nargs="?" if name == "ls" else None)
        if name == "write":
            command.add_argument("text")
            command.add_argument("--overwrite", action="store_true")
    command = sub.add_parser("exec", help="Locally approve and execute an exact argv list")
    command.add_argument("--cwd")
    command.add_argument("--timeout", type=float, default=60)
    command.add_argument("argv", nargs=argparse.REMAINDER)
    command = sub.add_parser("ask", help="Run a configured agent turn")
    command.add_argument("agent")
    command.add_argument("prompt")
    command.add_argument("--cwd")
    command.add_argument("--timeout", type=float, default=120)
    command = sub.add_parser("clipboard")
    command.add_argument("action", choices=["info", "read", "write"])
    command.add_argument("text", nargs="?")
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
            {"error": {"code": code}},
            stream=sys.stderr if args.command in {"serve", "connect"} else sys.stdout,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
