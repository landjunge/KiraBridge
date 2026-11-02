"""Native worker lifecycle/identity contracts, without launching apps or requesting rights."""

import asyncio
import base64
import hashlib
import json
import plistlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.macos import system_transport as native
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS

COMMIT = "a" * 40
GENERATION = "12345678-1234-1234-1234-123456789012"
CONTRACT = {
    "available": True,
    "protocol": 1,
    "reason": "available",
    "revision": "system-v1:" + COMMIT,
    "source_commit": COMMIT,
    "executable": "/private/test/KiraBridge.app/Contents/MacOS/KiraBridge",
    "bundle_id": native.BUNDLE_ID,
    "binary_sha256": "b" * 64,
}


class Writer:
    def __init__(self, child):
        self.child = child
        self.closed = False

    def write(self, data):
        self.child.requests.append(json.loads(data))
        if self.child.respond is not None:
            reply = self.child.respond(self.child.requests[-1], self.child)
            self.child.stdout.feed_data(reply)

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class Child:
    pid = 123

    def __init__(self, respond=None):
        self.respond = respond
        self.stdout = asyncio.StreamReader(limit=native.MAX_RESPONSE_BYTES + 1)
        self.stderr = None
        self.returncode = None
        self.requests = []
        self.stdin = Writer(self)
        self.finished = asyncio.Event()
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        return self.returncode


def response(request, child, *, result=None, error=None, helper_delta=None, delta=None):
    packet = {
        "protocol": 1,
        "revision": CONTRACT["revision"],
        "request_id": request["request_id"],
        "helper": {
            "pid": child.pid,
            "executable": CONTRACT["executable"],
            "bundle_id": native.BUNDLE_ID,
            "source_commit": COMMIT,
            "generation": GENERATION,
            **(helper_delta or {}),
        },
        **(delta or {}),
    }
    if error is not None:
        packet["error"] = error
    else:
        packet["result"] = result or {"ok": True}
    return json.dumps(packet).encode() + b"\n"


def transport(monkeypatch, respond=response, *, timeout=0.1):
    child = Child(respond)
    calls = []

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return child

    worker = native.NativeSystemTransport(process_factory=spawn, timeout=timeout)
    monkeypatch.setattr(worker, "snapshot_metadata", lambda: dict(CONTRACT))
    return worker, child, calls


@pytest.mark.parametrize(
    ("operation", "code", "message", "unknown", "expected"),
    [
        (
            "keyboard.inspect",
            "keyboard_unsupported",
            "Keyboard app is not frontmost",
            False,
            "keyboard_not_frontmost",
        ),
        (
            "keyboard.inspect",
            "keyboard_unsupported",
            "Secure or unknown keyboard field is unsupported",
            False,
            "keyboard_unsupported",
        ),
        (
            "keyboard.inspect",
            "keyboard_unsupported",
            "private field secret",
            False,
            "keyboard_unsupported",
        ),
        (
            "keyboard.key",
            "keyboard_unsupported",
            "Keyboard app is not frontmost",
            False,
            "keyboard_unsupported",
        ),
        (
            "keyboard.inspect",
            "keyboard_unsupported",
            "Keyboard app is not frontmost",
            True,
            "keyboard_unsupported",
        ),
    ],
)
async def test_only_verified_readonly_frontmost_refusal_gets_typed_code(
    monkeypatch, operation, code, message, unknown, expected
):
    worker, _, _ = transport(
        monkeypatch,
        lambda request, child: response(
            request,
            child,
            error={
                "code": code,
                "message": message,
                "effect_unknown": unknown,
            },
        ),
    )
    try:
        with pytest.raises(UncertainExecution if unknown else BridgeError) as caught:
            await worker.request(operation, {}, principal="alice")
        assert caught.value.code == expected
        assert str(caught.value) == "Native system operation refused or failed"
    finally:
        await worker.close()


