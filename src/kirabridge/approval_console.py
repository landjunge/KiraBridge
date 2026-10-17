"""Local operator surface. This application is never mounted on the MCP gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from kirabridge import LOCAL_APPROVAL_URL
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, State

PORT = 8766
ORIGIN = LOCAL_APPROVAL_URL.rstrip("/")
SESSION_AGE = 30 * 24 * 3600
ASSETS = Path(__file__).with_name("console_assets")


def signature(key: str, purpose: str, value: str) -> str:
    return hmac.new(key.encode(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def signed_token(key: str, purpose: str, *, now: float | None = None) -> str:
    value = f"{int(time.time() if now is None else now)}.{secrets.token_hex(16)}"
    return value + "." + signature(key, purpose, value)


def valid_token(key: str, purpose: str, token: str, max_age: float) -> bool:
    if not re.fullmatch(r"[0-9]{1,16}\.[a-f0-9]{32}\.[a-f0-9]{64}", token):
        return False
    stamp, nonce, mac = token.split(".")
    age = time.time() - int(stamp)
    return -5 <= age <= max_age and hmac.compare_digest(
        mac, signature(key, purpose, stamp + "." + nonce)
    )


async def limited_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise BridgeError("payload_limit", "Request exceeds limit")
    return bytes(body)


class ApprovalConsole:
    def __init__(self, bridge: Bridge, key: str):
        if len(key) < 32:
            raise BridgeError("unsafe_credentials", "Console credential is too short")
        self.bridge, self.key = bridge, key
        self.instance = secrets.token_hex(16)
        self.used_tickets: dict[str, float] = {}
        self.app = Starlette(
            exception_handlers={BridgeError: self.error},
            routes=[
                Route("/health", self.health),
                Route("/login", self.login, methods=["POST"]),
                Route("/", self.index),
                Route("/app.js", self.asset),
                Route("/login.js", self.asset),
                Route("/style.css", self.asset),
                Route("/api/tasks", self.tasks),
                Route("/api/tasks/{task_id}", self.task),
                Route("/api/tasks/{task_id}/{decision}", self.decide, methods=["POST"]),
            ],
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        client = scope.get("client")
        if (
            headers.get(b"host") != f"127.0.0.1:{PORT}".encode()
            or not client
            or client[0] not in {"127.0.0.1", "::1"}
        ):
            return await JSONResponse({"error": "local_access_only"}, status_code=403)(
                scope, receive, send
            )

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                    (
                        b"content-security-policy",
                        b"default-src 'none'; script-src 'self'; style-src 'self'; "
                        b"connect-src 'self'; base-uri 'none'; form-action 'self'; "
                        b"frame-ancestors 'none'",
                    ),
                ]
            await send(message)

        await self.app(scope, receive, secure_send)

    async def error(self, request: Request, exc: BridgeError):
        code = 404 if exc.code == "not_found" else 409
        if exc.code in {"unauthorized", "csrf"}:
            code = 401 if exc.code == "unauthorized" else 403
        if exc.code in {"invalid_request", "payload_limit"}:
            code = 400 if exc.code == "invalid_request" else 413
        return JSONResponse({"error": exc.code}, status_code=code)

    def authenticate(self, request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not valid_token(self.key, "session", token, SESSION_AGE):
            raise BridgeError("unauthorized", "Open the console from this Mac")
        if request.method == "POST" and request.headers.get("origin") != ORIGIN:
            raise BridgeError("csrf", "A local browser decision is required")

    async def health(self, request: Request):
        challenge = request.headers.get("x-kirabridge-challenge", "")
        if not re.fullmatch(r"[a-f0-9]{32}", challenge):
            raise BridgeError("invalid_request", "A health challenge is required")
        return JSONResponse(
            {
                "name": "KiraBridge approvals",
                "instance": self.instance,
                "proof": signature(self.key, "probe", challenge + "." + self.instance),
            }
        )

    async def login(self, request: Request):
        if request.headers.get("origin") not in {None, "null", ORIGIN}:
            raise BridgeError("csrf", "Use the local launcher")
        if request.headers.get("content-type", "").split(";")[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise BridgeError("invalid_request", "Use the local launcher")
        try:
            fields = parse_qs((await limited_body(request)).decode("ascii"), max_num_fields=2)
            tokens = fields.get("ticket", [])
            ticket = tokens[0] if len(tokens) == 1 else ""
        except (UnicodeDecodeError, ValueError):
            raise BridgeError("invalid_request", "Invalid login request") from None
        if not valid_token(self.key, "login:" + self.instance, ticket, 120):
            raise BridgeError("unauthorized", "The local login link has expired")
        now = time.time()
        self.used_tickets = {k: t for k, t in self.used_tickets.items() if t > now - 125}
        if ticket in self.used_tickets or len(self.used_tickets) >= 256:
            raise BridgeError("unauthorized", "Open the local launcher again")
        self.used_tickets[ticket] = now
        session = signed_token(self.key, "session")
        return HTMLResponse(
            '<!doctype html><html lang="de"><meta charset="utf-8">'
            '<meta name="referrer" content="no-referrer"><title>KiraBridge öffnen</title>'
            '<body><p id="login" data-session="' + session + '">KiraBridge wird geöffnet …</p>'
            '<script src="/login.js" defer></script></body></html>'
        )

    async def index(self, request: Request):
        return HTMLResponse((ASSETS / "index.html").read_text())

    async def asset(self, request: Request):
        name = request.url.path.removeprefix("/")
        media_type = "text/css" if name.endswith(".css") else "application/javascript"
        return Response((ASSETS / name).read_text(), media_type=media_type)

    async def tasks(self, request: Request):
        self.authenticate(request)
        rows = self.bridge.store.db.execute(
            "SELECT id,principal,operation,agent,state,created,updated FROM tasks "
            "ORDER BY CASE state WHEN 'created' THEN 0 WHEN 'queued' THEN 1 "
            "WHEN 'accepted' THEN 2 WHEN 'running' THEN 3 WHEN 'unknown' THEN 4 ELSE 5 END, "
            "updated DESC LIMIT 100"
        ).fetchall()
        count = self.bridge.store.db.execute(
            "SELECT count(*) FROM tasks WHERE state='created'"
        ).fetchone()[0]
        return JSONResponse(
            {
                "tasks": [dict(row) for row in rows],
                "pending": count,
                "approval_modes": {
                    name: policy.approval_mode
                    for name, policy in self.bridge.config.principals.items()
                },
            }
        )

    async def task(self, request: Request):
        self.authenticate(request)
        task_id = request.path_params["task_id"]
        task = self.bridge.store.get(task_id)
        request_hash = self.bridge.store.db.execute(
            "SELECT request_hash FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0]
        return JSONResponse({"task": task, "request_hash": request_hash})

    async def decide(self, request: Request):
        self.authenticate(request)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise BridgeError("invalid_request", "A JSON decision is required")
        try:
            payload = json.loads(await limited_body(request))
        except ValueError:
            raise BridgeError("invalid_request", "Invalid decision") from None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"request_hash"}
            or not isinstance(payload["request_hash"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", payload["request_hash"])
        ):
            raise BridgeError("invalid_request", "Review the complete request first")
        task_id, decision = request.path_params["task_id"], request.path_params["decision"]
        if decision == "approve":
            self.bridge.tasks.approve(
                task_id, expected_hash=payload["request_hash"], source="local_console"
            )
        elif decision == "deny":
            self.bridge.store.transition(
                task_id,
                State.CANCELLED,
                {"source": "local_console_rejection"},
                expected_hash=payload["request_hash"],
                expected_states={State.CREATED, State.QUEUED},
            )
        else:
            raise BridgeError("invalid_request", "Unknown decision")
        return JSONResponse({"task": self.bridge.store.get(task_id)})
