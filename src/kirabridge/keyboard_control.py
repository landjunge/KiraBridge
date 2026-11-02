"""Profile-free keyboard intents; discover once, bind freshly, never replay."""

import asyncio

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


class KeyboardControlInput(Input):
    app: str | None = Field(default=None, min_length=1, max_length=255)
    pid: int | None = Field(default=None, gt=0, le=2**31 - 1)
    expected_started_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_UTF8_BYTES)
    key: KeyboardKey | None = None
    modifiers: list[Modifier] = Field(default_factory=list, max_length=4)
    submit: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if (self.text is None) == (self.key is None):
            raise ValueError("Choose text or one key")
        if self.text is not None:
            literal_text(self.text)
            if self.modifiers:
                raise ValueError("Modifiers belong to a key, not literal text")
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
        # Validate again; callers cannot mutate a previously validated intent.
        args = KeyboardControlInput.model_validate(args.model_dump(exclude_none=True))
        k, principal = self.keyboard, task["principal"]

        def authorize(operation="keyboard.control"):
            k.authorize(principal, "keyboard.control")
            k.authorize(principal, operation)

        async def read(operation, arguments):
            authorize(operation)
            return await k.transport.request(
                operation, arguments, principal=principal, before_send=lambda: authorize(operation)
            )

        async def observe(evidence):
            if progress is not None:
                await progress(evidence)

        async with k.desktop_input.transaction() as turn:
            authorize()
            await running(
                {"evidence_type": "automatic_keyboard_resolution", "automatic_retry": False}
            )
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
            inspected = await read("keyboard.inspect", selected)
            target = inspected["target"]
            observed = inspected["application"]
            if (
                target.get("pid") != app["pid"]
                or target.get("expected_started_at") != app["started_at"]
                or any(
                    observed.get(key) != app.get(key)
                    for key in _APPLICATION_IDENTITY_FIELDS
                )
            ):
                raise BridgeError(
                    "keyboard_application_changed", "Resolved program identity changed"
                )
            if args.text is not None:
                operation = "keyboard.text"
                request = KeyboardTextInput(target=target, text=args.text, submit=args.submit)
            elif args.modifiers:
                operation = "keyboard.chord"
                request = KeyboardChordInput(target=target, key=args.key, modifiers=args.modifiers)
            else:
                operation = "keyboard.key"
                request = KeyboardKeyInput(target=target, key=args.key)
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
            if operation != "keyboard.text" and result.get("post_calls_returned") != 2:
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
