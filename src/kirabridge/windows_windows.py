"""Explicit Windows window tasks, sharing the keyboard desktop transaction."""

from __future__ import annotations

import sys
import time
from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution
from kirabridge.platform_adapters.windows.windows import (
    WindowBounds,
    WindowIdentity,
    WindowsWindows,
)


class WindowsWindowTargetInput(Input):
    hwnd: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)
    pid: str = Field(pattern=r"^[1-9][0-9]{0,9}$", strict=True)
    process_created_100ns: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)
    thread_id: str = Field(pattern=r"^[1-9][0-9]{0,9}$", strict=True)

    @model_validator(mode="after")
    def native_widths(self):
        WindowIdentity.from_wire(self.model_dump())
        return self


class WindowsWindowBoundsInput(Input):
    x: int = Field(ge=-(2**31), lt=2**31, strict=True)
    y: int = Field(ge=-(2**31), lt=2**31, strict=True)
    width: int = Field(ge=1, le=32768, strict=True)
    height: int = Field(ge=1, le=32768, strict=True)

    @model_validator(mode="after")
    def native_bounds(self):
        WindowBounds(**self.model_dump())
        return self


class WindowsWindowListInput(Input):
    limit: int = Field(default=32, ge=1, le=64, strict=True)


class WindowsWindowControlInput(Input):
    target: WindowsWindowTargetInput
    action: Literal["activate", "minimize", "maximize", "restore", "move_resize", "close"]
    bounds: WindowsWindowBoundsInput | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.action == "move_resize") != (self.bounds is not None):
            raise ValueError("Bounds are required only for move_resize")
        return self


WINDOWS_WINDOW_INPUTS = {
    "windows.window.list": WindowsWindowListInput,
    "windows.window.control": WindowsWindowControlInput,
}


class WindowsWindowManager:
    def __init__(self, authorize, desktop_input, *, backend_factory=WindowsWindows, host=None):
        self.authorize, self.desktop_input = authorize, desktop_input
        self.factory, self.backend = backend_factory, None
        self.host = sys.platform if host is None else host

    def require(self):
        if self.host != "win32":
            raise BridgeError("unsupported_platform", "Windows window tasks require Windows")
        if self.backend is None:
            self.backend = self.factory()
        return self.backend

    def catalog(self, decide):
        return [
            {
                "operation": operation,
                "provider_id": "windows.windows.v1",
                "host_platform": self.host,
                "available": self.host == "win32",
                "eligible_for_submission": self.host == "win32" and decide(operation)["authorized"],
                "policy": decide(operation),
                "scope": "Exact top-level Windows target; requested and observed effects differ",
            }
            for operation in WINDOWS_WINDOW_INPUTS
        ]

    async def execute(self, task, args, running, progress=None):
        operation, principal = task["operation"], task["principal"]
        self.authorize(principal, operation)
        backend = self.require()
        deadline = time.monotonic() + self.desktop_input.timeout
        async with self.desktop_input.transaction() as turn:

            def check_deadline():
                if time.monotonic() >= deadline:
                    if turn.attempted:
                        raise UncertainExecution(
                            "windows_window_deadline_unknown",
                            "Window deadline expired after an attempt; reconcile original task",
                        )
                    raise BridgeError(
                        "windows_window_deadline_expired", "Window deadline expired before effect"
                    )

            target = None
            if operation == "windows.window.control":
                target = WindowIdentity.from_wire(args.target.model_dump())
                backend.inspect(target)
            check_deadline()
            await running({"evidence_type": "windows_window_started", "automatic_retry": False})
            if operation == "windows.window.list":
                self.authorize(principal, operation)
                result = backend.list(args.limit)
            else:

                def before_effect():
                    self.authorize(principal, operation)
                    self.authorize(principal, "windows.window.list")
                    check_deadline()
                    turn.mark_attempted()

                result = backend.control(
                    target,
                    args.action,
                    bounds=WindowBounds(**args.bounds.model_dump()) if args.bounds else None,
                    before_effect=before_effect,
                )
            check_deadline()
            return {**result, "provider": "windows.windows.v1"}
