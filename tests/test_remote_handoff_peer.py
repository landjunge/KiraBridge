"""Bounded peer responses and unknown writes, without servers or providers."""

import json
from types import SimpleNamespace

import httpx
import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.remote_handoff_peer import FORMAT, HttpHandoffPeer


@pytest.fixture
async def peer():
    # No constructor/TLS bypass exists in the public API. This unit fixture isolates
    # response parsing; real pin/TLS/auth are exercised by test_remote_relay.py.
    value = object.__new__(HttpHandoffPeer)
    value.project_id, value.subject_ref = "project", "1" * 64
    import asyncio

    value._lock = asyncio.Lock()
    yield value
    if getattr(value, "_client", None) is not None:
        await value._client.aclose()


def response(peer, *, status=200, payload=None, body=None):
    def handle(request):
        return (
            httpx.Response(status, json=payload)
            if body is None
            else httpx.Response(status, content=body)
        )

    peer._client = httpx.AsyncClient(
        base_url="https://unit.invalid", transport=httpx.MockTransport(handle)
    )


@pytest.mark.parametrize(
    "status,body,payload",
    [
        (500, b"server unavailable", None),
        (200, b"invalid JSON", None),
        (200, b"x" * (1024 * 1024 + 1), None),
        (200, None, {"format": FORMAT, "project_id": "foreign", "subject_ref": "1" * 64}),
        (200, None, {"format": FORMAT, "project_id": "project", "subject_ref": "1" * 64}),
        (
            200,
            None,
            {
                "format": FORMAT,
                "project_id": "project",
                "subject_ref": "1" * 64,
                "call": {"ok": True},
            },
        ),
    ],
)
async def test_uncertain_writes_are_never_reported_as_safe_rejections(peer, status, body, payload):
    response(peer, status=status, body=body, payload=payload)
    with pytest.raises(UncertainExecution):
        await peer.call("import_return", {})


async def test_explicit_http_rejection_does_not_become_unknown(peer):
    response(peer, status=403, body=b"Forbidden")
    with pytest.raises(BridgeError) as exc:
        await peer.call("import_return", {})
    assert type(exc.value) is BridgeError and exc.value.code == "handoff_peer_rejected"


async def test_read_transport_failure_and_worker_review_are_distinct(peer):
    response(peer, status=503, body=b"Unavailable")
    with pytest.raises(BridgeError) as exc:
        await peer.call("get_return", {"return_id": "owned"})
    assert type(exc.value) is BridgeError and exc.value.code == "handoff_peer_unknown"
    with pytest.raises(BridgeError) as operator:
        await peer.call("review_return", {})
    assert operator.value.code == "handoff_operator_required"


@pytest.mark.parametrize(
    "failure", ["transport", "http", "rejected", "json", "identity", "logical", "null", "list"]
)
async def test_reservation_readback_failure_is_unknown(peer, failure):
    peer.operator_ref = "b" * 64
    calls, reservations = [], []
    envelope = {
        "source": {"handoff_id": "handoff-one"},
        "target": {"device_ref": "device-one"},
        "request": {"task_id": "core-one"},
        "request_sha256": "a" * 64,
    }

    def reply(value):
        return httpx.Response(
            200,
            json={
                "format": FORMAT,
                "project_id": peer.project_id,
                "subject_ref": peer.subject_ref,
                "call": {"ok": True, "result": value},
            },
        )

    def handle(request):
        body = json.loads(request.content)
        calls.append(body["tool"])
        if body["tool"] == "reserve_handoff_delivery":
            reservations.append(body["arguments"])
            return reply({"marker": body["arguments"], "duplicate": False})
        assert body["tool"] == "get_issued_handoff"
        if failure == "transport":
            raise httpx.ReadError("Lost readback", request=request)
        if failure in {"http", "rejected"}:
            return httpx.Response(503 if failure == "http" else 403)
        if failure == "json":
            return httpx.Response(200, content=b"invalid JSON")
        if failure == "identity":
            return httpx.Response(200, json={"format": FORMAT, "project_id": "foreign"})
        if failure == "logical":
            return httpx.Response(
                200,
                json={
                    "format": FORMAT,
                    "project_id": peer.project_id,
                    "subject_ref": peer.subject_ref,
                    "call": {"ok": False, "code": "not_found"},
                },
            )
        return reply({"found": False, "issued": None if failure == "null" else []})

    peer._client = httpx.AsyncClient(
        base_url="https://unit.invalid", transport=httpx.MockTransport(handle)
    )
    with pytest.raises(UncertainExecution) as exc:
        await peer.reserve_attempt(envelope, "local")
    assert exc.value.code == "remote_delivery_unknown"
    assert calls == ["reserve_handoff_delivery", "get_issued_handoff"]
    assert len(reservations) == 1


def execution_binding(peer, monkeypatch):
    # Isolate the request-proof boundary. Real certificate/key checks remain in
    # the paired TLS/Core integration tests; production never takes this shortcut.
    peer.device_key_sha256, peer.device_ref, peer.operator_ref = "c" * 64, "device-one", "b" * 64
    monkeypatch.setattr(
        "kirabridge.remote_handoff_peer.certificate_identity",
        lambda _: SimpleNamespace(public_key_sha256=peer.device_key_sha256),
    )
    task = {"id": "core-one", "principal": "local", "request_sha256": "a" * 64}
    marker = {
        "core_task_id": "core-one",
        "device_ref": "device-one",
        "operator_scope": peer.operator_ref,
        "principal_ref": digest("local"),
        "request_sha256": "a" * 64,
    }
    return task, {"remote_delivery": marker}


@pytest.mark.parametrize("invalid", ["missing", None, "", "a" * 63, "A" * 64, 7])
def test_run_binding_rejects_same_invalid_hashes(peer, monkeypatch, invalid):
    task, record = execution_binding(peer, monkeypatch)
    if invalid == "missing":
        task.pop("request_sha256")
        record["remote_delivery"].pop("request_sha256")
    else:
        task["request_sha256"] = record["remote_delivery"]["request_sha256"] = invalid
    with pytest.raises(BridgeError) as exc:
        peer.validate_run(task, record, device_certificate="fixture")
    assert exc.value.code == "remote_execution_binding"


def test_run_binding_accepts_matching_present_hash(peer, monkeypatch):
    task, record = execution_binding(peer, monkeypatch)
    assert peer.validate_run(task, record, device_certificate="fixture") is None