async def test_persistent_worker_serializes_and_binds_authenticated_owner(monkeypatch):
    worker, child, calls = transport(monkeypatch)
    try:
        replies = await asyncio.gather(
            *[worker.request("system.info", {}, principal=owner) for owner in ("alice", "bob")]
        )
        assert len(calls) == 1
        assert calls[0][0] == (CONTRACT["executable"], "--system-operation")
        assert calls[0][1]["stderr"] == asyncio.subprocess.DEVNULL
        assert [p["principal"] for p in child.requests] == ["alice", "bob"]
        assert len({p["request_id"] for p in child.requests}) == 2
        assert all(p["native_helper"]["pid"] == 123 for p in replies)
    finally:
        await worker.close()
    assert child.killed and child.stdin.closed


async def test_keyboard_inspection_renews_only_exhausted_owned_worker(monkeypatch):
    worker, old, _ = transport(monkeypatch)
    renewed_generation = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    renewed = Child(
        lambda request, child: response(
            request,
            child,
            result={"target": {"target_token": "c" * 32}},
            helper_delta={"generation": renewed_generation},
        )
    )
    renewed.pid = old.pid + 1
    spawns = []

    async def spawn(*args, **kwargs):
        assert old.killed and old.stdin.closed
        spawns.append(args)
        return renewed

    worker.factory = spawn
    worker.process = old
    worker.active_contract = dict(CONTRACT)
    worker.generation = GENERATION
    worker._keyboard_commit_attempts = 255
    try:
        await worker.request("keyboard.text.commit", {}, principal="alice")
        assert worker._keyboard_commit_attempts == 256 and not old.killed and spawns == []
        inspected = await worker.request("keyboard.inspect", {}, principal="alice")
        assert inspected["native_helper"]["pid"] == renewed.pid
        assert inspected["native_helper"]["generation"] == renewed_generation
        assert inspected["target"]["target_token"] == "c" * 32
        assert worker.process is renewed and worker._keyboard_commit_attempts == 0
        assert len(spawns) == 1
        assert [request["operation"] for request in old.requests] == ["keyboard.text.commit"]
        assert [request["operation"] for request in renewed.requests] == ["keyboard.inspect"]
    finally:
        await worker.close()
    assert renewed.killed and worker._keyboard_commit_attempts == 0


async def test_other_operations_do_not_renew_exhausted_keyboard_worker(monkeypatch):
    worker, child, calls = transport(monkeypatch)
    try:
        await worker.request("system.info", {}, principal="alice")
        worker._keyboard_commit_attempts = 256
        await worker.request("system.info", {}, principal="alice")
        await worker.request("app.focus", {}, principal="alice")
        assert len(calls) == 1 and worker.process is child and not child.killed
        assert worker._keyboard_commit_attempts == 256
        assert [request["operation"] for request in child.requests] == [
            "system.info",
            "system.info",
            "app.focus",
        ]
    finally:
        await worker.close()
    assert worker._keyboard_commit_attempts == 0


async def test_denied_keyboard_commit_does_not_consume_worker_budget(monkeypatch):
    worker, child, calls = transport(monkeypatch)

    def denied():
        raise BridgeError("permission_denied", "Commit denied before send")

    try:
        with pytest.raises(BridgeError) as error:
            await worker.request("keyboard.text.commit", {}, principal="alice", before_send=denied)
        assert error.value.code == "permission_denied"
        assert worker._keyboard_commit_attempts == 0
        assert child.requests == [] and not child.killed and len(calls) == 1
    finally:
        await worker.close()


async def test_acl_revalidated_after_waiting_for_serial_worker_lock(monkeypatch):
    worker, child, calls = transport(monkeypatch)
    policy = {"alice": True}
    authorizations = []

    def authorize(principal, operation):
        authorizations.append((principal, operation))
        if not policy.get(principal):
            raise BridgeError("permission_denied", "Current policy denies this operation")

    modules = native.SystemModules(worker, authorize=authorize)
    await worker.lock.acquire()
    pending = asyncio.create_task(modules.execute("system.info", {}, principal="alice"))
    await asyncio.sleep(0)
    assert not pending.done() and authorizations == [] and calls == []
    policy.clear()
    worker.lock.release()
    with pytest.raises(BridgeError) as caught:
        await pending
    assert caught.value.code == "permission_denied"
    assert authorizations == [("alice", "system.info")]
    assert child.requests == [] and not child.killed and len(calls) == 1
    policy["alice"] = True
    try:
        await modules.execute("system.info", {}, principal="alice")
        assert len(calls) == 1 and len(child.requests) == 1
    finally:
        await modules.close()


