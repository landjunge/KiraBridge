"""Real SDK OAuth/PKCE and MCP over in-process HTTP; no external accounts/models."""

import asyncio
import base64
import hashlib
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from mcp.server.auth.provider import AccessToken

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    GrokConnectorConfig,
    PrincipalConfig,
    TeamConfig,
    TeamWorkerConfig,
)
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.grok_connector.gateway import create_gateway
from kirabridge.grok_connector.provider import GrokOAuthProvider
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.team_manager.models import TeamCreate

ISSUER = "https://connector.example.test"
CALLBACK = "https://grok.com/oauth/callback"
PRIVATE_TOKEN = "private-grok-app-test-token-" + "x" * 40
CONSOLE_KEY = "local-connector-test-console-" + "c" * 40
VERIFIER = "grok-test-pkce-" + "v" * 48


class Relay(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.requests = []
        self.override = None

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self.override:
            return await self.override(request)
        return await self.inner.handle_async_request(request)


@pytest_asyncio.fixture
async def backend(config, monkeypatch):
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities += ["team.manage", "team.read", "team.write"]
    config.principals["grok_app"] = PrincipalConfig(
        approval_mode="automatic",
        capabilities=[
            "bridge.health",
            "task.read",
            "team.read",
            "team.write",
        ],
        roots=config.principals["local"].roots,
        token_env="GROK_APP_GATEWAY_TEST_TOKEN",
    )
    monkeypatch.setenv("GROK_APP_GATEWAY_TEST_TOKEN", PRIVATE_TOKEN)
    config.team = TeamConfig(
        enabled=True,
        workers={
            "local": TeamWorkerConfig(),
            "grok_app": TeamWorkerConfig(),
        },
    )
    config.grok_connector = GrokConnectorConfig(enabled=True, public_origin=ISSUER)
    bridge = Bridge(config)
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="connector-team",
            name="Connector test",
            coordinator="local",
            members={"local": "coordinator", "grok_app": "worker"},
            idempotency_key="create-team",
        ),
    )
    core = create_http_app(bridge)
    relay = Relay(core)
    async with bridge:
        # Exactly one SDK streamable-http lifespan belongs to the private core.
        # The gateway owns only its HTTP client and OAuth store, not another SDK server.
        ready, stop = asyncio.Event(), asyncio.Event()

        async def own_sdk_lifespan():
            async with core.app.router.lifespan_context(core.app):
                ready.set()
                await stop.wait()

        owner = asyncio.create_task(own_sdk_lifespan())
        await asyncio.wait_for(ready.wait(), 2)
        try:
            yield SimpleNamespace(config=config, bridge=bridge, relay=relay)
        finally:
            stop.set()
            await owner


@asynccontextmanager
async def open_gateway(backend):
    app = create_gateway(backend.config, transport=backend.relay)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=backend.config.grok_connector.public_origin,
            follow_redirects=False,
        ) as client:
            yield SimpleNamespace(
                **vars(backend), app=app, client=client, store=app.state.oauth_store
            )


@pytest_asyncio.fixture
async def gateway_env(backend):
    async with open_gateway(backend) as env:
        yield env


