"""Local one-time consent, with real private OAuth storage and no model calls."""

import base64
import hashlib
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import GrokConnectorConfig, PrincipalConfig
from kirabridge.grok_connector import state_dir
from kirabridge.grok_connector.auth_store import OAuthStore
from kirabridge.grok_connector.console import MAX_DECISION_BYTES, GrokConnectorConsole

KEY = "grok-connector-console-tests-" + "x" * 48
ISSUER = "https://kirabridge-console.example"
PRIVATE_STATE = "state-must-never-appear-in-operator-json"


@pytest.fixture
def connector_bridge(config):
    config.grok_connector = GrokConnectorConfig(enabled=True, public_origin=ISSUER)
    config.principals["grok_app"] = PrincipalConfig(
        approval_mode="automatic",
        capabilities=["bridge.health", "team.read", "team.write", "task.read"],
    )
    instance = Bridge(config)
    yield instance
    instance.store.close()


def browser(bridge, **kwargs):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ApprovalConsole(bridge, KEY), **kwargs),
        base_url=ORIGIN,
    )


def headers():
    return {"Authorization": "Bearer " + signed_token(KEY, "session"), "Origin": ORIGIN}


def store_for(bridge, issuer=ISSUER):
    return OAuthStore(
        state_dir(bridge.config) / "oauth.sqlite3",
        issuer=issuer,
        principal="grok_app",
    )


def pending(bridge, *, issuer=ISSUER, client_name="Grok connector test", client_id="test-client"):
    store = store_for(bridge, issuer)
    try:
        client = OAuthClientInformationFull(
            client_id=client_id,
            client_name=client_name,
            redirect_uris=["https://grok.com/kirabridge/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            scope="kirabridge",
        )
        store.register_client(client)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(b"v" * 43).digest()).rstrip(b"=")
        return store.request_authorization(
            client,
            AuthorizationParams(
                state=PRIVATE_STATE,
                scopes=["kirabridge"],
                code_challenge=challenge.decode(),
                redirect_uri=client.redirect_uris[0],
                redirect_uri_provided_explicitly=True,
                resource=issuer + "/mcp",
            ),
        )
    finally:
        store.close()


def endpoint(request_id):
    return "/api/grok-connector/" + request_id + "/decision"


async def test_disabled_connector_reads_no_oauth_store_and_creates_no_auth_state(
    bridge, monkeypatch
):
    monkeypatch.setattr(
        GrokConnectorConsole, "_store", lambda *args: pytest.fail("disabled store was opened")
    )
    async with browser(bridge) as client:
        result = await client.get("/api/grok-connector", headers=headers())
        assert result.status_code == 200
        assert result.json()["enabled"] is False
        assert result.json()["authorization"] is None and result.json()["pending"] == []
        assert (
            await client.post(endpoint("disabled"), headers=headers(), json={"allow": True})
        ).json()["error"] == "connector_disabled"
    assert not state_dir(bridge.config).exists()


async def test_connector_routes_retain_local_session_host_origin_and_csp(connector_bridge):
    async with browser(connector_bridge) as client:
        page = await client.get("/grok-connector")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        assert (await client.get("/api/grok-connector")).status_code == 401
        assert (
            await client.get("/api/grok-connector", headers={**headers(), "Host": "evil.example"})
        ).status_code == 403
        wrong_origin = await client.post(
            endpoint("not-opened"),
            headers={**headers(), "Origin": "https://evil.example"},
            json={"allow": True},
        )
        assert wrong_origin.status_code == 403
        assert "access-control-allow-origin" not in wrong_origin.headers
    async with browser(connector_bridge, client=("198.51.100.7", 1234)) as remote:
        assert (await remote.get("/grok-connector", headers=headers())).status_code == 403
    assert not state_dir(connector_bridge.config).exists()


async def test_pending_review_and_approval_do_not_disclose_code_state_or_change_task_policy(
    connector_bridge,
):
    request_id = pending(connector_bridge, client_name='<img src=x onerror="alert(1)">')
    before = {
        name: policy.model_dump() for name, policy in connector_bridge.config.principals.items()
    }
    async with browser(connector_bridge) as client:
        review = await client.get("/api/grok-connector", headers=headers())
        data = review.json()
        assert data["connector_url"] == ISSUER + "/mcp"
        assert data["principal"] == "grok_app" and data["cli_principal"] == "grok"
        assert data["task_approval_mode"] == "automatic"
        assert data["pending"][0]["id"] == request_id
        assert data["pending"][0]["redirect_uri"] == "https://grok.com/kirabridge/callback"
        assert data["pending"][0]["scopes"] == ["kirabridge"]
        assert PRIVATE_STATE not in review.text
        result = await client.post(endpoint(request_id), headers=headers(), json={"allow": True})
        assert result.json() == {"request_id": request_id, "status": "approved"}
        store = store_for(connector_bridge)
        try:
            poll = store.poll(request_id)
            code = parse_qs(urlsplit(poll["redirect_url"]).query)["code"][0]
        finally:
            store.close()
        after = await client.get("/api/grok-connector", headers=headers())
        assert after.json()["pending"] == []
        assert code not in result.text + after.text
        assert PRIVATE_STATE not in result.text + after.text
        assert "redirect_url" not in result.text + after.text
    assert {
        name: policy.model_dump() for name, policy in connector_bridge.config.principals.items()
    } == before
    assert connector_bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert connector_bridge.store.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0