async def test_acl_revalidated_after_async_native_worker_creation(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    child, policy, authorizations = Child(response), {"alice": True}, []

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return child

    def authorize(principal, operation):
        authorizations.append((principal, operation))
        if not policy.get(principal):
            raise BridgeError("permission_denied", "Current policy denies this operation")

    worker = native.NativeSystemTransport(process_factory=spawn)
    monkeypatch.setattr(worker, "snapshot_metadata", lambda: dict(CONTRACT))
    modules = native.SystemModules(worker, authorize=authorize)
    pending = asyncio.create_task(modules.execute("system.info", {}, principal="alice"))
    await entered.wait()
    policy.clear()
    assert authorizations == [] and child.requests == []
    release.set()
    try:
        with pytest.raises(BridgeError) as caught:
            await pending
        assert caught.value.code == "permission_denied"
        assert authorizations == [("alice", "system.info")]
        assert child.requests == [] and worker.process is child and not child.killed
    finally:
        await modules.close()


@pytest.mark.parametrize(
    "change",
    [
        {"pid": 124},
        {"pid": True},
        {"executable": "/bin/false"},
        {"source_commit": "c" * 40},
        {"bundle_id": "other"},
        {"generation": "invalid"},
    ],
)
async def test_foreign_helper_refuses_and_reaps_without_replay(monkeypatch, change):
    worker, child, calls = transport(
        monkeypatch, lambda req, proc: response(req, proc, helper_delta=change)
    )
    with pytest.raises(UncertainExecution, match="no automatic replay"):
        await worker.request("app.focus", {}, principal="alice")
    assert child.killed and len(calls) == 1 and worker.process is None


@pytest.mark.parametrize(
    "change", [{"protocol": 2}, {"protocol": True}, {"revision": "old"}, {"request_id": "old"}]
)
async def test_response_contract_refuses(monkeypatch, change):
    worker, child, _ = transport(monkeypatch, lambda req, proc: response(req, proc, delta=change))
    with pytest.raises(BridgeError) as caught:
        await worker.request("system.displays", {}, principal="alice")
    assert type(caught.value) is BridgeError and child.killed


@pytest.mark.parametrize(
    "raw", [b"[]\n", b"null\n", b"{broken}\n", b"{}\n", b"[" * 1100 + b"]" * 1100 + b"\n"]
)
async def test_malformed_response_reaps(monkeypatch, raw):
    worker, child, _ = transport(monkeypatch, lambda *_: raw)
    with pytest.raises(BridgeError):
        await worker.request("windows.list", {}, principal="alice")
    assert child.killed


async def test_eof_and_oversized_response_reap(monkeypatch):
    monkeypatch.setattr(native, "MAX_RESPONSE_BYTES", 64)
    worker, child, _ = transport(monkeypatch, lambda *_: b"x" * 65 + b"\n")
    with pytest.raises(BridgeError):
        await worker.request("system.info", {}, principal="alice")
    assert child.killed
    worker, child, _ = transport(monkeypatch, None)
    child.stdout.feed_eof()
    with pytest.raises(BridgeError):
        await worker.request("system.info", {}, principal="alice")
    assert child.killed


@pytest.mark.parametrize(
    "operation,uncertain",
    [
        ("apps.quit", True),
        ("preferences.write", True),
        ("system.volumes", False),
        ("system.permissions", False),
        ("system.permission_request", True),
        ("capture.window", False),
    ],
)
async def test_timeout_classifies_effect_and_never_replays(monkeypatch, operation, uncertain):
    worker, child, calls = transport(monkeypatch, None, timeout=0.01)
    with pytest.raises(BridgeError) as caught:
        await worker.request(operation, {}, principal="alice")
    assert isinstance(caught.value, UncertainExecution) == uncertain
    assert child.killed and len(calls) == 1


async def test_cancel_read_reaps_and_preserves_cancellation(monkeypatch):
    worker, child, _ = transport(monkeypatch, None)
    task = asyncio.create_task(worker.request("apps.quit", {}, principal="alice"))
    while not child.requests:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and worker.process is None


async def test_cancel_survives_cleanup_error(monkeypatch):
    worker, child, _ = transport(monkeypatch, None)

    async def cleanup(*args, **kwargs):
        raise BridgeError("process_cleanup_unknown", "cleanup failed")

    monkeypatch.setattr(native, "reap_process", cleanup)
    task = asyncio.create_task(worker.request("apps.quit", {}, principal="alice"))
    while not child.requests:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.process is None


@pytest.mark.parametrize("use_timeout", [False, True])
async def test_spawn_race_resolves_created_handle_before_reaping(monkeypatch, use_timeout):
    started, release = asyncio.Event(), asyncio.Event()
    child = Child(response)
    factory_cancelled = False

    async def spawn(*args, **kwargs):
        nonlocal factory_cancelled
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            factory_cancelled = True
            raise
        return child

    worker = native.NativeSystemTransport(process_factory=spawn, timeout=0.01 if use_timeout else 1)
    monkeypatch.setattr(worker, "snapshot_metadata", lambda: dict(CONTRACT))
    task = asyncio.create_task(worker.request("apps.quit", {}, principal="alice"))
    await started.wait()
    if use_timeout:
        await asyncio.sleep(0.02)
    else:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # Repeated cancellation cannot abandon the pending creation task.
    await asyncio.sleep(0)
    assert not task.done() and not factory_cancelled
    release.set()
    with pytest.raises(BridgeError if use_timeout else asyncio.CancelledError):
        await task
    assert child.killed and worker.process is None and child.requests == []


async def test_close_cancels_reader_before_reaping(monkeypatch):
    worker, child, _ = transport(monkeypatch, None)
    task = asyncio.create_task(worker.request("system.info", {}, principal="alice"))
    while not child.requests:
        await asyncio.sleep(0)
    await worker.close()
    assert task.cancelled() and child.killed
    with pytest.raises(BridgeError) as caught:
        await worker.request("system.info", {}, principal="alice")
    assert caught.value.code == "system_transport_closed"


async def test_native_refusal_is_sanitized_and_worker_remains_usable(monkeypatch):
    error = {
        "code": "macos_permission_denied",
        "message": "private native text",
        "effect_unknown": False,
    }
    worker, child, calls = transport(
        monkeypatch, lambda req, proc: response(req, proc, error=error)
    )
    try:
        with pytest.raises(BridgeError) as caught:
            await worker.request("windows.focus", {}, principal="alice")
        assert caught.value.code == "macos_permission_denied"
        assert "private" not in str(caught.value) and not child.killed
        child.respond = response
        await worker.request("system.info", {}, principal="alice")
        assert len(calls) == 1
    finally:
        await worker.close()


async def test_native_uncertainty_discards_worker(monkeypatch):
    worker, child, calls = transport(
        monkeypatch,
        lambda req, proc: response(
            req, proc, error={"code": "macos_focus_unknown", "effect_unknown": True}
        ),
    )
    with pytest.raises(UncertainExecution):
        await worker.request("windows.focus", {}, principal="alice")
    assert child.killed and len(calls) == 1


async def test_changed_app_contract_invalidates_worker_without_sending(monkeypatch):
    worker, child, calls = transport(monkeypatch)
    await worker.request("system.info", {}, principal="alice")
    monkeypatch.setattr(
        worker, "snapshot_metadata", lambda: {**CONTRACT, "binary_sha256": "c" * 64}
    )
    with pytest.raises(BridgeError) as caught:
        await worker.request("apps.quit", {}, principal="alice")
    assert caught.value.code == "system_provider_changed"
    assert child.killed and len(child.requests) == 1 and len(calls) == 1


async def test_worker_generation_change_invalidates_handles(monkeypatch):
    worker, child, _ = transport(monkeypatch)
    await worker.request("system.info", {}, principal="alice")
    child.respond = lambda req, proc: response(
        req, proc, helper_delta={"generation": "ffffffff-ffff-ffff-ffff-ffffffffffff"}
    )
    with pytest.raises(BridgeError):
        await worker.request("accessibility.inspect", {}, principal="alice")
    assert child.killed


@pytest.mark.parametrize("principal", ["", None, "x" * 257, "\ufeffalice"])
async def test_principal_required_before_launch(monkeypatch, principal):
    worker, _, calls = transport(monkeypatch)
    with pytest.raises(BridgeError):
        await worker.request("system.info", {}, principal=principal)
    assert calls == []


async def test_request_limit_and_invalid_json_prevent_launch(monkeypatch):
    worker, _, calls = transport(monkeypatch)
    for arguments in ({"body": "x" * 65536}, {"bad": float("nan")}):
        with pytest.raises(BridgeError):
            await worker.request("system.info", arguments, principal="alice")
    assert calls == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 31])
