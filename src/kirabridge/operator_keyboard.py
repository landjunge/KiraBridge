"""Explicit local keyboard UI intents through existing RPC/tasks and decisions.

GET/status never approves or dispatches. An incomplete preparatory stage halts
the inline POST workflow permanently; a later completion does not resume it.
"""

import re
import uuid

from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.keyboard_control import KeyboardControlInput
from kirabridge.keyboard_profile_manager import PROFILE_INPUTS, ActionName
from kirabridge.keyboard_profiles import KeyboardProfile, Revision, Slug
from kirabridge.permissions import decision
from kirabridge.platform_adapters.macos.control_models import ApplicationTargetInput
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS
from kirabridge.security_manager import request_hash

ALLOWED = {
    "apps.list": SYSTEM_INPUTS["apps.list"],
    "keyboard.control": KeyboardControlInput,
    **PROFILE_INPUTS,
    "keyboard.shortcuts.discover": SYSTEM_INPUTS["keyboard.shortcuts.discover"],
}
FINAL = {"completed", "failed", "cancelled", "unknown", "blocked", "rejected"}
STAGES = {
    "profile": {"keyboard.profiles.get"},
    "focus": {"app.focus"},
    "inspect": {"keyboard.inspect"},
    "main": {*ALLOWED, "keyboard.action"},
}
DEFINITE_FAILURES = {
    "keyboard_ui_permission_denied",
    "keyboard_ui_profile_conflict",
    "keyboard_ui_candidate_only",
}
SCOPE = r"ui-keyboard-([a-f0-9]{32})-(main|profile|focus|inspect)"


class RunProfileInput(ApplicationTargetInput):
    profile_id: Slug
    expected_revision: Revision
    action: ActionName


