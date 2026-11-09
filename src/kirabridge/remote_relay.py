"""One explicit remote delivery through existing MCP tasks. No queue, worker or grants issued."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from importlib.resources import files

from jsonschema import ValidationError

from kirabridge.bridge_core.models import (
    BridgeError,
    TaskRequest,
    UncertainExecution,
    canonical,
    digest,
)
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache
from kirabridge.tls_identity import certificate_identity


@dataclass(frozen=True)
class DeviceBinding:
    device_ref: str
    public_key_sha256: str
    authority_revision: int
    workspace_ref: str
    workspace_path: str


@dataclass(frozen=True)
class NativeGrant:
    """Trusted resolver output, not wire data. The existing Core grant remains authority."""

    binding_sha256: str
    principal: str
    approval: str = field(repr=False)


def grant_binding_sha256(envelope):
    return digest(
        {
            key: envelope[key]
            for key in ("request_sha256", "source", "target", "route", "issued_at", "expires_at")
        }
    )


def structured(result):
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    raise UncertainExecution("remote_receipt_unknown", "No structured Core receipt")


class RemoteRelay:
    def __init__(
        self,
        source,
        device_peer: Peer,
        binding: DeviceBinding,
        resolve_grant,
        *,
        clock=time.time,
        pairing=None,
        device_key=None,
    ):
        if (
            not device_peer.url
            or not device_peer.url.startswith("https://")
            or not device_peer.certificate_sha256
        ):
            raise BridgeError(
                "remote_device_config", "An explicit leaf-pinned HTTPS device is required"
            )
        identity = certificate_identity(device_peer.ca_file)
        if (
            identity.certificate_sha256 != device_peer.certificate_sha256
            or identity.public_key_sha256 != binding.public_key_sha256
            or source.device_ref != binding.device_ref
            or source.device_key_sha256 != binding.public_key_sha256
        ):
            raise BridgeError("remote_device_config", "Device certificate identity differs")
        self.source, self.peer, self.binding = source, device_peer, binding
        self.resolve_grant, self.clock, self.pairing = resolve_grant, clock, pairing
        self._device_key = device_key  # str, zero-arg provider or 0600 file path; never logged
        self.pool = MCPClientPool(call_timeout=25)
        self.validator = SchemaValidatorCache()
        self.schema = json.loads(
            files("kirabridge").joinpath("remote_contract.v1.schema.json").read_text()
        )

    async def __aenter__(self):
        try:
            await self.pool.connect(self.peer)
        except BaseException:
            await self.pool.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        await self.pool.__aexit__(*args)

    def _snapshot(self, envelope):
        try:
            data = canonical(envelope)
            if len(data.encode()) > 1024 * 1024:
                raise ValueError()
            snapshot = json.loads(data)
            self.validator.validate(snapshot, self.schema)
        except (ValidationError, ValueError, TypeError, RecursionError, UnicodeError):
            raise BridgeError(
                "remote_envelope_invalid", "Invalid bounded remote envelope"
            ) from None
        return snapshot

    async def _check(self, envelope):
        if envelope["kind"] != "intent" or envelope["route"] != "separate_managed_session":
            raise BridgeError(
                "remote_profile_unsupported",
                "Only the explicit issued-handoff profile can dispatch",
            )
        target = {
            "device_ref": self.binding.device_ref,
            "device_key_sha256": self.binding.public_key_sha256,
            "authority_revision": self.binding.authority_revision,
            "workspace_ref": self.binding.workspace_ref,
        }
        if envelope["target"] != target:
            raise BridgeError("remote_device_changed", "Target device or authority binding differs")
        request = TaskRequest.model_validate(envelope["request"])
        if (
            digest(request.model_dump()) != envelope["request_sha256"]
            or request.idempotency_key != request.task_id
            or request.arguments.get("cwd") != self.binding.workspace_path
        ):
            raise BridgeError(
                "remote_request_changed", "Exact request or workspace binding differs"
            )
        source = envelope["source"]
        if (
            source["thread_id"] != self.source.project_id
            or source["actor_ref"] != self.source.subject_ref
            or source["service_ref"] != self.source.service_ref
            or source["tenant_ref"] != self.source.tenant_ref
            or source["handoff_id"] != request.arguments["handoff_id"]
            or source["handoff_revision"] != request.arguments["revision"]
        ):
            raise BridgeError("remote_source_changed", "Configured source binding differs")
        lookup = await self.source.call("get_issued_handoff", {"handoff_id": source["handoff_id"]})
        issued = lookup.get("issued") if lookup.get("found") is True else None
        if (
            not isinstance(issued, dict)
            or issued.get("content_hash") != source["content_sha256"]
            or digest(issued.get("handoff")) != source["content_sha256"]
            or issued["handoff"].get("thread_id") != source["thread_id"]
            or issued["handoff"].get("task_id") != source["original_task_id"]
            or issued["handoff"].get("revision") != source["handoff_revision"]
            or issued.get("source", {}).get("thread_revision") != source["thread_revision"]
        ):
            raise BridgeError("remote_source_changed", "Issued source no longer matches its pin")
        grant = self.resolve_grant(envelope["authorization"]["grant_ref"])
        expected = grant_binding_sha256(envelope)
        if (
            not isinstance(grant, NativeGrant)
            or grant.binding_sha256 != expected
            or envelope["authorization"]["grant_sha256"] != expected
        ):
            raise BridgeError("remote_grant_invalid", "No matching existing operator grant")
        return request, grant

    async def _existing(self, request, grant):
        task = structured(
            await self.pool.call(self.peer.id, "task_get", {"task_id": request.task_id})
        )
        if (task.get("error") or {}).get("code") == "not_found":
            return None
        if (
            task.get("id") != request.task_id
            or task.get("principal") != grant.principal
            or task.get("request_sha256") != digest(request.model_dump())
        ):
            raise BridgeError("remote_task_conflict", "Existing Core identity or request differs")
        return task

    def _authorize_device(self):
        # Optional revocable device key: gates execution only; reconcile stays read-only.
        if self.pairing is not None:
            self.pairing.authorize(
                self.binding.device_ref, self.binding.workspace_ref, self._load_device_key()
            )

    def _load_device_key(self):
        source = self._device_key
        if callable(source):
            return source()
        if isinstance(source, (str, os.PathLike)) and not isinstance(source, str):
            source = os.fspath(source)
        if isinstance(source, str) and os.path.isabs(source):
            try:
                if os.stat(source).st_mode & 0o077:
                    raise BridgeError("device_key_invalid", "Device key file must be 0600")
                with open(source) as handle:
                    return handle.read().strip()
            except OSError:
                return None
        return source

    async def reconcile(self, envelope):
        envelope = self._snapshot(envelope)
        request, grant = await self._check(envelope)
        task = await self._existing(request, grant)
        if task is None:
            raise UncertainExecution(
                "remote_task_unknown", "No Core receipt; do not replay delivery"
            )
        return task

    async def deliver(self, envelope):
        self._authorize_device()
        envelope = self._snapshot(envelope)
        request, grant = await self._check(envelope)
        existing = await self._existing(request, grant)
        if existing is not None:
            return existing  # Read-only reconciliation, including UNKNOWN and pending tasks.
        now = self.clock()
        if not envelope["issued_at"] <= now < envelope["expires_at"]:
            raise BridgeError("remote_grant_expired", "Remote admission window is not current")
        # An immutable transport marker in the EXISTING TD issued record, not a queue.
        # A prior marker without a Core receipt means unknown: never submit again.
        if not await self.source.reserve_attempt(envelope, grant.principal):
            raise UncertainExecution(
                "remote_delivery_unknown", "Existing dispatch marker; do not replay"
            )
        self._authorize_device()
        if (
            self.resolve_grant(envelope["authorization"]["grant_ref"]) != grant
            or self.clock() >= envelope["expires_at"]
        ):
            raise BridgeError("remote_grant_invalid", "Grant changed before submission")
        try:
            task = structured(
                await self.pool.call(
                    self.peer.id,
                    "task_submit",
                    {"request": request.model_dump(), "approval": grant.approval},
                )
            )
        except Exception:
            raise UncertainExecution(
                "remote_delivery_unknown", "Original submission outcome unknown; reconcile only"
            ) from None
        if (
            task.get("id") != request.task_id
            or task.get("principal") != grant.principal
            or task.get("request_sha256") != digest(request.model_dump())
        ):
            raise UncertainExecution("remote_delivery_unknown", "No exact Core submission receipt")
        return task
