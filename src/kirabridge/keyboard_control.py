"""Profile-free keyboard intents; discover once, bind freshly, never replay."""

import asyncio
from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution
from kirabridge.keyboard_models import (
    MAX_TEXT_UTF8_BYTES,
    KeyboardChordInput,
    KeyboardKey,
    KeyboardKeyInput,
    KeyboardTextInput,
    Modifier,
    literal_text,
)
from kirabridge.keyboard_system import (
    HARDWARE_SYSTEM_ACTIONS,
    KeyboardSystemKeyInput,
    possible_system_shortcut,
    registered_system_action,
    system_receipt_verified,
)


class KeyboardControlInput(Input):
    app: str | None = Field(default=None, min_length=1, max_length=255)
    pid: int | None = Field(default=None, gt=0, le=2**31 - 1)
    expected_started_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_UTF8_BYTES)
    key: KeyboardKey | None = None
    modifiers: list[Modifier] = Field(default_factory=list, max_length=5)
    submit: bool = False
    scope: Literal["auto", "app", "system"] = "auto"
    action: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    repeat: int = Field(default=1, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def coherent(self):
        if sum(v is not None for v in (self.text, self.key, self.action)) != 1:
            raise ValueError("Choose text, one key or a system action")
        if self.action is not None and (
            self.scope != "system"
            or (self.modifiers and self.action not in HARDWARE_SYSTEM_ACTIONS)
        ):
            raise ValueError("System actions require scope=system and their configured modifiers")
        if self.scope == "system" and self.text is not None:
            raise ValueError("System scope cannot type text")
        if self.text is not None:
            literal_text(self.text)
            if self.modifiers:
                raise ValueError("Modifiers belong to a key, not literal text")
            if self.repeat != 1:
                raise ValueError("Text is one literal write; repetition belongs to keys")
        elif self.submit:
            raise ValueError("submit belongs to text; use the enter key otherwise")
        if len(self.modifiers) != len(set(self.modifiers)):
            raise ValueError("Modifiers must be unique")
        if (self.pid is None) != (self.expected_started_at is None):
            raise ValueError("PID selection requires its observed start time")
        if self.app is not None and (self.pid is not None or not self.app.strip()):
            raise ValueError("Choose an application name/bundle ID or an exact PID generation")
        return self


CONTROL_INPUTS = {"keyboard.control": KeyboardControlInput}
_FOCUS_OBSERVATION_TIMEOUT = 1.0
_FOCUS_OBSERVATION_INTERVAL = 0.05
_APPLICATION_IDENTITY_FIELDS = ("pid", "started_at", "bundle_id", "app_path", "executable")


class KeyboardControl:
    def __init__(self, keyboard):
        self.keyboard = keyboard

    async def execute(self, task, args, running, progress=None):
        async with self.keyboard.desktop_input.transaction() as turn:
            return await self.execute_in_turn(task, args, running, turn, progress)

    async def execute_in_turn(
        self,
        task,
        args,
        running,
        turn,
        progress=None,
        *,
        expected_application=None,
        authorization_operation=None,
    ):
        """Reuse one caller-owned desktop transaction; never reuse a native target."""
        # Validate again; callers cannot mutate a previously validated intent.
        args = KeyboardControlInput.model_validate(args.model_dump(exclude_none=True))
        k, principal = self.keyboard, task["principal"]

        def authorize(operation="keyboard.control"):
            k.authorize(principal, "keyboard.control")
            if authorization_operation is not None:
                k.authorize(principal, authorization_operation)
            k.authorize(principal, operation)

        async def read(operation, arguments):
            authorize(operation)
            return await k.transport.request(
                operation, arguments, principal=principal, before_send=lambda: authorize(operation)
            )

        async def observe(evidence):
            if progress is not None:
                await progress(evidence)

        authorize()
        await running({"evidence_type": "automatic_keyboard_resolution", "automatic_retry": False})
        if expected_application is not None:
            # A sequence already owns one exact application generation. Its next
            # fresh native inspection proves focus and identity without another
            # full application catalogue. Never refocus or select a replacement.
            app = dict(expected_application)
            if (
                args.scope != "app"
                or args.key is None
                or args.app is not None
                or args.pid != app.get("pid")
                or args.expected_started_at != app.get("started_at")
                or app.get("active") is not True
            ):
                raise BridgeError(
                    "keyboard_application_changed",
                    "Sequence must retain its exact foreground application generation",
                )
        else:
            page = await read("apps.list", {"limit": 1000})
            if page.get("eof") is not True:
                raise BridgeError(
                    "keyboard_catalog_incomplete", "Running program list is incomplete"
                )
            applications = page["applications"]
            if args.pid is not None:
                matches = [
                    a
                    for a in applications
                    if a.get("pid") == args.pid and a.get("started_at") == args.expected_started_at
                ]
            elif args.app is not None:
                label = args.app.strip().casefold()
                matches = [
                    a
                    for a in applications
                    if label
                    in {str(a.get("bundle_id", "")).casefold(), str(a.get("name", "")).casefold()}
                ]
            else:
                matches = [a for a in applications if a.get("active") is True]
            if len(matches) != 1:
                raise BridgeError(
                    "keyboard_application_ambiguous"
                    if matches
                    else "keyboard_application_unavailable",
                    "Choose one running program by exact name, bundle ID or PID generation",
                )
            app = dict(matches[0])
        selected = {"pid": app["pid"], "expected_started_at": app["started_at"]}
        if app.get("active") is not True:
            if args.app is None and args.pid is None:
                raise BridgeError("keyboard_application_changed", "Foreground program changed")

            def focus_send():
                authorize("app.focus")
                turn.mark_attempted()

            focused = await k.transport.request(
                "app.focus",
                {"expected_pid": app["pid"], "expected_start": f"{app['started_at']:.6f}"},
                principal=principal,
                before_send=focus_send,
            )
            if focused.get("active_observed") is not True:
                try:
                    async with asyncio.timeout(_FOCUS_OBSERVATION_TIMEOUT):
                        while True:
                            await asyncio.sleep(_FOCUS_OBSERVATION_INTERVAL)
                            page = await read("apps.list", {"limit": 1000})
                            if page.get("eof") is not True:
                                raise BridgeError(
                                    "keyboard_catalog_incomplete",
                                    "Running program list is incomplete",
                                )
                            current = [
                                a for a in page["applications"] if a.get("pid") == app["pid"]
                            ]
                            if len(current) != 1 or any(
                                current[0].get(key) != app.get(key)
                                for key in _APPLICATION_IDENTITY_FIELDS
                            ):
                                raise BridgeError(
                                    "keyboard_application_changed",
                                    "Program identity changed during activation",
                                )
                            if current[0].get("active") is True:
                                break
                except TimeoutError as error:
                    raise BridgeError(
                        "keyboard_focus_unconfirmed", "Program activation was not confirmed"
                    ) from error
        system_action = args.action
        if args.scope == "auto" and possible_system_shortcut(args.key, args.modifiers):
            inventory = await read(
                "keyboard.system_inventory",
                {"key": args.key.model_dump(exclude_none=True), "modifiers": args.modifiers},
            )
            system_action = registered_system_action(inventory, args.key, args.modifiers)
        if args.scope == "system" or system_action is not None:
            operation = "keyboard.system_key"
            request = KeyboardSystemKeyInput(
                scope="system",
                target=selected,
                action=system_action,
                key=None if system_action is not None else args.key,
                modifiers=[]
                if system_action is not None and args.action is None
                else args.modifiers,
                repeat=args.repeat,
            )
            result = await k.execute_in_turn(
                {**task, "operation": operation},
                request,
                observe,
                turn,
                progress,
                before_send=authorize,
            )
            if not system_receipt_verified(result, action=system_action, repeat=args.repeat):
                raise UncertainExecution(
                    "keyboard_control_unknown", "System key receipt is incomplete; no replay"
                )
            return {
                **result,
                "automatic_target": True,
                "resolved_application": app,
                "native_operation": operation,
                "automatic_retry": False,
            }
        inspected = await read("keyboard.inspect", selected)
        target = inspected["target"]
        observed = inspected["application"]
        if (
            target.get("pid") != app["pid"]
            or target.get("expected_started_at") != app["started_at"]
            or any(observed.get(key) != app.get(key) for key in _APPLICATION_IDENTITY_FIELDS)
            or (expected_application is not None and observed.get("active") is not True)
        ):
            raise BridgeError("keyboard_application_changed", "Resolved program identity changed")
        if args.text is not None:
            operation = "keyboard.text"
            request = KeyboardTextInput(target=target, text=args.text, submit=args.submit)
        elif args.modifiers:
            operation = "keyboard.chord"
            request = KeyboardChordInput(
                target=target, key=args.key, modifiers=args.modifiers, repeat=args.repeat
            )
        else:
            operation = "keyboard.key"
            request = KeyboardKeyInput(target=target, key=args.key, repeat=args.repeat)
        await observe(
            {
                "evidence_type": "automatic_keyboard_target_bound",
                "resolved_application": observed,
                "native_operation": operation,
                "input_attempted": False,
                "automatic_retry": False,
            }
        )
        result = await k.execute_in_turn(
            {**task, "operation": operation},
            request,
            observe,
            turn,
            progress,
            before_send=authorize,
        )
        if operation != "keyboard.text" and result.get("post_calls_returned") != 2 * args.repeat:
            raise UncertainExecution(
                "keyboard_control_unknown", "Native key receipt is incomplete; no replay"
            )
        return {
            **result,
            "automatic_target": True,
            "resolved_application": observed,
            "native_operation": operation,
            "automatic_retry": False,
        }
