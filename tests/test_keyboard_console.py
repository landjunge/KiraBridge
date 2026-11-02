"""Keyboard Console RPC, exact approvals and HTTP guards without GUI or services."""

import asyncio
import copy
import uuid

import httpx
import pytest

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.keyboard_profiles import KeyboardProfileStore, fcntl
from kirabridge.operator_application import operator_application
from kirabridge.operator_keyboard import OperatorKeyboard
from kirabridge.security_manager import request_hash

IDENTITY = "12345678-1234-4234-8234-123456789012"
TARGET = {
    "pid": 123,
    "expected_started_at": 1700000000.125,
    "target_token": "a" * 32,
    "helper_pid": 456,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}
CAPS = [
    "keyboard.execute",
    "keyboard.profiles.read",
    "keyboard.profiles.manage",
    "keyboard.shortcuts.read",
]


def profile(provenance="user"):
    return {
        "id": "editor",
        "app": {"bundle_id": "org.example.Editor"},
        "actions": {
            "select_all": {
                "key": {"character": "a"},
                "modifiers": ["command"],
                "provenance": provenance,
            }
        },
    }


def value(operation="keyboard.profiles.list", args=None):
    return {"id": IDENTITY, "operation": operation, "args": args or {}}


def run_args():
    return {
        "pid": 123,
        "expected_started_at": 1700000000.125,
        "profile_id": "editor",
        "expected_revision": "c" * 64,
        "action": "select_all",
    }


class RPC:
    def __init__(self):
        self.calls, self.tasks, self.requests, self.targets, self.notices, self.approvals = (
            [],
            {},
            {},
            {},
            {},
            [],
        )
        self.stop = None
        self.profile = profile()
        self.revision = "c" * 64

    def result(self, operation, args):
        if operation == "keyboard.profiles.get":
            return {"profile": self.profile, "revision": self.revision, "profile_id": "editor"}
        if operation == "keyboard.inspect":
            return {"target": TARGET, "effect": "none"}
        if operation == "app.focus":
            return {
                "activation_requested": True,
                "active_observed": True,
                "pid": 123,
                "application_start": "1700000000.125000",
            }
        return {"effect": "none", "app_processing_confirmed": False}

    def finish(self, task_id):
        task = self.tasks[task_id]
        state = self.stop[1] if self.stop and task["operation"] == self.stop[0] else "completed"
        task.update(state=state, result=self.result(task["operation"], task["args"]))
        if state in {"completed", "failed", "unknown"}:
            self.notices[task_id] = [
                {
                    "id": "notice-" + task_id,
                    "receipt": "receipt-" + task_id,
                    "target": self.targets[task_id],
                    "payload": {"source": "task", "task_id": task_id},
                }
            ]

    def detail(self, task_id):
        return {
            "task": copy.deepcopy(self.tasks[task_id]),
            "request_hash": request_hash(self.requests[task_id]),
        }

    def decide(self, task_id, decision, hashed):
        assert decision == "approve" and hashed == request_hash(self.requests[task_id])
        self.approvals.append(task_id)
        self.finish(task_id)

    async def __call__(self, name, args, **kwargs):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "task_request":
            request = TaskRequest.model_validate(args["request"])
            self.requests[request.task_id] = request
            self.targets[request.task_id] = args["completion_target"]
            self.tasks[request.task_id] = {
                "id": request.task_id,
                "principal": "local",
                "operation": request.operation,
                "args": request.arguments,
                "state": "created",
                "result": None,
                "error": None,
            }
            return copy.deepcopy(self.tasks[request.task_id])
        if name == "task_get":
            if args["task_id"] not in self.tasks:
                raise BridgeError("not_found", "Missing task")
            return copy.deepcopy(self.tasks[args["task_id"]])
        if name == "completion_receive":
            notices = self.notices.get(args["source_id"], [])
            assert all(n["target"] == args["target"] for n in notices)
            return {"notices": copy.deepcopy(notices)}
        if name == "completion_ack":
            for task_id, notices in self.notices.items():
                if notices and notices[0]["id"] == args["notice_id"]:
                    assert notices[0]["receipt"] == args["receipt"]
                    self.notices[task_id] = []
                    return {"ack_scope": "consumer_processed"}
        raise AssertionError(name)


