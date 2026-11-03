"""Bounded automatic-only native reads, without persisted tasks or notices."""

from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos.system_models import SYSTEM_INPUTS

# Deliberately independent of the broad native operation catalog. No input,
# capture/image delivery, preferences, permission request or generic dispatch.
NATIVE_READ_OPERATIONS = frozenset(
    {
        "apps.list",
        "apps.inspect",
        "windows.list",
        "windows.inspect",
        "accessibility.status",
        "accessibility.inspect",
    }
)
NATIVE_READ_SECONDS = 12.0


def native_arguments(operation, arguments, max_bytes):
    """Validate the complete inner contract before any batch read starts."""
    if (
        type(operation) is not str
        or operation not in NATIVE_READ_OPERATIONS
        or type(arguments) is not dict
    ):
        raise ValueError("Choose an explicit supported native read and arguments object")
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("Native read arguments exceed 64 KiB")
        frozen = json.loads(encoded)
        native = SYSTEM_INPUTS[operation].model_validate(frozen).model_dump(exclude_none=True)
        # Tree and outer response limits are independent. Reserve space for the
        # ordinary inspection header and native identity, then enforce the exact
        # complete response size after reading. No result is silently clipped.
        if operation == "accessibility.inspect" and native.get("max_depth", 0):
            if max_bytes < 24576:
                raise ValueError("A tree read requires max_bytes of at least 24576")
            native["max_tree_bytes"] = min(native["max_tree_bytes"], max_bytes - 8192)
        return native
    except (ValidationError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Native read arguments do not match their operation schema") from exc


class NativeQueries:
    def __init__(self, security, provider, modules, slots):
        self.security, self.provider, self.modules = security, provider, modules
        self.slots, self.active = slots, 0

    def _automatic(self, principal, operation):
        decision = self.security.authorize(principal, operation)
        if decision["approval_required"]:
            raise BridgeError(
                "approval_required",
                "Native read requires approval; submit the same operation using task_request",
            )

    async def execute(self, principal, operation, arguments, *, max_bytes):
        try:
            arguments = native_arguments(operation, arguments, max_bytes)
        except ValueError:
            raise BridgeError("invalid_arguments", "Invalid native read arguments") from None
        self._automatic(principal, operation)
        if self.active >= self.slots:
            raise BridgeError("native_read_busy", "Native read slots are occupied")
        self.active += 1
        try:
            # Includes waiting for the native transport lock, unlike the native
            # request timeout alone. Cancellation never starts a replacement read.
            async with asyncio.timeout(NATIVE_READ_SECONDS):
                result = await self.provider.execute(
                    operation,
                    lambda: self.modules.execute(
                        operation, arguments, principal=principal, automatic_only=True
                    ),
                    revalidate=lambda: self._automatic(principal, operation),
                )
                value = {
                    "operation": "native.read",
                    "native_operation": operation,
                    "result": result,
                    "read_only": True,
                }
                size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                if size > max_bytes:
                    raise BridgeError(
                        "native_read_result_limit",
                        "Native read exceeds max_bytes; request a smaller page/tree",
                    )
                return value
        except TimeoutError:
            raise BridgeError(
                "native_read_timeout", "Native read exceeded its time budget"
            ) from None
        finally:
            self.active -= 1