async def authorize(
    env, *, approve=True, auth_method="none", grant_types=None, omit_grant_types=False
):
    metadata = {
        "redirect_uris": [CALLBACK],
        "client_name": "Transport test client",
        "token_endpoint_auth_method": auth_method,
        "response_types": ["code"],
        "grant_types": grant_types
        if grant_types is not None
        else ["authorization_code", "refresh_token"],
        "scope": "kirabridge",
    }
    if omit_grant_types:
        metadata.pop("grant_types")
    registration = await env.client.post("/register", json=metadata)
    assert registration.status_code == 201, registration.text
    registered = registration.json()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
    )
    response = await env.client.get(
        "/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": CALLBACK,
            "response_type": "code",
            "scope": "kirabridge",
            "state": "test-state-bound",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": env.config.grok_connector.public_origin + "/mcp",
        },
    )
    assert response.status_code == 302, response.text
    pending = env.store.list_pending()
    request_id = response.headers["location"].rsplit("/", 1)[-1]
    assert any(item["id"] == request_id for item in pending)
    page = await env.client.get("/oauth/consent/" + request_id)
    assert (
        page.status_code == 200 and "script-src 'self'" in page.headers["content-security-policy"]
    )
    assert f'<strong id="connection-code">{request_id[-12:].upper()}</strong>' in page.text
    assert "Vergleiche diese Kennung mit der Anmeldung auf deinem Mac." in page.text
    assert "<input" not in page.text
    assert "test-state-bound" not in page.text and VERIFIER not in page.text
    assert (await env.client.get("/oauth/poll/" + request_id)).json()["status"] == "pending"
    # A real local-console session makes the decision. No remote route can approve it.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ApprovalConsole(env.bridge, CONSOLE_KEY)),
        base_url=ORIGIN,
    ) as operator:
        decision = await operator.post(
            "/api/grok-connector/" + request_id + "/decision",
            headers={
                "Authorization": "Bearer " + signed_token(CONSOLE_KEY, "session"),
                "Origin": ORIGIN,
            },
            json={"allow": approve},
        )
        assert decision.status_code == 200, decision.text
    polled = (await env.client.get("/oauth/poll/" + request_id)).json()
    if not approve:
        assert polled["status"] == "denied"
        return registered, None
    assert polled["status"] == "approved"
    redirect = urlsplit(polled["redirect_url"])
    query = parse_qs(redirect.query)
    assert redirect.scheme == "https" and redirect.hostname == "grok.com"
    assert query["state"] == ["test-state-bound"]
    assert query["iss"] == [env.config.grok_connector.public_origin]
    return registered, query["code"][0]


async def token(env, registered, code, **changes):
    method = registered["token_endpoint_auth_method"]
    credentials = {}
    auth = None
    if method == "client_secret_post":
        credentials["client_secret"] = registered["client_secret"]
    if method == "client_secret_basic":
        auth = httpx.BasicAuth(registered["client_id"], registered["client_secret"])
    return await env.client.post(
        "/token",
        auth=auth,
        data={
            "grant_type": "authorization_code",
            "client_id": registered["client_id"],
            "redirect_uri": CALLBACK,
            "code": code,
            "code_verifier": VERIFIER,
            "resource": env.config.grok_connector.public_origin + "/mcp",
            **credentials,
            **changes,
        },
    )


async def login(env):
    registered, code = await authorize(env)
    response = await token(env, registered, code)
    assert response.status_code == 200, response.text
    return registered, response.json()


async def rpc(env, access, method, params, request_id=1):
    return await env.client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + access,
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


