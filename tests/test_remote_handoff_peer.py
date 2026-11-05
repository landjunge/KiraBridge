"""Bounded peer responses and unknown writes, without servers or providers."""

import httpx
import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
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
