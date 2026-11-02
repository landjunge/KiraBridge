"""Keyboard orchestration through existing tasks, desktop transaction and worker."""

from kirabridge.keyboard_models import KeyboardKeyInput

KEYBOARD_INPUTS = {"keyboard.key": KeyboardKeyInput}


class KeyboardManager:
    def __init__(self, *, transport, desktop_input, authorize):
        self.transport, self.desktop_input, self.authorize = transport, desktop_input, authorize

    async def execute(self, task, args, running):
        principal, operation = task["principal"], task["operation"]
        async with self.desktop_input.transaction() as turn:
            self.authorize(principal, operation)
            await running(
                {
                    "evidence_type": "native_keyboard_attempt",
                    "operation": operation,
                    "automatic_retry": False,
                    "scope": "native request; no application acknowledgement",
                }
            )
            turn.mark_attempted()
            return await self.transport.request(
                operation,
                args.model_dump(exclude_none=True),
                principal=principal,
                before_send=lambda: self.authorize(principal, operation),
            )
