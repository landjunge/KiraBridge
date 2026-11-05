"""Opt-in HTTPS transport for the existing project-bound ThreadDesk handoff contract."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

import httpx

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.handoff_manager import TOOLS
from kirabridge.tls_identity import certificate_identity, pinned_context

FORMAT = "threaddesk.handoff-http.v1"
INTERACTIVE = frozenset({"answer_handoff_question", "review_return"})


class HttpHandoffPeer:
    def __init__(
        self,
        origin,
        project_id,
        subject_ref,
        *,
        service_ref,
        tenant_ref,
        device_ref,
        device_key_sha256,
        token,
        certificate_file,
        certificate_sha256,
        timeout=10.0,
    ):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise BridgeError("handoff_peer_config", "One explicit HTTPS origin is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project_id):
            raise BridgeError("handoff_peer_config", "One explicit project is required")
        if (
            not re.fullmatch(r"[a-f0-9]{64}", subject_ref)
            or not 0 < timeout <= 30
            or any(
                not isinstance(ref, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ref)
                for ref in (service_ref, tenant_ref, device_ref)
            )
            or not isinstance(device_key_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", device_key_sha256)
        ):
            raise BridgeError("handoff_peer_config", "Invalid peer identity or deadline")
        self.origin, self.project_id, self.subject_ref = origin.rstrip("/"), project_id, subject_ref
        self.service_ref, self.tenant_ref = service_ref, tenant_ref
        self.device_ref, self.device_key_sha256 = device_ref, device_key_sha256
        self.operator_ref = digest(
            [
                FORMAT,
                self.origin,
                project_id,
                subject_ref,
                certificate_sha256,
                device_ref,
                device_key_sha256,
            ]
        )
        self._token = token
        self._context = pinned_context(certificate_file, certificate_sha256)
        self._timeout = timeout
        self._client = None
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.origin,
            headers={"Authorization": "Bearer " + self._token},
            verify=self._context,
            follow_redirects=False,
            trust_env=False,
            timeout=self._timeout,
        )
        try:
            await self._request("GET")
        except BaseException:
            await self._client.aclose()
            self._client = None
            raise
        return self

    async def __aexit__(self, *args):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method, **kwargs):
        if self._client is None:
            raise BridgeError("handoff_peer_closed", "Remote peer is not connected")
        async with self._client.stream(
            method, f"/api/projects/{self.project_id}/handoff", **kwargs
        ) as response:
            if response.status_code != 200:
                if response.status_code >= 500:
                    raise BridgeError("handoff_peer_response", "Remote outcome is unknown")
                raise BridgeError("handoff_peer_rejected", "Remote handoff request was rejected")
            data = bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data) > 1024 * 1024:
                    raise BridgeError("handoff_peer_response", "Remote response exceeds bound")
        try:
            import json

            value = json.loads(data)
        except ValueError:
            raise BridgeError("handoff_peer_response", "Invalid remote handoff response") from None
        if (
            not isinstance(value, dict)
            or value.get("format") != FORMAT
            or value.get("project_id") != self.project_id
            or value.get("subject_ref") != self.subject_ref
        ):
            raise BridgeError("handoff_peer_identity", "Remote source identity differs")
        return value

    async def call(self, tool, arguments, *, task_id=None):
        if tool not in TOOLS:
            raise BridgeError("handoff_peer_version", "Unsupported remote handoff operation")
        if tool in INTERACTIVE:
            raise BridgeError(
                "handoff_operator_required", "Use an explicit interactive TD decision"
            )
        return await self._post_call(tool, arguments)

    async def _post_call(self, tool, arguments):
        try:
            async with self._lock:
                value = await self._request("POST", json={"tool": tool, "arguments": arguments})
        except (httpx.HTTPError, BridgeError) as exc:
            if isinstance(exc, BridgeError) and exc.code in {
                "handoff_peer_rejected",
                "handoff_peer_closed",
            }:
                raise
            error = (
                UncertainExecution
                if tool not in {"get_return", "get_issued_handoff"}
                else BridgeError
            )
            raise error(
                "handoff_peer_unknown", "Remote transport outcome is unknown; do not replay"
            ) from None
        result = value.get("call")
        if (
            not isinstance(result, dict)
            or type(result.get("ok")) is not bool
            or (result["ok"] and not isinstance(result.get("result"), dict))
        ):
            error = (
                UncertainExecution
                if tool not in {"get_return", "get_issued_handoff"}
                else BridgeError
            )
            raise error("handoff_peer_unknown", "No exact remote operation receipt")
        if not result["ok"]:
            code = result.get("code", "handoff_peer_rejected")
            code = (
                code
                if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code)
                else "handoff_peer_rejected"
            )
            raise BridgeError(code, "ThreadDesk rejected the bounded handoff operation")
        return result["result"]

    async def reserve_attempt(self, envelope, principal):
        marker = {
            "handoff_id": envelope["source"]["handoff_id"],
            "core_task_id": envelope["request"]["task_id"],
            "device_ref": envelope["target"]["device_ref"],
            "operator_scope": self.operator_ref,
            "principal_ref": digest(principal),
            "request_sha256": envelope["request_sha256"],
            "envelope_sha256": digest(envelope),
        }
        receipt = await self._post_call("reserve_handoff_delivery", marker)
        lookup = await self.call("get_issued_handoff", {"handoff_id": marker["handoff_id"]})
        if (
            not isinstance(receipt, dict)
            or receipt.get("marker") != marker
            or type(receipt.get("duplicate")) is not bool
            or lookup.get("issued", {}).get("remote_delivery") != marker
        ):
            raise UncertainExecution(
                "remote_delivery_unknown", "No matching durable transport receipt"
            )
        return not receipt["duplicate"]

    def validate_run(self, task, record, *, device_certificate):
        """Executor-side check, including direct Core submissions outside the relay."""
        if certificate_identity(device_certificate).public_key_sha256 != self.device_key_sha256:
            raise BridgeError("remote_execution_binding", "Executor certificate differs")
        marker = record.get("remote_delivery")
        if not isinstance(marker, dict) or any(
            marker.get(key) != expected
            for key, expected in {
                "core_task_id": task["id"],
                "device_ref": self.device_ref,
                "operator_scope": self.operator_ref,
                "principal_ref": digest(task["principal"]),
                "request_sha256": task.get("request_sha256"),
            }.items()
        ):
            raise BridgeError("remote_execution_binding", "No exact device/request reservation")
