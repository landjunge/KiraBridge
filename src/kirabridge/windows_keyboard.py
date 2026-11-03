"""Explicit Windows contracts; never reinterpret macOS key codes or target tokens."""

from __future__ import annotations

import sys
import time
from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, EmptyInput, Input, UncertainExecution
from kirabridge.platform_adapters.windows.keyboard import KeyStroke, WindowsKeyboard, WindowTarget


class WindowsTargetInput(Input):
    hwnd: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)
    pid: int = Field(gt=0, lt=2**32, strict=True)
    process_created_100ns: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)
    thread_id: int = Field(gt=0, lt=2**32, strict=True)
    keyboard_layout: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)

    @model_validator(mode="after")
    def native_widths(self):
        WindowTarget.from_wire(self.model_dump())
        return self


class WindowsStrokeInput(Input):
    named: str | None = Field(default=None, min_length=1, max_length=32, strict=True)
    character: str | None = Field(default=None, min_length=1, max_length=1, strict=True)
    scan_code: int | None = Field(default=None, ge=1, le=127, strict=True)
    unicode: str | None = Field(default=None, min_length=1, max_length=1, strict=True)
    extended: bool = Field(default=False, strict=True)
    modifiers: list[Literal["control", "alt", "shift", "windows"]] = Field(
        default_factory=list, max_length=4
    )
    repeat: int = Field(default=1, ge=1, le=20, strict=True)

    def native(self):
        return KeyStroke(**{**self.model_dump(), "modifiers": tuple(self.modifiers)})

    @model_validator(mode="after")
    def coherent(self):
        self.native()
        return self


class WindowsSequenceInput(Input):
    target: WindowsTargetInput
    steps: list[WindowsStrokeInput] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_events(self):
        if sum(step.repeat for step in self.steps) > 32:
            raise ValueError("A Windows sequence may request at most 32 keys")
        return self


WINDOWS_KEYBOARD_INPUTS = {
    "windows.keyboard.inspect": EmptyInput,
    "windows.keyboard.sequence": WindowsSequenceInput,
}


class WindowsKeyboardManager:
    def __init__(self, authorize, desktop_input, *, backend_factory=WindowsKeyboard, host=None):
        self.authorize, self.desktop_input = authorize, desktop_input
        self.factory, self.backend = backend_factory, None
        self.host = sys.platform if host is None else host

    def require(self):
        if self.host != "win32":
            raise BridgeError(
                "unsupported_platform", "Windows keyboard needs an interactive Windows guest"
            )
        if self.backend is None:
            self.backend = self.factory()
        return self.backend

    def catalog(self, decide):
        return [
            {
                "operation": operation,
                "provider_id": "windows.sendinput.v1",
                "host_platform": self.host,
                "available": self.host == "win32",
                "eligible_for_submission": self.host == "win32" and decide(operation)["authorized"],
                "policy": decide(operation),
                "scope": "Windows input stream; insertion is not application acknowledgement",
            }
            for operation in WINDOWS_KEYBOARD_INPUTS
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
                            "windows_input_deadline_unknown",
                            "Windows input deadline expired; reconcile original task, no replay",
                        )
                    raise BridgeError(
                        "windows_input_deadline_expired", "Deadline expired before Windows input"
                    )

            target = None
            if operation == "windows.keyboard.sequence":
                target = WindowTarget.from_wire(args.target.model_dump())
                if backend.inspect_foreground() != target:
                    raise BridgeError(
                        "windows_target_changed", "Windows foreground changed before input"
                    )
            check_deadline()
            await running({"evidence_type": "windows_keyboard_started", "automatic_retry": False})
            if operation == "windows.keyboard.inspect":
                self.authorize(principal, operation)
                return {
                    "target": backend.inspect_foreground().to_wire(),
                    "provider": "windows.sendinput.v1",
                    "effect_attempted": False,
                }

            def before_send():
                self.authorize(principal, operation)
                self.authorize(principal, "windows.keyboard.inspect")
                check_deadline()
                turn.mark_attempted()

            result = backend.send(
                target,
                [step.native() for step in args.steps],
                before_send=before_send,
            )
            check_deadline()
            return {**result, "provider": "windows.sendinput.v1"}
