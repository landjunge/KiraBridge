"""Keyboard orchestration through existing tasks, desktop transaction and worker."""

import asyncio
import base64

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, canonical
from kirabridge.keyboard_models import (
    KeyboardChordInput,
    KeyboardInput,
    KeyboardInspectInput,
    KeyboardKeyInput,
    KeyboardTarget,
    KeyboardTextInput,
)
from kirabridge.keyboard_text import native_frame_bytes, plan_text

KEYBOARD_INPUTS = {
    "keyboard.input": KeyboardInput,
    "keyboard.key": KeyboardKeyInput,
    "keyboard.chord": KeyboardChordInput,
    "keyboard.text": KeyboardTextInput,
}


class KeyboardManager:
    def __init__(self, *, transport, desktop_input, authorize):
        self.transport, self.desktop_input, self.authorize = transport, desktop_input, authorize

    async def execute(self, task, args, running, progress=None):
        principal, operation = task["principal"], task["operation"]
        if operation == "keyboard.input":
            return await self._direct(task, args, running, progress)
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

    async def _direct(self, task, args, running, progress):
        """Resolve once, then reuse native guards without profiles or retargeting."""
        args = KeyboardInput.model_validate(args.model_dump(warnings=False))
        principal, completed = task["principal"], 0

        async def observe(operation, arguments):
            def before_send():
                self.authorize(principal, "keyboard.input")
                self.authorize(principal, operation)

            before_send()
            return await self.transport.request(
                operation, arguments, principal=principal, before_send=before_send
            )

        def binding(snapshot):
            try:
                target = KeyboardTarget.model_validate(snapshot["target"]).model_dump()
                window = snapshot["window_token"]
                if not isinstance(window, str) or not window:
                    raise ValueError("Missing window token")
                return tuple(
                    target[name]
                    for name in (
                        "pid",
                        "expected_started_at",
                        "target_token",
                        "helper_pid",
                        "worker_generation",
                    )
                ) + (window,)
            except (KeyError, TypeError, ValueError) as error:
                raise BridgeError(
                    "keyboard_snapshot_invalid", "Native keyboard target is incomplete"
                ) from error

        async with self.desktop_input.transaction() as turn:
            catalog = await observe("apps.list", {"limit": 1000})
            rows = catalog.get("applications")
            if not isinstance(rows, list) or catalog.get("truncated") is not False:
                raise BridgeError(
                    "keyboard_application_catalog_incomplete",
                    "Application catalog is incomplete; no target was selected",
                )
            matches = [
                row
                for row in rows
                if isinstance(row, dict)
                and (
                    row.get("active") is True
                    if args.app is None
                    else args.app.casefold()
                    in {
                        str(row.get("name", "")).casefold(),
                        str(row.get("bundle_id", "")).casefold(),
                    }
                )
            ]
            if len(matches) != 1:
                raise BridgeError(
                    "keyboard_application_ambiguous" if matches else "keyboard_application_missing",
                    "Select one running application by exact name or bundle identifier",
                )
            application = matches[0]
            identity = KeyboardInspectInput(
                pid=application.get("pid"), expected_started_at=application.get("started_at")
            ).model_dump()
            try:
                initial = await observe("keyboard.inspect", identity)
            except BridgeError as error:
                # This exact native refusal follows the existing protected-process
                # checks. Secure/unsupported fields never trigger focus or fallback.
                if args.app is None or error.code != "keyboard_not_frontmost":
                    raise

                def before_focus():
                    self.authorize(principal, "keyboard.input")
                    self.authorize(principal, "app.focus")
                    turn.mark_attempted()

                before_focus()
                await self.transport.request(
                    "app.focus",
                    {
                        "expected_pid": identity["pid"],
                        "expected_start": f"{identity['expected_started_at']:.6f}",
                    },
                    principal=principal,
                    before_send=before_focus,
                )
                deadline = asyncio.get_running_loop().time() + 2
                while True:
                    try:
                        initial = await observe("keyboard.inspect", identity)
                        break
                    except BridgeError as error:
                        if (
                            error.code != "keyboard_not_frontmost"
                            or asyncio.get_running_loop().time() >= deadline
                        ):
                            raise
                        await asyncio.sleep(0.05)

            expected_binding = binding(initial)
            if initial["target"]["pid"] != identity["pid"] or (
                initial["target"]["expected_started_at"] != identity["expected_started_at"]
            ):
                raise BridgeError(
                    "keyboard_target_changed", "Selected application identity changed"
                )
            await running(
                {
                    "evidence_type": "native_keyboard_direct_bound",
                    "operation": "keyboard.input",
                    "application": application,
                    "target": initial["target"],
                    "window_token": initial["window_token"],
                    "requested_count": args.repeat,
                    "completed_count": 0,
                    "input_attempted": False,
                    "automatic_retry": False,
                    "profile_required": False,
                }
            )
            current, total_posts = initial, 0
            try:
                if args.text is not None:
                    request = KeyboardTextInput(
                        target=initial["target"], text=args.text * args.repeat, submit=args.submit
                    )
                    plan = plan_text(request, task_id=task["id"], principal=principal)
                    manifest = plan.manifest
                    begin = {
                        **manifest,
                        "binding_json": canonical(
                            {k: v for k, v in manifest.items() if k != "transfer_id"}
                        ),
                    }
                    result = await self._text(
                        task, plan, begin, turn, progress, authorization_operation="keyboard.input"
                    )
                    completed = args.repeat
                else:
                    operation = "keyboard.chord" if args.modifiers else "keyboard.key"
                    for index in range(args.repeat):
                        if index:
                            current = await observe("keyboard.inspect", identity)
                        if binding(current) != expected_binding:
                            raise BridgeError(
                                "keyboard_target_changed",
                                "Focused keyboard field or worker changed",
                            )
                        payload = {
                            "target": current["target"],
                            "key": args.key.model_dump(exclude_none=True),
                        }
                        if args.modifiers:
                            payload["modifiers"] = list(args.modifiers)

                        def before_pair():
                            self.authorize(principal, "keyboard.input")
                            self.authorize(principal, operation)

                        result = await self.send_pair_in_turn(
                            principal, operation, payload, turn, before_send=before_pair
                        )
                        if result.get("input_attempted") is not True or (
                            type(result.get("post_calls_returned")) is not int
                            or result["post_calls_returned"] != 2
                        ):
                            raise UncertainExecution(
                                "keyboard_input_unknown",
                                "Native key dispatch is unverified; no replay",
                            )
                        completed += 1
                        total_posts += 2
                        if progress is not None:
                            await progress(
                                {
                                    "evidence_type": "native_keyboard_direct_progress",
                                    "requested_count": args.repeat,
                                    "completed_count": completed,
                                    "post_calls_returned": total_posts,
                                    "input_attempted": True,
                                    "app_processing_confirmed": False,
                                    "automatic_retry": False,
                                }
                            )
                final = await observe("keyboard.inspect", identity)
                if binding(final) != expected_binding:
                    raise BridgeError(
                        "keyboard_target_changed",
                        "Focused keyboard field or worker changed after input",
                    )
                return {
                    **result,
                    "application": application,
                    "requested_count": args.repeat,
                    "completed_count": completed,
                    "profile_required": False,
                    "post_calls_returned": total_posts
                    if args.text is None
                    else result.get("post_calls_returned", 0),
                    "app_processing_confirmed": result.get("app_processing_confirmed") is True,
                    "field_change_observed": initial.get("field") != final.get("field"),
                    "observed_field": final.get("field"),
                    "target": final["target"],
                    "window_token": final["window_token"],
                    "automatic_retry": False,
                }
            except BridgeError as error:
                if completed:
                    raise UncertainExecution(
                        "keyboard_input_partial_unknown",
                        f"{completed} of {args.repeat} input repetitions dispatched; "
                        f"stopped: {error}",
                    ) from error
                raise

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

    async def _text(
        self, task, plan, begin, turn, progress, *, authorization_operation="keyboard.text"
    ):
        principal = task["principal"]
        manifest = plan.manifest
        identifier = manifest["transfer_id"]
        began, committed = False, False

        async def send(operation, arguments, *, commit=False):
            def before_send():
                nonlocal committed
                if authorization_operation != "keyboard.text":
                    self.authorize(principal, authorization_operation)
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