async def test_sdk_oauth_local_consent_pkce_mcp_identity_and_private_task_boundaries(gateway_env):
    env = gateway_env
    metadata = (await env.client.get("/.well-known/oauth-authorization-server")).json()
    assert metadata["issuer"] == ISSUER
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert "none" in metadata["token_endpoint_auth_methods_supported"]
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    unauth = await env.client.post("/mcp", json={})
    assert unauth.status_code == 401
    assert (
        await env.client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer " + PRIVATE_TOKEN,
            },
            json={},
        )
    ).status_code == 401
    assert (
        ISSUER + "/.well-known/oauth-protected-resource/mcp" in unauth.headers["www-authenticate"]
    )
    resource = (await env.client.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert resource["resource"] == ISSUER + "/mcp"
    assert resource["authorization_servers"] == [ISSUER]
    registered, issued = await login(env)
    initialized = await rpc(
        env,
        issued["access_token"],
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "gateway-integration", "version": "1"},
        },
    )
    assert initialized.status_code == 200 and "serverInfo" in initialized.json()["result"]
    health = await rpc(
        env,
        issued["access_token"],
        "tools/call",
        {
            "name": "bridge_health",
            "arguments": {},
        },
        2,
    )
    assert health.status_code == 200
    assert health.json()["result"]["structuredContent"]["approval_mode"] == "automatic"
    sent = await rpc(
        env,
        issued["access_token"],
        "tools/call",
        {
            "name": "team_message_send",
            "arguments": {
                "request": {
                    "team_id": "connector-team",
                    "recipient": "local",
                    "body": "Hello from app identity",
                    "kind": "note",
                    "idempotency_key": "app-message",
                }
            },
        },
        3,
    )
    assert sent.json()["result"]["structuredContent"]["sender"] == "grok_app"
    spoof = await rpc(
        env,
        issued["access_token"],
        "tools/call",
        {
            "name": "team_message_send",
            "arguments": {
                "request": {
                    "team_id": "connector-team",
                    "recipient": "local",
                    "body": "spoof",
                    "idempotency_key": "spoof",
                    "sender": "grok",
                }
            },
        },
        4,
    )
    assert spoof.json()["result"]["isError"]
    private = env.bridge.submit(
        "local",
        TaskRequest(
            task_id="private-local-task",
            operation="file.list",
            arguments={"path": env.config.principals["local"].roots[0]},
            idempotency_key="private-task",
        ),
    )
    denied = await rpc(
        env,
        issued["access_token"],
        "tools/call",
        {
            "name": "task_get",
            "arguments": {"task_id": private["id"]},
        },
        5,
    )
    assert denied.json()["result"]["structuredContent"]["error"]["code"] == "not_found"
    assert all(
        request.headers["authorization"] == "Bearer " + PRIVATE_TOKEN
        for request in env.relay.requests
    )
    assert all(
        request.url.host == "127.0.0.1" and request.url.path == "/mcp"
        for request in env.relay.requests
    )
    assert issued["access_token"] not in str(env.store.status())
    assert (
        env.store.status()["last_use"]["client_id_sha256"]
        == hashlib.sha256(registered["client_id"].encode()).hexdigest()
    )


async def test_resource_pkce_and_code_replay_are_checked_before_grant_exchange(gateway_env):
    env = gateway_env
    registered, code = await authorize(env)
    assert (
        await token(env, registered, code, resource="https://other.example/mcp")
    ).status_code == 400
    assert (await token(env, registered, code, code_verifier="short")).status_code == 400
    assert (await token(env, registered, code, code_verifier="w" * 64)).status_code == 400
    issued = await token(env, registered, code)
    assert issued.status_code == 200
    replay = await token(env, registered, code)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert not env.relay.requests


async def test_refresh_rotation_replay_revokes_the_token_family(gateway_env):
    env = gateway_env
    registered, issued = await login(env)
    data = {
        "grant_type": "refresh_token",
        "client_id": registered["client_id"],
        "refresh_token": issued["refresh_token"],
        "resource": ISSUER + "/mcp",
    }
    rotated = await env.client.post("/token", data=data)
    assert rotated.status_code == 200
    assert rotated.json()["access_token"] != issued["access_token"]
    assert (await env.client.post("/token", data=data)).status_code == 400
    assert (await rpc(env, rotated.json()["access_token"], "tools/list", {})).status_code == 401


@pytest.mark.parametrize("auth_method", ["client_secret_post", "client_secret_basic"])
async def test_confidential_client_methods_use_sdk_authentication(gateway_env, auth_method):
    env = gateway_env
    registered, code = await authorize(env, auth_method=auth_method)
    issued = await token(env, registered, code)
    assert issued.status_code == 200
    assert (await rpc(env, issued.json()["access_token"], "tools/list", {})).status_code == 200