async def test_one_time_denial_and_identical_decision_are_idempotent(connector_bridge):
    request_id = pending(connector_bridge)
    async with browser(connector_bridge) as client:
        first = await client.post(endpoint(request_id), headers=headers(), json={"allow": False})
        repeat = await client.post(endpoint(request_id), headers=headers(), json={"allow": False})
        assert first.json() == repeat.json() == {"request_id": request_id, "status": "denied"}
        conflict = await client.post(endpoint(request_id), headers=headers(), json={"allow": True})
        assert conflict.status_code == 409 and conflict.json()["error"] == "state_conflict"
        assert (await client.get("/api/grok-connector", headers=headers())).json()["pending"] == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"allow": 1},
        {"allow": "true"},
        {"allow": None},
        {"allow": True, "principal": "grok"},
    ],
)
async def test_decision_requires_explicit_boolean_without_an_actor_field(connector_bridge, payload):
    request_id = pending(connector_bridge)
    async with browser(connector_bridge) as client:
        denied = await client.post(endpoint(request_id), headers=headers(), json=payload)
        assert denied.status_code == 400
        review = (await client.get("/api/grok-connector", headers=headers())).json()
        assert [item["id"] for item in review["pending"]] == [request_id]


async def test_duplicate_oversized_and_wrong_content_type_decisions_are_rejected(connector_bridge):
    request_id = pending(connector_bridge)
    async with browser(connector_bridge) as client:
        json_headers = {**headers(), "Content-Type": "application/json"}
        duplicate = await client.post(
            endpoint(request_id), headers=json_headers, content='{"allow":true,"allow":false}'
        )
        assert duplicate.status_code == 400
        oversized = await client.post(
            endpoint(request_id), headers=json_headers, content=b" " * (MAX_DECISION_BYTES + 1)
        )
        assert oversized.status_code == 413
        wrong_type = await client.post(
            endpoint(request_id), headers=headers(), data={"allow": "true"}
        )
        assert wrong_type.status_code == 400
        assert (
            len((await client.get("/api/grok-connector", headers=headers())).json()["pending"]) == 1
        )


async def test_each_enabled_request_closes_its_store_even_on_missing_request(
    connector_bridge, monkeypatch
):
    pending(connector_bridge)
    closed = []
    original = OAuthStore.close

    def track(store):
        closed.append(store)
        original(store)

    monkeypatch.setattr(OAuthStore, "close", track)
    async with browser(connector_bridge) as client:
        assert (await client.get("/api/grok-connector", headers=headers())).status_code == 200
        assert (
            await client.post(endpoint("missing-request"), headers=headers(), json={"allow": True})
        ).status_code == 404
    assert len(closed) == 2
    for store in closed:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            store.db.execute("SELECT 1")


async def test_new_runtime_origin_replaces_old_url_and_cannot_approve_old_issuer(connector_bridge):
    request_id = pending(connector_bridge)
    profile = state_dir(connector_bridge.config) / "runtime-profile.json"
    new_origin = "https://replacement-tunnel.example"
    profile.write_text(
        json.dumps({"owner": "kirabridge-grok-app", "port": 8767, "public_origin": new_origin})
    )
    profile.chmod(0o600)
    async with browser(connector_bridge) as client:
        result = (await client.get("/api/grok-connector", headers=headers())).json()
        assert result["public_origin"] == new_origin
        assert result["connector_url"] == new_origin + "/mcp"
        assert result["authorization"]["issuer"] == new_origin
        assert result["pending"] == []
        assert (
            await client.post(endpoint(request_id), headers=headers(), json={"allow": True})
        ).status_code == 404
    assert connector_bridge.config.grok_connector.public_origin == ISSUER


async def test_conflicting_runtime_profile_reports_error_instead_of_stale_url(connector_bridge):
    directory = state_dir(connector_bridge.config)
    directory.mkdir(mode=0o700)
    profile = directory / "runtime-profile.json"
    profile.write_text(
        json.dumps({"owner": "foreign", "port": 8767, "public_origin": "https://wrong.example"})
    )
    profile.chmod(0o600)
    async with browser(connector_bridge) as client:
        result = await client.get("/api/grok-connector", headers=headers())
        assert result.status_code == 409
        assert result.json()["error"] == "connector_profile_conflict"
        assert ISSUER not in result.text and "wrong.example" not in result.text
    assert not (directory / "oauth.sqlite3").exists()


async def test_local_auth_receipt_never_claims_actual_phone_or_eve_voice_proof(connector_bridge):
    pending(connector_bridge)
    store = store_for(connector_bridge)
    try:
        store.record_use(
            "test-client", tool="bridge_health", request_ref="private-request-metadata"
        )
    finally:
        store.close()
    async with browser(connector_bridge) as client:
        response = await client.get("/api/grok-connector", headers=headers())
        data = response.json()
        assert data["authorization"]["last_use"]["tool"] == "bridge_health"
        assert data["mobile_app_call"] == data["eve_voice_tools"] == "unverified"
        assert data["gateway_reachability"] == "unverified"
        assert (
            "private-request-metadata" not in response.text and PRIVATE_STATE not in response.text
        )
