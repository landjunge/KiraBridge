"""One bounded native app child per Core; no daemon, task engine or input fallback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import plistlib
import re
import stat
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, NativeFailureEvidence, UncertainExecution
from kirabridge.image_manager import MAX_IMAGE_BYTES, validate_png
from kirabridge.platform_adapters import reap_process
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS
from kirabridge.system_operations import SYSTEM_READ_OPERATIONS as READ_OPERATIONS

PROTOCOL = 1
BUNDLE_ID = "de.netzwerkpunkt.kirabridge"
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
KEYBOARD_COMMIT_LIMIT = 256  # Matches the native worker's consumed-transfer budget.


def _failure_stage(operation, error):
    # Only exact static backend messages become stage names. Arbitrary messages
    # may contain user data; never attach them to exceptions or task evidence.
    stages = {
        ("windows.focus", "macos_focus_unknown"): {
            "Window raise outcome is unknown": "window_raise",
            "Window activation outcome is unknown": "application_activation",
            "Application identity changed after window raise": "target_revalidation",
        },
        ("keyboard.key", "keyboard_unsupported"): {
            "Physical modifier/system key is unsupported": "physical_key_validation",
            "Current input source/layout identity is invalid": "keyboard_layout_validation",
            "Current keyboard layout exceeds its bounded limit": "keyboard_layout_validation",
        },
        ("keyboard.inspect", "keyboard_unsupported"): {
            "Keyboard app is not frontmost": "frontmost_check",
            "Exact focused window/field is unavailable": "focused_window_lookup",
            "Focused keyboard window is unavailable": "focused_window_lookup",
            "Focused field/window ownership is unavailable": "focused_window_lookup",
        },
    }
    message = error.get("message")
    if not isinstance(message, str) or len(message) > 256:
        return "unspecified"
    return stages.get((operation, error["code"]), {}).get(message, "unspecified")


def _private_file(path, limit):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.getuid()}
            or info.st_mode & 0o022
        ):
            raise ValueError("Untrusted native app file")
        if info.st_size > limit:
            raise ValueError("Native app metadata exceeds limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            # Reserve the observed file size, not the maximum allowed binary size.
            # The extra byte detects growth; a short read is never a valid snapshot.
            data = stream.read(info.st_size + 1)
        after = os.fstat(fd)
        if len(data) != info.st_size or _stat_identity(info) != _stat_identity(after):
            raise ValueError("Native app changed during metadata read")
        return data, after
    finally:
        os.close(fd)


def _stat_identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def _private_stat(path, limit):
    """Validate a pinned native file without reading its contents."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.getuid()}
            or info.st_mode & 0o022
            or info.st_size > limit
        ):
            raise ValueError("Untrusted native app file")
        after = os.fstat(fd)
        if _stat_identity(info) != _stat_identity(after):
            raise ValueError("Native app changed during metadata read")
        return after
    finally:
        os.close(fd)