@pytest.mark.parametrize("auth_method", ["none", "client_secret_post", "client_secret_basic"])
async def test_code_only_registration_preserves_grants_and_never_issues_refresh(
    gateway_env, auth_method
):
    env = gateway_env
    registered, code = await authorize(
        env, auth_method=auth_method, grant_types=["authorization_code"]
    )
    assert registered["grant_types"] == ["authorization_code"]
    assert env.store.get_client(registered["client_id"]).grant_types == ["authorization_code"]
    if auth_method != "none":
        wrong = {**registered, "client_secret": "not-the-generated-secret"}
        assert (await token(env, wrong, code)).status_code == 401
    issued = await token(env, registered, code)
    assert issued.status_code == 200
    assert "refresh_token" not in issued.json()
    assert (await rpc(env, issued.json()["access_token"], "tools/list", {})).status_code == 200
    credentials, auth = {}, None
    if auth_method == "client_secret_post":
        credentials["client_secret"] = registered["client_secret"]
    if auth_method == "client_secret_basic":
        auth = httpx.BasicAuth(registered["client_id"], registered["client_secret"])
    denied = await env.client.post(
        "/token",
        auth=auth,
        data={
            "grant_type": "refresh_token",
            "client_id": registered["client_id"],
            "refresh_token": "never-issued",
            "resource": ISSUER + "/mcp",
            **credentials,
        },
    )
    assert denied.status_code == 400 and denied.json()["error"] == "unsupported_grant_type"


async def test_omitted_grant_types_default_to_code_only_without_refresh(gateway_env):
    env = gateway_env
    registered, code = await authorize(env, omit_grant_types=True)
    assert registered["grant_types"] == ["authorization_code"]
    issued = await token(env, registered, code)
    assert issued.status_code == 200 and "refresh_token" not in issued.json()
    assert (await rpc(env, issued.json()["access_token"], "tools/list", {})).status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "ungranted"},
        {"response_types": ["token"]},
        {"token_endpoint_auth_method": "private_key_jwt"},
        {"grant_types": ["refresh_token"]},
    ],
)
async def test_code_only_registration_keeps_scope_response_and_auth_validation(
    gateway_env, changes
):
    env = gateway_env
    response = await env.client.post(
        "/register",
        json={
            "redirect_uris": [CALLBACK],
            "client_name": "Invalid code-only client",
            "token_endpoint_auth_method": "none",
            "scope": "kirabridge",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            **changes,
        },
    )
    assert response.status_code == 400
    assert env.store.status()["counts"]["clients"] == 0


async def test_expired_and_wrong_resource_tokens_never_reach_daemon(gateway_env):
    env = gateway_env
    _, issued = await login(env)
    token_hash = hashlib.sha256(issued["access_token"].encode()).hexdigest()
    env.store.db.execute(
        "UPDATE oauth_tokens SET expires=? WHERE hash=?", (time.time() - 1, token_hash)
    )
    assert (await rpc(env, issued["access_token"], "tools/list", {})).status_code == 401
    env.store.db.execute(
        "UPDATE oauth_tokens SET expires=?,resource=? WHERE hash=?",
        (
            time.time() + 60,
            "https://wrong.example/mcp",
            token_hash,
        ),
    )
    assert (await rpc(env, issued["access_token"], "tools/list", {})).status_code == 401
    assert not env.relay.requests


@pytest.mark.parametrize(
    "changes",
    [
        {"scopes": ["other"]},
        {"subject": "grok"},
        {"claims": {"iss": "https://other.example"}},
        {"resource": ISSUER + "/mcp/"},
    ],
)
async def test_gateway_independently_checks_scope_subject_and_issuer(
    gateway_env, monkeypatch, changes
):
    env = gateway_env
    registered, issued = await login(env)

    async def incorrectly_verified(self, token):
        return AccessToken(
            **{
                "token": token,
                "client_id": registered["client_id"],
                "scopes": ["kirabridge"],
                "subject": "grok_app",
                "resource": ISSUER + "/mcp",
                "claims": {"iss": ISSUER},
                "expires_at": int(time.time()) + 60,
                **changes,
            }
        )

    monkeypatch.setattr(GrokOAuthProvider, "load_access_token", incorrectly_verified)
    assert (await rpc(env, issued["access_token"], "tools/list", {})).status_code == 401
    assert not env.relay.requests