class OperatorKeyboard:
    def __init__(self, control, decisions):
        self.control, self.decisions = control, decisions

    def _require(self, operations):
        config = self.control.config()
        if any(not decision(config, "local", operation)["authorized"] for operation in operations):
            raise BridgeError(
                "keyboard_ui_permission_denied", "Keyboard UI requires existing capabilities"
            )

    @staticmethod
    def _scope(task_id):
        match = re.fullmatch(SCOPE, task_id) if isinstance(task_id, str) else None
        if match is None:
            raise BridgeError("invalid_request", "Not a keyboard UI task")
        return match.groups()

    def _owned(self, task, task_id):
        _, stage = self._scope(task_id)
        if (
            task.get("id") != task_id
            or task.get("principal") != "local"
            or task.get("operation") not in STAGES[stage]
        ):
            raise BridgeError("keyboard_task_mismatch", "Task is outside the keyboard UI scope")
        return task

    async def _current(self, task_id):
        return self._owned(await self.control.rpc("task_get", {"task_id": task_id}), task_id)

    def _workflow(self, task, nonce, stage):
        observed = self.control.actions.observe("keyboard-" + nonce)
        saved = observed.get("result") if observed else None
        saved_task = saved.get("task") if isinstance(saved, dict) else None
        stopped = (
            stage != "main" and isinstance(saved_task, dict) and saved_task.get("id") == task["id"]
        )
        primary = stage == "main"
        return {
            **task,
            "ui_stage": stage,
            "ui_primary": primary,
            "ui_incomplete": not primary,
            "ui_halted": bool(stopped or primary and task["state"] in FINAL - {"completed"}),
            "ui_workflow_status": "primary" if primary else "halted" if stopped else "unconfirmed",
        }

    async def status(self, task_id, *, wait_seconds=0):
        nonce, stage = self._scope(task_id)
        # A lost POST can stop before the primary task exists. Read only the
        # latest own preparation; never turn its completion into an action.
        candidates = [stage] if stage != "main" else ["main", "inspect", "focus", "profile"]
        for candidate in candidates:
            current_id = f"ui-keyboard-{nonce}-{candidate}"
            try:
                task = await self._current(current_id)
                break
            except BridgeError as error:
                if error.code != "not_found":
                    raise
        else:
            return {
                "id": task_id,
                "state": "unknown",
                "error": {"code": "keyboard_task_unconfirmed"},
                "ui_stage": stage,
                "ui_primary": stage == "main",
                "ui_halted": False,
                "ui_incomplete": True,
                "existence_confirmed": False,
                "ui_workflow_status": "unconfirmed",
            }
        target, processed = f"ui-keyboard:{nonce}:{candidate}", 0
        try:
            delivery = await self.control.rpc(
                "completion_receive",
                {
                    "target": target,
                    "source_id": current_id,
                    "limit": 20,
                    "wait_seconds": 0 if task["state"] in FINAL else wait_seconds,
                },
                timeout=12,
            )
            notices = delivery.get("notices", [])
            for notice in notices:
                payload = notice.get("payload", {})
                if (
                    notice.get("target") != target
                    or payload.get("task_id") != current_id
                    or payload.get("source") != "task"
                ):
                    raise BridgeError("completion_scope_mismatch", "Foreign keyboard completion")
                task = await self._current(current_id)
                if task["state"] not in FINAL:
                    break
                await self.control.rpc(
                    "completion_ack", {"notice_id": notice["id"], "receipt": notice["receipt"]}
                )
                processed += 1
            task["ui_completion"] = {
                "pending": len(notices) == 20 or processed < len(notices),
                "processed": processed,
            }
        except BridgeError as error:
            task["ui_completion"] = {
                "pending": True,
                "processed": processed,
                "error": {"code": error.code},
            }
        return self._workflow(task, nonce, candidate)

    async def _stage(self, nonce, stage, operation, arguments):
        self._require([operation])
        task_id = f"ui-keyboard-{nonce}-{stage}"
        request = TaskRequest(
            task_id=task_id, idempotency_key=task_id, operation=operation, arguments=arguments
        )
        task = await self.control.rpc(
            "task_request",
            {"request": request.model_dump(), "completion_target": f"ui-keyboard:{nonce}:{stage}"},
        )
        self._owned(task, task_id)
        if task.get("state") == "created":
            detail = self.decisions.detail(task_id)
            actual = self._owned(detail["task"], task_id)
            if (
                actual.get("operation") != operation
                or actual.get("args") != arguments
                or detail.get("request_hash") != request_hash(request)
            ):
                raise BridgeError("review_conflict", "UI approval request differs")
            self._require([operation])
            self.decisions.decide(task_id, "approve", detail["request_hash"])
        return await self.status(task_id, wait_seconds=8)

    async def _run(self, nonce, operation, arguments):
        if operation != "run_profile":
            self._require([operation])
            return await self._stage(nonce, "main", operation, arguments)
        self._require(["keyboard.profiles.get", "app.focus", "keyboard.inspect", "keyboard.action"])
        task = await self._stage(
            nonce, "profile", "keyboard.profiles.get", {"profile_id": arguments["profile_id"]}
        )
        if task["state"] != "completed":
            return task
        result = task["result"]
        if result.get("revision") != arguments["expected_revision"]:
            raise BridgeError("keyboard_ui_profile_conflict", "Selected profile revision changed")
        profile = KeyboardProfile.model_validate(result["profile"])
        if profile.id != arguments["profile_id"]:
            raise BridgeError("keyboard_ui_profile_conflict", "Selected profile ID differs")
        action = profile.actions.get(arguments["action"])
        if action is None or action.candidate_only:
            raise BridgeError("keyboard_ui_candidate_only", "Choose an explicit configured action")
        task = await self._stage(
            nonce,
            "focus",
            "app.focus",
            {
                "expected_pid": arguments["pid"],
                "expected_start": f"{arguments['expected_started_at']:.6f}",
            },
        )
        if task["state"] != "completed":
            return task
        task = await self._stage(
            nonce,
            "inspect",
            "keyboard.inspect",
            {key: arguments[key] for key in ("pid", "expected_started_at")},
        )
        if task["state"] != "completed":
            return task
        target = task["result"]["target"]
        if (
            target.get("pid") != arguments["pid"]
            or target.get("expected_started_at") != arguments["expected_started_at"]
        ):
            raise BridgeError("keyboard_target_changed", "Focused target generation changed")
        return await self._stage(
            nonce,
            "main",
            "keyboard.action",
            {
                "target": target,
                **{key: arguments[key] for key in ("profile_id", "expected_revision", "action")},
            },
        )

    async def request(self, value):
        try:
            if not isinstance(value, dict) or set(value) != {"id", "operation", "args"}:
                raise ValueError("Invalid keyboard intent")
            nonce = uuid.UUID(value["id"]).hex
            if str(uuid.UUID(hex=nonce)) != value["id"]:
                raise ValueError("Canonical UUID required")
            operation = value["operation"]
            model = RunProfileInput if operation == "run_profile" else ALLOWED[operation]
            arguments = model.model_validate(value["args"]).model_dump(
                exclude_none=True, by_alias=True
            )
        except (KeyError, ValueError, TypeError, AttributeError, ValidationError) as error:
            raise BridgeError("invalid_request", "Invalid keyboard UI request") from error
        intent = {
            "action_id": "keyboard-" + nonce,
            "service": "keyboard",
            "action": operation,
            "args": arguments,
        }

        async def dispatch(*_):
            task = await self._run(nonce, operation, arguments)
            return {"state": task["state"], "task": task}

        result = await self.control.actions.execute(intent, dispatch)
        definite = (
            result.get("state") == "failed"
            and result.get("error", {}).get("code") in DEFINITE_FAILURES
        )
        task = result.get(
            "task",
            {
                "id": f"ui-keyboard-{nonce}-main",
                "state": "failed" if definite else "unknown",
                "result": None,
                "error": result.get("error"),
                "ui_halted": definite,
                "ui_incomplete": True,
                "ui_workflow_status": "halted" if definite else "unconfirmed",
            },
        )
        if result.get("task"):
            _, stage = self._scope(task["id"])
            task = self._workflow(task, nonce, stage)
        return {
            "request_id": value["id"],
            "task": task,
            "status_url": f"/api/control/keyboard/task/ui-keyboard-{nonce}-main",
        }