class NativeSystemTransport:
    def __init__(
        self,
        app_path=None,
        *,
        expected_commit=None,
        expected_binary_sha256=None,
        process_factory=None,
        timeout=12.0,
    ):
        if (
            not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 30
        ):
            raise ValueError("Native timeout must be finite and at most 30 seconds")
        self.app_path = Path(app_path or Path.home() / "Applications/KiraBridge.app")
        self.expected_commit = expected_commit
        self.expected_binary_sha256 = expected_binary_sha256
        self.factory = process_factory or asyncio.create_subprocess_exec
        self.timeout = timeout
        self.lock = asyncio.Lock()
        self.process = None
        self.generation = None
        self.active_contract = None
        self.closed = False
        self.active_request = None
        self._keyboard_commit_attempts = 0

    def snapshot_metadata(self):
        """No app launch, framework/API call, permission probe or user-content read."""
        return self._read_app_metadata(verify_binary=True)

    def passive_metadata(self):
        """Return epoch identity from small metadata plus executable stat, never binary bytes."""
        return self._read_app_metadata(verify_binary=False)

    def _read_app_metadata(self, *, verify_binary):
        if sys.platform != "darwin":
            return {"available": False, "reason": "unsupported_platform"}
        try:
            if self.app_path.is_symlink():
                raise ValueError("Symlink app refused")
            info, _ = _private_file(self.app_path / "Contents/Info.plist", 65536)
            metadata = plistlib.loads(info)
            if not isinstance(metadata, dict):
                raise ValueError("Native protocol metadata must be a dictionary")
            commit = metadata.get("KiraBridgeSourceCommit", "")
            if (
                type(metadata.get("KiraBridgeSystemProtocol")) is not int
                or metadata.get("KiraBridgeSystemProtocol") != PROTOCOL
                or metadata.get("CFBundleIdentifier") != BUNDLE_ID
                or metadata.get("CFBundleExecutable") != "KiraBridge"
                or not re.fullmatch(r"[a-f0-9]{40}", commit)
                or (self.expected_commit is not None and commit != self.expected_commit)
            ):
                raise ValueError("Native protocol metadata mismatch")
            executable = self.app_path / "Contents/MacOS/KiraBridge"
            if verify_binary:
                binary, file_identity = _private_file(executable, 32 * 1024 * 1024)
            else:
                file_identity = _private_stat(executable, 32 * 1024 * 1024)
            if not file_identity.st_mode & 0o111:
                raise ValueError("Native app executable missing")
            result = {
                "available": True,
                "protocol": PROTOCOL,
                "reason": "available",
                "revision": "system-v1:" + commit,
                "provider_generation": self._provider_generation(info, file_identity),
                "source_commit": commit,
                "executable": str(executable.absolute()),
                "bundle_id": BUNDLE_ID,
                "keyboard_protocol": (
                    1
                    if type(metadata.get("KiraBridgeKeyboardProtocol")) is int
                    and metadata["KiraBridgeKeyboardProtocol"] == 1
                    else 0
                ),
            }
            if verify_binary:
                binary_sha256 = hashlib.sha256(binary).hexdigest()
                result["binary_sha256"] = binary_sha256
                if (
                    self.expected_binary_sha256 is not None
                    and binary_sha256 != self.expected_binary_sha256
                ):
                    result.update(
                        available=False,
                        reason="native_app_protocol_unavailable",
                    )
            else:
                result.update(
                    available=False,
                    reason="native_binary_not_verified",
                )
            return result
        except (OSError, ValueError, TypeError, RecursionError, plistlib.InvalidFileException):
            return {"available": False, "reason": "native_app_protocol_unavailable"}

    def _provider_generation(self, info, file_identity):
        value = {
            "info_sha256": hashlib.sha256(info).hexdigest(),
            "binary_stat": _stat_identity(file_identity),
            "expected_commit": self.expected_commit,
            "expected_binary_sha256": self.expected_binary_sha256,
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _discard(self):
        child, self.process = self.process, None
        self.generation = self.active_contract = None
        self._keyboard_commit_attempts = 0
        if child is not None:
            await reap_process(child, process_group=False)

    async def close(self):
        self.closed = True
        active = self.active_request
        if active is not None and active is not asyncio.current_task() and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        await self._discard()

    async def request(self, operation, arguments, *, principal, before_send=None):
        if (
            not isinstance(principal, str)
            or not principal
            or principal.startswith("\ufeff")
            or len(principal.encode()) > 256
        ):
            raise BridgeError(
                "system_context_required", "Native operation requires its authenticated owner"
            )
        mutating = operation not in READ_OPERATIONS
        attempted = False
        async with self.lock:
            if self.closed:
                raise BridgeError("system_transport_closed", "Native system transport is closed")
            contract = self.snapshot_metadata()
            if not contract.get("available"):
                raise BridgeError(
                    "system_transport_unavailable", "Native app protocol is unavailable"
                )
            if self.active_contract is not None and self.active_contract != contract:
                await self._discard()
                raise BridgeError("system_provider_changed", "Native app changed; refresh metadata")
            request_id = uuid.uuid4().hex
            try:
                payload = (
                    json.dumps(
                        {
                            "protocol": PROTOCOL,
                            "revision": contract["revision"],
                            "request_id": request_id,
                            "principal": principal,
                            "operation": operation,
                            "arguments": arguments,
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode()
                    + b"\n"
                )
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise BridgeError(
                    "invalid_arguments", "Native request is not bounded JSON"
                ) from None
            if len(payload) > MAX_REQUEST_BYTES:
                raise BridgeError("system_request_limit", "Native system request exceeds limit")
            self.active_request = asyncio.current_task()
            try:
                async with asyncio.timeout(self.timeout):
                    if (
                        operation == "keyboard.inspect"
                        and self._keyboard_commit_attempts >= KEYBOARD_COMMIT_LIMIT
                    ):
                        # Only a new inspection may renew handles; never replay a mutation.
                        await self._discard()
                    if self.process is None:
                        creation = asyncio.create_task(
                            self.factory(
                                contract["executable"],
                                "--system-operation",
                                stdin=asyncio.subprocess.PIPE,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.DEVNULL,
                                limit=MAX_RESPONSE_BYTES + 1,
                            )
                        )
                        try:
                            self.process = await asyncio.shield(creation)
                        except asyncio.CancelledError:
                            # Resolve creation before cleanup, including repeated cancellation.
                            # The OS child may already exist although no handle was returned yet.
                            while not creation.done():
                                try:
                                    await asyncio.shield(creation)
                                except asyncio.CancelledError:
                                    pass
                                except Exception:
                                    break
                            if not creation.cancelled() and creation.exception() is None:
                                self.process = creation.result()
                            raise
                        self.active_contract = contract
                    child = self.process
                    if child.returncode is not None:
                        raise ValueError("Native worker exited")
                    if before_send is not None:
                        before_send()
                    attempted = True
                    if operation == "keyboard.text.commit":
                        self._keyboard_commit_attempts += 1
                    child.stdin.write(payload)
                    await child.stdin.drain()
                    raw = await child.stdout.readline()
                    if not raw.endswith(b"\n") or len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("Native response incomplete or oversized")
                    response = json.loads(raw)
                    if not isinstance(response, dict):
                        raise ValueError("Invalid native response")
                    helper = response.get("helper", {})
                    if not isinstance(helper, dict):
                        raise ValueError("Invalid native helper identity")
                    if (
                        type(response.get("protocol")) is not int
                        or response.get("protocol") != PROTOCOL
                        or response.get("revision") != contract["revision"]
                        or response.get("request_id") != request_id
                        or type(helper.get("pid")) is not int
                        or helper["pid"] != child.pid
                        or helper.get("executable") != contract["executable"]
                        or helper.get("bundle_id") != BUNDLE_ID
                        or helper.get("source_commit") != contract["source_commit"]
                        or not isinstance(helper.get("generation"), str)
                        or not re.fullmatch(
                            r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}",
                            helper["generation"],
                        )
                        or (self.generation is not None and self.generation != helper["generation"])
                    ):
                        raise ValueError("Native response identity changed")
                    self.generation = helper["generation"]
                    if "error" in response:
                        error = response["error"]
                        if (
                            not isinstance(error, dict)
                            or not isinstance(error.get("code"), str)
                            or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", error["code"])
                            or type(error.get("effect_unknown")) is not bool
                        ):
                            raise ValueError("Invalid native failure")
                        cls = UncertainExecution if error["effect_unknown"] else BridgeError
                        raise cls(
                            error["code"],
                            "Native system operation refused or failed",
                            native_failure=NativeFailureEvidence(
                                operation=operation,
                                stage=_failure_stage(operation, error),
                                backend_effect_unknown=error["effect_unknown"],
                                helper_pid=helper["pid"],
                                helper_generation=helper["generation"],
                                helper_source_commit=helper["source_commit"],
                                contract_binary_sha256=contract["binary_sha256"],
                                request_id=request_id,
                            ),
                        )
                    result = response.get("result")
                    if not isinstance(result, dict):
                        raise ValueError("Invalid native result")
                    return {
                        **result,
                        "native_helper": helper,
                        "provider_revision": contract["revision"],
                    }
            except UncertainExecution:
                try:
                    await self._discard()
                except BridgeError:
                    pass  # Preserve the uncertainty of an already attempted external effect.
                raise
            except BridgeError:
                raise
            except asyncio.CancelledError:
                try:
                    await self._discard()
                except BridgeError:
                    pass  # Reaping failure must never turn cancellation into normal completion.
                raise
            except (OSError, ValueError, UnicodeError, RecursionError, TimeoutError) as exc:
                try:
                    await self._discard()
                except BridgeError:
                    pass
                cls = UncertainExecution if mutating and attempted else BridgeError
                raise cls(
                    "system_operation_unknown"
                    if mutating and attempted
                    else "system_transport_failed",
                    "Native worker failed; no automatic replay; refresh handles before new work",
                ) from exc
            finally:
                self.active_request = None


class SystemModules:
    def __init__(
        self,
        transport=None,
        *,
        app_path=None,
        expected_commit=None,
        expected_binary_sha256=None,
        authorize=None,
    ):
        self.authorize = authorize
        self.transport = transport or NativeSystemTransport(
            app_path, expected_commit=expected_commit, expected_binary_sha256=expected_binary_sha256
        )

    def snapshot_metadata(self):
        return self.transport.snapshot_metadata()

    def passive_metadata(self):
        reader = getattr(self.transport, "passive_metadata", None)
        return (
            reader()
            if callable(reader)
            else {"available": False, "reason": "native_binary_not_verified"}
        )

    async def close(self):
        await self.transport.close()

    async def execute(
        self, operation, arguments, *, principal="", task_id="", automatic_only=False
    ):
        if automatic_only and (operation not in READ_OPERATIONS or self.authorize is None):
            raise BridgeError("forbidden", "Automatic read requires a current authorization check")
        model = SYSTEM_INPUTS.get(operation)
        if model is None:
            raise BridgeError("unknown_operation", "Unknown native system operation")
        try:
            validated = model.model_validate(arguments)
        except ValidationError:
            raise BridgeError("invalid_arguments", "Native system arguments are invalid") from None
        native = validated.model_dump(exclude_none=True)
        if operation == "notifications.post":
            if not principal or not task_id:
                raise BridgeError("system_context_required", "Notification requires its task owner")
            native["identifier"] = hashlib.sha256((principal + "\0" + task_id).encode()).hexdigest()
        options = {"principal": principal}
        if self.authorize is not None:

            def authorize_send():
                decision = self.authorize(principal, operation)
                if automatic_only and decision["approval_required"]:
                    raise BridgeError(
                        "approval_required",
                        "Native read requires approval; submit the operation using task_request",
                    )

            options["before_send"] = authorize_send
        result = await self.transport.request(operation, native, **options)
        if operation in {"system.permissions", "keyboard.system_inventory"}:
            from kirabridge.platform_adapters.macos.keyboard_permissions import permission_guidance

            observation = (
                result
                if operation == "system.permissions"
                else {
                    **result.get("permissions", {}),
                    "native_helper": result.get("native_helper", {}),
                }
            )
            result["permission_guidance"] = permission_guidance(observation)
        if operation.startswith("capture."):
            encoded = result.get("image_data")
            if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
                raise BridgeError("image_limit", "Native capture exceeds image limit")
            try:
                data = base64.b64decode(encoded, validate=True)
                width, height = validate_png(data)
            except (ValueError, TypeError):
                raise BridgeError(
                    "image_invalid", "Native capture is not a valid bounded PNG"
                ) from None
            if any(type(result.get(key)) is not int for key in ("width", "height", "bytes")) or (
                result.get("width"),
                result.get("height"),
                result.get("bytes"),
            ) != (
                width,
                height,
                len(data),
            ):
                raise BridgeError("image_invalid", "Native capture metadata does not match its PNG")
            if result.get("content_sha256") != hashlib.sha256(data).hexdigest():
                raise BridgeError("image_invalid", "Native capture checksum mismatch")
        return result
