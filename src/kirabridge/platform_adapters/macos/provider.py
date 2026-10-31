"""Compose existing native leaves without owning policy, tasks or retry logic."""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.platform_adapters.macos.capabilities import CapabilityProbe
from kirabridge.platform_adapters.macos.permissions import PermissionProbe


@dataclass(frozen=True)
class OperationDescriptor:
    operation: str
    leaf: str
    permissions: tuple[tuple[str, str, str | None], ...] = ()
    public: bool = True


TERMINAL_PERMISSIONS = (
    ("accessibility", "/usr/bin/osascript", None),
    ("automation", "/usr/bin/osascript", "com.apple.Terminal"),
    ("automation", "/usr/bin/osascript", "com.apple.systemevents"),
)
TERMINAL_READ_PERMISSION = (("automation", "/usr/bin/osascript", "com.apple.Terminal"),)
DESCRIPTORS = tuple(
    [
        OperationDescriptor("file." + name, "files")
        for name in ("read", "image", "list", "write", "mkdir", "move", "delete")
    ]
    + [
        OperationDescriptor("process." + name, "processes")
        for name in ("list", "inspect", "terminate")
    ]
    + [
        OperationDescriptor(
            "clipboard.read", "clipboard", (("clipboard", "/usr/bin/pbpaste", None),)
        ),
        OperationDescriptor(
            "clipboard.write",
            "clipboard",
            (("clipboard", "/usr/bin/pbcopy", None), ("clipboard", "/usr/bin/pbpaste", None)),
        ),
        OperationDescriptor("clipboard.info", "clipboard"),
    ]
    + [
        OperationDescriptor(
            "session." + name,
            "terminal_app",
            TERMINAL_READ_PERMISSION
            if name in {"catalog", "read", "open"}
            else TERMINAL_PERMISSIONS,
        )
        for name in ("catalog", "read", "open", "input", "focus", "close")
    ]
    + [
        OperationDescriptor("terminal.visible", "terminal_app", TERMINAL_PERMISSIONS),
        OperationDescriptor("terminal.native", "terminal_app", TERMINAL_PERMISSIONS, public=False),
    ]
)


class MacOSProvider:
    provider_id = "macos.existing_native"
    provider_version = "1"

    def __init__(
        self,
        *,
        terminal_app=None,
        clipboard=None,
        files=None,
        processes=None,
        capabilities=None,
        permissions=None,
        actor_identities=None,
    ):
        self.leaves = {
            "terminal_app": terminal_app,
            "desktop_session": getattr(terminal_app, "desktop", None),
            "clipboard": clipboard,
            "files": files,
            "processes": processes,
        }
        self.capability_probe = capabilities or CapabilityProbe()
        self.permission_probe = permissions or PermissionProbe()
        self.actor_identities = dict(actor_identities or {})
        self.descriptors = {item.operation: item for item in DESCRIPTORS}

    def snapshot(self):
        """Metadata only. No leaf/native probe, task, clipboard or window access."""
        technical = self.capability_probe.snapshot()
        permissions = self.permission_probe.snapshot()
        payload = {
            "schema_version": 1,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            **technical,
            "permissions": permissions,
            "authorization": "existing_principal_policy_and_target_guards",
        }
        # Revisions represent facts, not elapsed wall time.
        payload["revision"] = digest(
            {
                **payload,
                "permissions": [
                    {k: v for k, v in p.items() if k != "observed_at"} for p in permissions
                ],
            }
        )
        return deepcopy(payload)

    def _permission_rows(self, descriptor):
        return [
            self.permission_probe.status(
                resource,
                actor=actor,
                target=target,
                identity=self.actor_identities.get(actor),
            )
            for resource, actor, target in descriptor.permissions
        ]

    def operation_catalog(self, decide):
        """Annotate only existing schemas; this callback is the central ACL decision."""
        facts = self.snapshot()
        rows = []
        for descriptor in self.descriptors.values():
            if not descriptor.public:
                continue
            policy = decide(descriptor.operation)
            permissions = self._permission_rows(descriptor)
            native_available = facts["capabilities"][descriptor.leaf]["available"]
            bound = self.leaves.get(descriptor.leaf) is not None
            blocked = any(
                p["state"] in {"denied", "not_determined"} or p.get("raw_granted") is False
                for p in permissions
            )
            rows.append(
                {
                    "operation": descriptor.operation,
                    "provider_id": self.provider_id,
                    "provider_version": self.provider_version,
                    "leaf": descriptor.leaf,
                    "technical_available": native_available and bound,
                    "permissions": permissions,
                    "policy": policy,
                    "eligible_for_submission": bool(policy.get("authorized"))
                    and native_available
                    and bound
                    and not blocked,
                    "approval_required": bool(policy.get("approval_required")),
                    "requires_fresh_policy_and_target_check": True,
                    "os_permission_state": "requires_native_target_check",
                }
            )
        return rows

    def require(self, operation, *, expected_revision=None):
        descriptor = self.descriptors.get(operation)
        if descriptor is None:
            raise BridgeError("macos_operation_unavailable", "No macOS provider for this operation")
        snapshot = self.snapshot()
        if expected_revision is not None and snapshot["revision"] != expected_revision:
            raise BridgeError("macos_provider_changed", "macOS capability observations changed")
        capability = snapshot["capabilities"][descriptor.leaf]
        if not capability["available"] or self.leaves.get(descriptor.leaf) is None:
            raise BridgeError(
                "macos_capability_unavailable", "Selected macOS transport is unavailable"
            )
        for permission in self._permission_rows(descriptor):
            if (
                permission["state"] in {"denied", "not_determined"}
                or permission.get("raw_granted") is False
            ):
                raise BridgeError(
                    "macos_permission_denied", "Matching native permission is not granted"
                )
        # Unknown on an existing transport still requires its own final native
        # checks. No optional/new leaf is enabled by an unknown observation.
        return descriptor

    async def execute(self, operation, invoke, *, revalidate, expected_revision=None):
        """Call one already selected domain handler once. No approval or retry here."""
        self.require(operation, expected_revision=expected_revision)
        validated = revalidate()
        if inspect.isawaitable(validated):
            validated = await validated
        if validated is False:
            raise BridgeError("macos_revalidation_denied", "Fresh policy or target check refused")
        # The callback may await. Recheck immediately before invoking the leaf.
        self.require(operation, expected_revision=expected_revision)
        result = invoke()
        return await result if inspect.isawaitable(result) else result