async def test_gateway_restart_persists_grants_and_origin_change_rejects_old_tokens(backend):
    async with open_gateway(backend) as original:
        registered, code = await authorize(original)
    # New store/client instances after a complete gateway lifespan shutdown.
    async with open_gateway(backend) as restarted:
        issued = await token(restarted, registered, code)
        assert issued.status_code == 200
        access = issued.json()["access_token"]
        assert (await rpc(restarted, access, "tools/list", {})).status_code == 200
    backend.config.grok_connector.public_origin = "https://new-connector.example.test"
    async with open_gateway(backend) as moved:
        assert (await rpc(moved, access, "tools/list", {})).status_code == 401
        assert moved.store.list_pending() == []


async def test_host_origin_body_duplicate_parameter_and_route_boundaries(gateway_env):
    env = gateway_env
    assert (
        await env.client.get("/health", headers={"Host": "attacker.example"})
    ).status_code == 403
    assert (
        await env.client.get("/health", headers={"Origin": "https://attacker.example"})
    ).status_code == 403
    healthy = await env.client.get("/health")
    assert set(healthy.json()) == {"name", "version", "healthy"}
    assert "access-control-allow-origin" not in healthy.headers
    allowed = await env.client.options(
        "/mcp",
        headers={
            "Origin": "https://grok.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == "https://grok.com"
    assert "Authorization" in allowed.headers["access-control-allow-headers"]
    for path in ("/api/tasks", "/api/grok-connector", "/mcp/", "/oauth/consent/bad"):
        assert (await env.client.get(path)).status_code == 404
    assert (
        await env.client.post(
            "/token",
            content="resource=a&resource=b",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).status_code == 400
    assert (
        await env.client.post(
            "/register",
            content='{"client_name":"a","client_name":"b"}',
            headers={"Content-Type": "application/json"},
        )
    ).status_code == 400
    env.config.grok_connector.max_body_bytes = 1024
    assert (await env.client.post("/mcp", content=b"x" * 1025)).status_code == 413
    assert not env.relay.requests


async def test_upstream_timeouts_and_redirects_are_not_retried(gateway_env):
    env = gateway_env
    _, issued = await login(env)

    async def timeout(request):
        raise httpx.ReadTimeout("Do not expose private bearer/token URL", request=request)

    env.relay.override = timeout
    response = await rpc(env, issued["access_token"], "tools/list", {})
    assert response.status_code == 504 and response.json()["error"] == "upstream_outcome_unknown"
    assert len(env.relay.requests) == 1
    assert PRIVATE_TOKEN not in response.text and issued["access_token"] not in response.text

    async def redirect(request):
        return httpx.Response(307, headers={"Location": "https://attacker.example"})

    env.relay.override = redirect
    assert (await rpc(env, issued["access_token"], "tools/list", {})).status_code == 502
    assert len(env.relay.requests) == 2


async def test_proxy_concurrency_and_response_size_are_bounded(gateway_env):
    env = gateway_env
    _, issued = await login(env)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    env.relay.override = hold
    env.config.grok_connector.max_requests = 1
    first = asyncio.create_task(rpc(env, issued["access_token"], "tools/list", {}))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        assert (await env.client.get("/health")).status_code == 429
    finally:
        release.set()
        assert (await first).status_code == 200
    env.config.grok_connector.max_body_bytes = 1024

    async def huge(request):
        return httpx.Response(200, content=b"x" * 1025)

    env.relay.override = huge
    assert (await rpc(env, issued["access_token"], "tools/list", {})).status_code == 502


async def test_remote_denial_and_discovery_cors_do_not_expose_operator_authority(gateway_env):
    env = gateway_env
    await authorize(env, approve=False)
    response = await env.client.get(
        "/.well-known/oauth-authorization-server", headers={"Origin": "https://grok.com"}
    )
    assert response.headers["access-control-allow-origin"] == "https://grok.com"
    assert "WWW-Authenticate" in response.headers["access-control-expose-headers"]
    assert "*" not in response.headers.get("access-control-allow-origin", "")
    assert (
        await env.client.post("/api/grok-connector/fake/decision", json={"allow": True})
    ).status_code == 404
    script = (await env.client.get("/oauth/consent.js")).text
    assert "attempts > 300" in script and "setTimeout(poll, 2000)" in script
    assert "innerHTML" not in script and "localStorage" not in script
    assert not env.relay.requests
