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

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.image_manager import MAX_IMAGE_BYTES, validate_png
from kirabridge.platform_adapters import reap_process
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS
from kirabridge.system_operations import SYSTEM_READ_OPERATIONS as READ_OPERATIONS

PROTOCOL = 1
BUNDLE_ID = "de.netzwerkpunkt.kirabridge"
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


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
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        if len(data) > limit or (info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("Native app changed during metadata read")
        return data, after
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

    def snapshot_metadata(self):
        """No app launch, framework/API call, permission probe or user-content read."""
        if sys.platform != "darwin":
            return {"available": False, "reason": "unsupported_platform"}
        try:
            if self.app_path.is_symlink():
                raise ValueError("Symlink app refused")
            info, _ = _private_file(self.app_path / "Contents/Info.plist", 65536)
            metadata = plistlib.loads(info)
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
            binary, mode = _private_file(executable, 32 * 1024 * 1024)
            if not mode.st_mode & 0o111:
                raise ValueError("Native app executable missing")
            binary_sha256 = hashlib.sha256(binary).hexdigest()
            if (
                self.expected_binary_sha256 is not None
                and binary_sha256 != self.expected_binary_sha256
            ):
                raise ValueError("Native app binary identity mismatch")
            return {
                "available": True,
                "protocol": PROTOCOL,
                "reason": "available",
                "revision": "system-v1:" + commit,
                "source_commit": commit,
                "executable": str(executable.absolute()),
                "bundle_id": BUNDLE_ID,
                "binary_sha256": binary_sha256,
            }
        except (OSError, ValueError, TypeError, RecursionError, plistlib.InvalidFileException):
            return {"available": False, "reason": "native_app_protocol_unavailable"}

    async def _discard(self):
        child, self.process = self.process, None
        self.generation = self.active_contract = None
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
        if not isinstance(principal, str) or not principal or len(principal.encode()) > 256:
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
                        raise cls(error["code"], "Native system operation refused or failed")
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

    async def close(self):
        await self.transport.close()

    async def execute(self, operation, arguments, *, principal="", task_id=""):
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
            options["before_send"] = lambda: self.authorize(principal, operation)
        result = await self.transport.request(operation, native, **options)
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
