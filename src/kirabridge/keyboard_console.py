"""Authenticated presentation only; the keyboard endpoint owns its 32 KiB limit."""

import json
import uuid

from starlette.responses import JSONResponse
from starlette.routing import Route

from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_keyboard import OperatorKeyboard


class KeyboardConsole:
    def __init__(self, control, decisions, authenticate):
        self.service, self.authenticate = OperatorKeyboard(control, decisions), authenticate
        self.routes = [
            Route("/api/control/keyboard/availability", self.availability, methods=["GET"]),
            Route("/api/control/keyboard/request", self.request, methods=["POST"]),
            Route("/api/control/keyboard/task/{task_id}", self.task, methods=["GET"]),
        ]

    async def availability(self, request):
        self.authenticate(request)
        return JSONResponse(await self.service.availability())

    async def request(self, request):
        self.authenticate(request)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise BridgeError("invalid_request", "A JSON keyboard intent is required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 32 * 1024:
                raise BridgeError("payload_limit", "Keyboard UI request exceeds 32 KiB")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise BridgeError("invalid_request", "Invalid keyboard UI JSON") from error
        return JSONResponse(await self.service.request(value))

    async def task(self, request):
        self.authenticate(request)
        task_id = request.path_params["task_id"]
        task = await self.service.status(task_id)
        nonce, _ = self.service._scope(task_id)
        return JSONResponse(
            {
                "request_id": str(uuid.UUID(hex=nonce)),
                "task": task,
                "status_url": f"/api/control/keyboard/task/ui-keyboard-{nonce}-main",
            }
        )
