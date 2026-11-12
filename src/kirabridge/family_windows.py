"""Fixed native family switch, before Bridge/SQLite initialization.

The operator-owned registry freezes an existing automatic policy decision. It is
not a browser-provided capability, and cannot override or extend the live policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import plistlib
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.permissions import decision
from kirabridge.platform_adapters.macos.system_identity import installed_native_contract
from kirabridge.platform_adapters.macos.system_transport import NativeSystemTransport, _private_file

PRODUCTS = {
    "kirabridge": ("~/Applications/KiraBridge.app", "de.netzwerkpunkt.kirabridge"),
    "threaddesk": ("~/Applications/ThreadDesk.app", "de.netzwerkpunkt.threaddesk.tauri"),
    "4allpass": ("/Applications/4AllPass.app", "de.netzwerkpunkt.fourallpass"),
    "tollgate": ("/Applications/TollGate.app", "de.netzwerkpunkt.tollgate"),
    "agent-authority": ("/Applications/Agent Authority.app", "de.agentauthority.observer"),
}
REQUIRED = ("windows.focus", "accessibility.set", "apps.launch")
SCHEMA = "kirabridge.family-windows.v1"


class FamilyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: Literal["kirabridge", "threaddesk", "4allpass", "tollgate", "agent-authority"]
    source_pid: StrictInt = Field(gt=1, le=2147483647)
    source_start: str | None = Field(default=None, pattern=r"^[0-9]{1,12}\.[0-9]{6}$")


def registry_path() -> Path:
    return Path.home() / ".config/kirabridge/family-windows.json"


def read_registry() -> dict:
    raw, info = _private_file(registry_path(), 65536)
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise BridgeError("family_registry_invalid", "Registration must be owner-only")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise BridgeError("family_registry_invalid", "Invalid operator family registration")
    return value


def policy_snapshot(config, principal: str) -> dict:
    if principal != "local" or not config._source_path or not config._source_sha256:
        raise BridgeError("family_policy_required", "An existing local policy file is required")
    for operation in REQUIRED:
        result = decision(config, principal, operation)
        if not result["authorized"] or not result["automatic"]:
            raise BridgeError(
                "family_policy_denied", "Existing automatic native grants are required"
            )
    # Validate file ownership/mode as well as the loader's policy bytes.
    raw, _ = _private_file(Path(config._source_path), 2 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != config._source_sha256:
        raise BridgeError("family_policy_changed", "Policy changed during admission")
    return {
        "path": config._source_path,
        "sha256": config._source_sha256,
        "principal": principal,
        "operations": list(REQUIRED),
    }


def registration_template(config, principal: str) -> dict:
    return {
        "schema": SCHEMA,
        "enabled": False,
        "policy": policy_snapshot(config, principal),
        "apps": {
            key: {"path": str(Path(path).expanduser()), "bundle_id": bundle}
            for key, (path, bundle) in PRODUCTS.items()
        },
    }


def validate_registry(value, expected_policy):
    if (
        set(value) != {"schema", "enabled", "policy", "apps"}
        or value.get("schema") != SCHEMA
        or value.get("enabled") is not True
        or value.get("policy") != expected_policy
        or not isinstance(value.get("apps"), dict)
        or set(value["apps"]) != set(PRODUCTS)
    ):
        raise BridgeError(
            "family_registry_invalid", "Registration does not match the current policy"
        )
    for key, item in value["apps"].items():
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "bundle_id"}
            or item.get("bundle_id") != PRODUCTS[key][1]
            or not isinstance(item.get("path"), str)
            or not item["path"].startswith("/")
            or not item["path"].endswith(".app")
        ):
            raise BridgeError("family_registry_invalid", "Invalid fixed product registration")


def validate_receipt(value, target):
    if not isinstance(value, dict):
        raise UncertainExecution("family_receipt_unknown", "Native effect receipt is incomplete")
    bounds = value.get("actual_outer_bounds", {})
    if (
        value.get("success") is not True
        or "error" in value
        or value.get("execution_outcome_unknown") is True
        or value.get("active_product") != target
        or type(value.get("visible_family_windows")) is not int
        or value["visible_family_windows"] != 1
        or not isinstance(bounds, dict)
        or any(
            type(bounds.get(k)) not in (int, float) or not math.isfinite(bounds[k])
            for k in ("x", "y", "width", "height")
        )
        or bounds["width"] <= 0
        or bounds["height"] <= 0
    ):
        raise UncertainExecution("family_receipt_unknown", "Native effect receipt is incomplete")
    return value


async def execute_family(args, *, transport=None):
    """Only a pinned installed native app is a production backend; never swift/shell."""
    if args.action != "registration" and sys.platform != "darwin":
        raise BridgeError("family_unsupported", "Native family windows require macOS")
    config = load_config(args.config)
    snapshot = policy_snapshot(config, args.principal)
    if args.action == "registration":
        return registration_template(config, args.principal)
    try:
        source_pid = int(args.source_pid)
    except (TypeError, ValueError):
        raise BridgeError(
            "family_source_invalid", "An exact native source PID is required"
        ) from None
    request = FamilyRequest(
        target=args.target, source_pid=source_pid, source_start=args.source_start
    )
    admitted_registry = read_registry()
    validate_registry(admitted_registry, snapshot)
    if transport is None:
        contract = installed_native_contract(__file__)
        if not contract.get("expected_commit"):
            raise BridgeError(
                "family_installed_backend_required", "A pinned installed native release is required"
            )
        transport = NativeSystemTransport(**contract, timeout=30)
        metadata = transport.snapshot_metadata()
        if not metadata.get("available"):
            raise BridgeError(
                "family_backend_unavailable", "Pinned native family backend unavailable"
            )
        raw, _ = _private_file(Path(metadata["executable"]).parent.parent / "Info.plist", 65536)
        protocol = plistlib.loads(raw).get("KiraBridgeFamilyWindowProtocol")
        if type(protocol) is not int or protocol != 1:
            raise BridgeError(
                "family_backend_unavailable", "Installed app lacks the native family protocol"
            )

    def revalidate():
        if (
            policy_snapshot(load_config(args.config), args.principal) != snapshot
            or read_registry() != admitted_registry
        ):
            raise BridgeError(
                "family_policy_changed", "Registration/policy changed before dispatch"
            )

    try:
        value = await transport.request(
            "family.window." + args.action,
            request.model_dump(exclude_none=True),
            principal=args.principal,
            before_send=revalidate,
        )
        return validate_receipt(value, request.target) if args.action == "switch" else value
    finally:
        await transport.close()


def failure(exc, *, mutating=True):
    unknown = mutating and isinstance(exc, UncertainExecution)
    return {
        "success": False,
        "error": {
            "code": getattr(exc, "code", "family_invalid_request"),
            "message": "Family window operation failed; inspect before retrying",
        },
        "execution_outcome_unknown": unknown,
    }