def test_timeout_is_bounded(timeout):
    with pytest.raises(ValueError):
        native.NativeSystemTransport(timeout=timeout)


def make_app(tmp_path):
    app = tmp_path / "KiraBridge.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    metadata = {
        "CFBundleIdentifier": native.BUNDLE_ID,
        "CFBundleExecutable": "KiraBridge",
        "KiraBridgeSystemProtocol": 1,
        "KiraBridgeSourceCommit": COMMIT,
    }
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
    executable = app / "Contents/MacOS/KiraBridge"
    executable.write_bytes(b"test native executable")
    executable.chmod(0o700)
    return app


@pytest.mark.parametrize("protocol,expected", [(None, 0), (True, 0), (1, 1)])
def test_keyboard_metadata_preserves_old_worker_compatibility(
    tmp_path, monkeypatch, protocol, expected
):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = make_app(tmp_path)
    info = app / "Contents/Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    if protocol is not None:
        metadata["KiraBridgeKeyboardProtocol"] = protocol
        info.write_bytes(plistlib.dumps(metadata))
    worker = native.NativeSystemTransport(app, expected_commit=COMMIT)
    observed = worker.snapshot_metadata()
    assert observed["available"] is True
    assert observed["keyboard_protocol"] == expected
    assert worker.process is None


