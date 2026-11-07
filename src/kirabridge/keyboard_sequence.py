"""Ordered physical key events in one durable task; never a text replacement."""

import hashlib

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import Input, UncertainExecution
from kirabridge.keyboard_control import KeyboardControlInput
from kirabridge.keyboard_models import KeyboardKey, Modifier

MAX_SEQUENCE_KEYS = 32


class KeyboardStroke(Input):
    key: KeyboardKey
    modifiers: list[Modifier] = Field(default_factory=list, max_length=5)
    repeat: int = Field(default=1, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def unique_modifiers(self):
        if len(self.modifiers) != len(set(self.modifiers)):
            raise ValueError("Modifiers must be unique")
        return self


class KeyboardSequenceInput(Input):
    app: str | None = Field(default=None, min_length=1, max_length=255)
    pid: int | None = Field(default=None, gt=0, le=2**31 - 1)
    expected_started_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    steps: list[KeyboardStroke] = Field(min_length=1, max_length=MAX_SEQUENCE_KEYS)

    @model_validator(mode="after")
    def coherent(self):
        # Keep selection validation identical to a single control request.
        KeyboardControlInput(
            app=self.app,
            pid=self.pid,
            expected_started_at=self.expected_started_at,
            key=self.steps[0].key,
            scope="app",
        )
        if sum(step.repeat for step in self.steps) > MAX_SEQUENCE_KEYS:
            raise ValueError("A sequence may post at most 32 key-down/key-up pairs")
        return self


SEQUENCE_INPUTS = {"keyboard.sequence": KeyboardSequenceInput}


class KeyboardSequence:
    def __init__(self, control):
        self.control = control

    async def execute(self, task, args, running, progress=None):
        args = KeyboardSequenceInput.model_validate(args.model_dump(exclude_none=True))
        keyboard = self.control.keyboard
        keyboard.authorize(task["principal"], "keyboard.sequence")
        completed, bound_app = [], None

        async def emit(evidence):
            if progress is not None:
                await progress(evidence)

        async with keyboard.desktop_input.transaction() as turn:
            await running(
                {
                    "evidence_type": "keyboard_sequence_started",
                    "requested_steps": len(args.steps),
                    "completed_steps": 0,
                    "physical_key_events": True,
                    "automatic_retry": False,
                }
            )
            for index, step in enumerate(args.steps):
                step_id = "ks_" + hashlib.sha256(f"{task['id']}:{index}".encode()).hexdigest()[:32]

                async def observe(evidence, index=index, step_id=step_id):
                    await emit(
                        {
                            "evidence_type": "keyboard_sequence_step",
                            "step_index": index,
                            "step_id": step_id,
                            "completed_steps": len(completed),
                            "requested_steps": len(args.steps),
                            "stage": evidence,
                            "automatic_retry": False,
                        }
                    )

                selection = (
                    {"pid": bound_app["pid"], "expected_started_at": bound_app["started_at"]}
                    if bound_app is not None
                    else {
                        "app": args.app,
                        "pid": args.pid,
                        "expected_started_at": args.expected_started_at,
                    }
                )
                request = KeyboardControlInput(
                    **selection,
                    key=step.key,
                    modifiers=step.modifiers,
                    repeat=step.repeat,
                    scope="app",
                )
                try:
                    result = await self.control.execute_in_turn(
                        {**task, "id": step_id, "operation": "keyboard.control"},
                        request,
                        observe,
                        turn,
                        observe,
                        expected_application=bound_app,
                        authorization_operation="keyboard.sequence",
                    )
                    bound_app = result["resolved_application"]
                    completed.append(
                        {
                            "index": index,
                            "step_id": step_id,
                            "post_calls_returned": result["post_calls_returned"],
                            "native_operation": result["native_operation"],
                        }
                    )
                    await emit(
                        {
                            "evidence_type": "keyboard_sequence_step_completed",
                            "step_index": index,
                            "step_id": step_id,
                            "completed_steps": len(completed),
                            "requested_steps": len(args.steps),
                            "post_calls_returned": sum(r["post_calls_returned"] for r in completed),
                            "automatic_retry": False,
                        }
                    )
                except Exception as cause:
                    if completed or turn.attempted:
                        error = UncertainExecution(
                            "keyboard_sequence_partial",
                            "Sequence stopped; reconcile original task and receiver; no replay",
                        )
                        error.provider_error = {
                            "step_index": index,
                            "completed_steps": len(completed),
                            "requested_steps": len(args.steps),
                            "cause_code": getattr(cause, "code", "execution_error"),
                            "automatic_retry": False,
                        }
                        raise error from cause
                    raise
        return {
            "requested_steps": len(args.steps),
            "completed_steps": len(completed),
            "post_calls_returned": sum(r["post_calls_returned"] for r in completed),
            "physical_key_events": True,
            "app_processing_confirmed": False,
            "automatic_retry": False,
            "resolved_application": bound_app,
            "steps": completed,
        }
