"""Keyboard orchestration through existing tasks, desktop transaction and worker."""

from kirabridge.bridge_core.models import BridgeError
from kirabridge.keyboard_models import KeyboardChordInput, KeyboardKeyInput, KeyboardTextInput
from kirabridge.keyboard_text import native_frame_bytes

KEYBOARD_INPUTS = {
    "keyboard.key": KeyboardKeyInput,
    "keyboard.chord": KeyboardChordInput,
    "keyboard.text": KeyboardTextInput,
}


class KeyboardManager:
    def __init__(self, *, transport, desktop_input, authorize):
        self.transport, self.desktop_input, self.authorize = transport, desktop_input, authorize

    async def execute(self, task, args, running):
        principal, operation = task["principal"], task["operation"]
        arguments = args.model_dump(exclude_none=True)
        if operation == "keyboard.text":
            if args.submit:
                raise BridgeError(
                    "keyboard_submit_pending", "Transactional Return is not enabled yet"
                )
            try:
                native_frame_bytes(operation, arguments, principal=principal)
            except ValueError:
                raise BridgeError(
                    "keyboard_staging_pending",
                    "Long native text staging is not enabled yet; no input sent",
                ) from None
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
                arguments,
                principal=principal,
                before_send=lambda: self.authorize(principal, operation),
            )