def test_metadata_is_passive_and_pins_binary_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = make_app(tmp_path)
    worker = native.NativeSystemTransport(app, expected_commit=COMMIT)
    contract = worker.snapshot_metadata()
    assert contract["available"] and contract["source_commit"] == COMMIT
    assert contract["binary_sha256"] == hashlib.sha256(b"test native executable").hexdigest()
    assert (
        native.NativeSystemTransport(app, expected_commit="b" * 40).snapshot_metadata()["available"]
        is False
    )
    assert worker.process is None


def test_installed_binary_digest_pin_accepts_exact_native_code(tmp_path, monkeypatch):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = make_app(tmp_path)
    expected = hashlib.sha256(b"test native executable").hexdigest()
    modules = native.SystemModules(
        app_path=app, expected_commit=COMMIT, expected_binary_sha256=expected
    )
    assert modules.snapshot_metadata()["binary_sha256"] == expected
    assert modules.transport.process is None


def test_installed_binary_digest_pin_refuses_replaced_code_even_with_same_plist(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = make_app(tmp_path)
    expected = hashlib.sha256(b"test native executable").hexdigest()
    worker = native.NativeSystemTransport(
        app, expected_commit=COMMIT, expected_binary_sha256=expected
    )
    (app / "Contents/MacOS/KiraBridge").write_bytes(b"replaced native executable")
    assert worker.snapshot_metadata()["available"] is False and worker.process is None


@pytest.mark.parametrize(
    "unsafe", ["old_protocol", "boolean_protocol", "symlink", "writable", "missing"]
)
def test_unknown_or_untrusted_app_is_never_started(tmp_path, monkeypatch, unsafe):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = make_app(tmp_path)
    info = app / "Contents/Info.plist"
    executable = app / "Contents/MacOS/KiraBridge"
    if unsafe == "old_protocol":
        metadata = plistlib.loads(info.read_bytes())
        del metadata["KiraBridgeSystemProtocol"]
        info.write_bytes(plistlib.dumps(metadata))
    elif unsafe == "boolean_protocol":
        metadata = plistlib.loads(info.read_bytes())
        metadata["KiraBridgeSystemProtocol"] = True
        info.write_bytes(plistlib.dumps(metadata))
    elif unsafe == "symlink":
        executable.unlink()
        executable.symlink_to("/bin/true")
    elif unsafe == "writable":
        executable.chmod(0o777)
    else:
        info.unlink()
    worker = native.NativeSystemTransport(app)
    assert worker.snapshot_metadata()["available"] is False and worker.process is None


def test_nonmac_metadata_is_passive(tmp_path, monkeypatch):
    monkeypatch.setattr(native.sys, "platform", "linux")
    worker = native.NativeSystemTransport(tmp_path)
    assert worker.snapshot_metadata() == {"available": False, "reason": "unsupported_platform"}


class ModuleTransport:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"ok": True}

    async def request(self, operation, arguments, *, principal):
        self.calls.append((operation, arguments, principal))
        return self.result