def console(bridge, config, monkeypatch):
    config.principals["local"].capabilities += CAPS
    key = "keyboard-console-" + "x" * 48
    app = ApprovalConsole(operator_application(bridge), key)
    rpc = RPC()
    backend = app.keyboard_console.service
    monkeypatch.setattr(backend.control, "rpc", rpc)
    backend.decisions = rpc
    headers = {"Authorization": "Bearer " + signed_token(key, "session"), "Origin": ORIGIN}
    return app, backend, rpc, headers


async def test_http_auth_csrf_allowlist_and_endpoint_specific_limit(bridge, config, monkeypatch):
    app, _, rpc, headers = console(bridge, config, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        path = "/api/control/keyboard/request"
        assert (await client.post(path, json=value())).status_code == 401
        assert (
            await client.post(
                path, headers={**headers, "Origin": "https://invalid.example"}, json=value()
            )
        ).status_code == 403
        assert (
            await client.post(
                path, headers={**headers, "Content-Type": "application/json"}, content=b" " * 32769
            )
        ).status_code == 413
        assert (
            await client.post(
                path, headers=headers, json=value("keyboard.key", {"key": {"named": "enter"}})
            )
        ).status_code == 400
        assert rpc.calls == []
        large = profile()
        large["actions"] = {"action_" + str(i): large["actions"]["select_all"] for i in range(60)}
        response = await client.post(
            path, headers=headers, json=value("keyboard.profiles.put", {"profile": large})
        )
        assert response.status_code == 200 and response.json()["task"]["state"] == "completed"
        response = await client.post(
            "/api/control/terminal/read",
            headers={**headers, "Content-Type": "application/json"},
            content=b" " * 5000,
        )
        assert response.status_code == 413  # Existing global limit is still 4096.


async def test_duplicate_posts_approve_exact_own_task_once_and_get_never_dispatches(
    bridge, config, monkeypatch
):
    app, backend, rpc, headers = console(bridge, config, monkeypatch)
    first = await backend.request(value())
    duplicate = await backend.request(value())
    assert duplicate == first and len(rpc.approvals) == 1
    with pytest.raises(BridgeError) as error:
        await backend.request(value("apps.list"))
    assert error.value.code == "idempotency_conflict"
    count = len([c for c in rpc.calls if c[0] == "task_request"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get(first["status_url"])).status_code == 401
        response = await client.get(first["status_url"], headers=headers)
        assert response.json()["task"]["state"] == "completed"
    assert len([c for c in rpc.calls if c[0] == "task_request"]) == count
    assert len([c for c in rpc.calls if c[0] == "completion_ack"]) == 1
    assert all(not n for n in rpc.notices.values())


async def test_missing_capability_and_foreign_approval_are_not_bypassed(
    bridge, config, monkeypatch
):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    policy = config.principals["local"]
    policy.capabilities.remove("keyboard.profiles.read")
    before = list(policy.capabilities)
    result = await backend.request(value())
    assert result["task"]["error"]["code"] == "keyboard_ui_permission_denied" and rpc.calls == []
    assert result["task"]["ui_halted"] and result["task"]["ui_workflow_status"] == "halted"
    assert policy.capabilities == before
    policy.capabilities.append("keyboard.profiles.read")
    original = rpc.detail

    def foreign(task_id):
        detail = original(task_id)
        detail["task"]["principal"] = "other"
        return detail

    rpc.detail = foreign
    intent = {**value(), "id": str(uuid.uuid4())}
    result = await backend.request(intent)
    assert result["task"]["error"]["code"] == "keyboard_task_mismatch"
    assert rpc.approvals == []


async def test_enqueued_main_with_mismatched_reply_is_unknown_not_definite_halt(
    bridge, config, monkeypatch
):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    original = rpc.__call__

    async def wrong_reply(name, args, **kwargs):
        result = await original(name, args, **kwargs)
        if name == "task_request" and args["request"]["operation"] == "keyboard.action":
            rpc.finish(result["id"])  # It may already have run before the wrong reply arrives.
            result["id"] = "unrelated-response"
        return result

    monkeypatch.setattr(backend.control, "rpc", wrong_reply)
    request = value("run_profile", run_args())
    response = await backend.request(request)
    assert response["task"]["state"] == "unknown"
    assert not response["task"]["ui_halted"]
    assert response["task"]["ui_workflow_status"] == "unconfirmed"
    assert response["task"]["error"]["code"] == "keyboard_task_mismatch"
    primary = "ui-keyboard-" + uuid.UUID(IDENTITY).hex + "-main"
    assert (await backend.status(primary))["state"] == "completed"
    await backend.request(request)
    assert sum(name == "task_request" for name, _ in rpc.calls) == 4


@pytest.mark.parametrize(
    "stop", [("app.focus", "unknown"), ("keyboard.inspect", "failed"), ("app.focus", "running")]
)
async def test_run_stages_abort_without_refocus_or_get_continuation(
    bridge, config, monkeypatch, stop
):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    rpc.stop = stop
    request = value("run_profile", run_args())
    first = await backend.request(request)
    operations = [c[1]["request"]["operation"] for c in rpc.calls if c[0] == "task_request"]
    assert operations == ["keyboard.profiles.get", "app.focus"] + (
        ["keyboard.inspect"] if stop[0] == "keyboard.inspect" else []
    )
    assert first["task"]["ui_halted"] and first["task"]["ui_incomplete"]
    rpc.stop = None
    rpc.finish(first["task"]["id"])
    primary = "ui-keyboard-" + uuid.UUID(IDENTITY).hex + "-main"
    reconciled = await backend.status(primary)
    assert (
        reconciled["state"] == "completed"
        and reconciled["ui_halted"]
        and not reconciled["ui_primary"]
    )
    await backend.request(request)
    assert [c[1]["request"]["operation"] for c in rpc.calls if c[0] == "task_request"] == operations


@pytest.mark.parametrize("candidate", [False, True])
async def test_stale_or_candidate_profile_refuses_before_focus(
    bridge, config, monkeypatch, candidate
):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    rpc.profile = profile("observed_menu" if candidate else "user")
    if not candidate:
        rpc.revision = "d" * 64
    result = await backend.request(value("run_profile", run_args()))
    assert result["task"]["state"] == "failed"
    assert result["task"]["ui_halted"] and result["task"]["ui_workflow_status"] == "halted"
    assert [c[1]["request"]["operation"] for c in rpc.calls if c[0] == "task_request"] == [
        "keyboard.profiles.get"
    ]


async def test_lost_post_without_any_task_is_unknown_not_no_effect(bridge, config, monkeypatch):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    primary = "ui-keyboard-" + uuid.UUID(IDENTITY).hex + "-main"
    result = await backend.status(primary)
    assert result["state"] == "unknown" and result["existence_confirmed"] is False
    assert not result["ui_halted"] and result["ui_incomplete"]
    assert result["ui_workflow_status"] == "unconfirmed"
    assert all(name == "task_get" for name, _ in rpc.calls)


async def test_completed_focus_does_not_claim_halt_while_post_is_active(
    bridge, config, monkeypatch
):
    _, backend, rpc, _ = console(bridge, config, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = rpc.__call__

    async def gated(name, args, **kwargs):
        if (
            name == "completion_receive"
            and args["source_id"].endswith("-focus")
            and args["wait_seconds"] == 0
        ):
            # The POST has completed focus but still owns its inline pipeline.
            if not entered.is_set():
                entered.set()
                await release.wait()
        return await original(name, args, **kwargs)

    monkeypatch.setattr(backend.control, "rpc", gated)
    request = asyncio.create_task(backend.request(value("run_profile", run_args())))
    await entered.wait()
    try:
        primary = "ui-keyboard-" + uuid.UUID(IDENTITY).hex + "-main"
        observed = await backend.status(primary)
        assert observed["state"] == "completed" and not observed["ui_halted"]
        assert observed["ui_incomplete"] and observed["ui_workflow_status"] == "unconfirmed"
    finally:
        release.set()
        await request


@pytest.mark.skipif(fcntl is None, reason="POSIX profile store required")
async def test_real_store_request_hash_decisions_focus_inspect_action_and_completion(
    bridge, config, monkeypatch
):
    config.principals["local"].capabilities += CAPS
    # Match the store's no-symlink anchor contract, including macOS /var.
    app = operator_application(bridge)
    control = app.control
    backend = OperatorKeyboard(control, app.task_decisions)
    store = KeyboardProfileStore(config.state_path.resolve())
    stored = store.put(profile())
    bridge.keyboard_profiles._store = store
    bridge.tasks.preflight = None
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    native_calls, rpc_calls = [], []

    async def native(operation, arguments, *, principal, before_send):
        before_send()
        native_calls.append((operation, copy.deepcopy(arguments)))
        if operation == "app.focus":
            assert arguments == {"expected_pid": 123, "expected_start": "1700000000.125000"}
            return {
                "activation_requested": True,
                "active_observed": True,
                "pid": 123,
                "application_start": "1700000000.125000",
            }
        if operation == "keyboard.inspect":
            assert arguments == {"pid": 123, "expected_started_at": 1700000000.125}
            return {"target": TARGET, "effect": "none"}
        assert operation == "keyboard.profile.chord"
        assert arguments["target"] == TARGET
        return {
            "profile_binding_verified": True,
            "profile_binding": {
                k: arguments["profile_context"][k] for k in ("id", "revision", "action")
            },
            "post_calls_returned": 2,
            "app_processing_confirmed": False,
        }

    monkeypatch.setattr(bridge.system_modules.transport, "request", native)

    async def rpc(name, arguments, **kwargs):
        rpc_calls.append((name, copy.deepcopy(arguments)))
        if name == "task_request":
            request = TaskRequest.model_validate(arguments["request"])
            result = bridge.prepare(
                "local", request, completion_target=arguments["completion_target"]
            )
            assert app.task_decisions.detail(request.task_id)["request_hash"] == request_hash(
                request
            )
            return result
        if name == "task_get":
            return bridge.task("local", arguments["task_id"])
        if name == "completion_receive":
            claimed = bridge.store.claim(bridge.tasks.owner, config.lease_seconds, "normal")
            if claimed is not None:
                await bridge.tasks._execute(claimed)
            return await bridge.completions.wait(
                "local", arguments["target"], 20, 0, arguments["source_id"]
            )
        if name == "completion_ack":
            return bridge.completions.ack("local", arguments["notice_id"], arguments["receipt"])
        raise AssertionError(name)

    monkeypatch.setattr(control, "rpc", rpc)
    request = value("run_profile", {**run_args(), "expected_revision": stored.revision})
    result = await backend.request(request)
    assert result["task"]["state"] == "completed", result
    assert result["task"]["result"]["profile_binding_verified"] is True
    assert result["task"]["result"]["app_processing_confirmed"] is False
    assert [operation for operation, _ in native_calls] == [
        "app.focus",
        "keyboard.inspect",
        "keyboard.profile.chord",
    ]
    assert len([name for name, _ in rpc_calls if name == "completion_ack"]) == 4
    await backend.request(request)
    await backend.status(result["task"]["id"])
    assert len(native_calls) == 3
