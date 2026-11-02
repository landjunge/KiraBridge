"""Keyboard orchestration through existing tasks, desktop transaction and worker."""

import asyncio
import base64

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, canonical
from kirabridge.keyboard_models import KeyboardChordInput, KeyboardKeyInput, KeyboardTextInput
from kirabridge.keyboard_text import native_frame_bytes, plan_text

KEYBOARD_INPUTS = {
    "keyboard.key": KeyboardKeyInput,
    "keyboard.chord": KeyboardChordInput,
    "keyboard.text": KeyboardTextInput,
}


class KeyboardManager:
    def __init__(self, *, transport, desktop_input, authorize):
        self.transport, self.desktop_input, self.authorize = transport, desktop_input, authorize

    async def execute(self, task, args, running, progress=None):
        principal, operation = task["principal"], task["operation"]
        arguments = args.model_dump(exclude_none=True)
        if operation == "keyboard.text":
            plan = plan_text(args, task_id=task["id"], principal=principal)
            manifest = plan.manifest
            begin = {
                **manifest,
                "binding_json": canonical(
                    {k: v for k, v in manifest.items() if k != "transfer_id"}
                ),
            }
            native_frame_bytes("keyboard.text.begin", begin, principal=principal)
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
            if operation == "keyboard.text":
                return await self._text(task, plan, begin, turn, progress)
            return await self.send_pair_in_turn(principal, operation, arguments, turn)

    async def send_pair_in_turn(self, principal, operation, arguments, turn, *, before_send=None):
        """Caller owns the desktop lease; authorize and mark only at transport send."""

        def prepare():
            if before_send is not None:
                before_send()
            else:
                self.authorize(principal, operation)
            turn.mark_attempted()

        return await self.transport.request(
            operation, arguments, principal=principal, before_send=prepare
        )

    async def _text(self, task, plan, begin, turn, progress):
        principal = task["principal"]
        manifest = plan.manifest
        identifier = manifest["transfer_id"]
        began, committed = False, False

        async def send(operation, arguments, *, commit=False):
            def before_send():
                nonlocal committed
                self.authorize(principal, "keyboard.text")
                if commit:
                    turn.mark_attempted()
                    committed = True

            return await self.transport.request(
                operation,
                arguments,
                principal=principal,
                before_send=before_send,
            )

        def acknowledgement(reply, state):
            if (
                reply.get("transfer_id") != identifier
                or reply.get("state") != state
                or reply.get("input_attempted") is not False
            ):
                raise BridgeError(
                    "keyboard_stage_reply_invalid",
                    "Native staging was not acknowledged; no commit sent",
                )

        try:
            reply = await send("keyboard.text.begin", begin)
            began = True
            acknowledgement(reply, "accepted")
            received = 0
            for index, packet in enumerate(plan.chunks):
                received += len(base64.b64decode(packet["data_b64"], validate=True)) // 2
                reply = await send("keyboard.text.chunk", packet)
                acknowledgement(reply, "received")
                if (
                    type(reply.get("received_chunks")) is not int
                    or reply["received_chunks"] != index + 1
                    or type(reply.get("received_utf16_units")) is not int
                    or reply["received_utf16_units"] != received
                ):
                    raise BridgeError(
                        "keyboard_stage_reply_invalid", "Native chunk counts differ; no commit sent"
                    )
            if progress is not None:
                await progress(
                    {
                        "evidence_type": "native_keyboard_commit_attempt",
                        "transfer_id": identifier,
                        "automatic_retry": False,
                    }
                )
            result = await send("keyboard.text.commit", {"transfer_id": identifier}, commit=True)
            if (
                result.get("transfer_id") != identifier
                or result.get("task_id") != task["id"]
                or result.get("staging_verified") is not True
                or result.get("text_verified") is not True
                or result.get("selection_verified") is not True
                or result.get("return_posted") is not manifest["submit"]
                or result.get("text_sha256") != manifest["sha256"]
            ):
                raise UncertainExecution(
                    "keyboard_text_unknown", "Native commit outcome is not verified; no replay"
                )
            return result
        except BaseException:
            child = self.transport.process
            if began and not committed and child is not None and child.returncode is None:
                try:
                    async with asyncio.timeout(1):
                        # Owner-only memory cleanup, even if input permission was revoked.
                        await self.transport.request(
                            "keyboard.text.abort", {"transfer_id": identifier}, principal=principal
                        )
                except BaseException:
                    pass  # Preserve the original error; native staging also has an expiry.
            raise