async def test_notification_identifier_is_internal_owner_task_binding():
    transport = ModuleTransport()
    modules = native.SystemModules(transport)
    await modules.execute(
        "notifications.post", {"body": "exact user message"}, principal="alice", task_id="task-1"
    )
    operation, args, owner = transport.calls[0]
    assert operation == "notifications.post" and owner == "alice"
    assert args["body"] == "exact user message"
    assert args["identifier"] == hashlib.sha256(b"alice\0task-1").hexdigest()
    with pytest.raises(BridgeError):
        await modules.execute(
            "notifications.post",
            {"body": "hello", "identifier": "injected"},
            principal="alice",
            task_id="t",
        )
    with pytest.raises(BridgeError):
        await modules.execute("notifications.post", {"body": "hello"}, principal="alice")
    assert len(transport.calls) == 1


async def test_capture_reuses_strict_png_validator_and_checks_metadata():
    data = Path(__file__).with_name("fixtures").joinpath("images/own-rgb-32x24.png").read_bytes()
    result = {
        "image_data": base64.b64encode(data).decode(),
        "width": 32,
        "height": 24,
        "bytes": len(data),
        "content_sha256": hashlib.sha256(data).hexdigest(),
    }
    transport = ModuleTransport(result)
    modules = native.SystemModules(transport)
    args = {"display_id": 1, "expected_revision": "a" * 64}
    assert await modules.execute("capture.display", args, principal="alice") == result
    for bad in ({"width": 33}, {"content_sha256": "b" * 64}, {"image_data": "not base64"}):
        transport.result = {**result, **bad}
        with pytest.raises(BridgeError):
            await modules.execute("capture.display", args, principal="alice")


@pytest.mark.parametrize(
    "operation,args",
    [
        (
            "preferences.write",
            {"key": "notification_sound", "value": 1, "expected_revision": "a" * 64},
        ),
        (
            "preferences.write",
            {"key": "appearance", "value": "arbitrary", "expected_revision": "a" * 64},
        ),
        (
            "preferences.write",
            {"key": "window_width", "value": 5000, "expected_revision": "a" * 64},
        ),
        ("preferences.read", {"key": "secret", "domain": "other"}),
        ("windows.list", {"include_ax": True}),
        ("windows.list", {"offset": 50}),
        ("windows.focus", {"expected_pid": 1, "expected_start": "1.000000", "title": "guessed"}),
        ("capture.window", {"window_id": 1, "expected_pid": 2, "expected_start": "1.000000"}),
        ("system.info", {"_principal": "injected"}),
    ],
)
def test_models_enforce_exact_targets_allowlist_and_context_separation(operation, args):
    with pytest.raises(ValidationError):
        SYSTEM_INPUTS[operation].model_validate(args)
