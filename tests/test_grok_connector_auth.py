import base64
import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from starlette.applications import Starlette
from starlette.routing import Route

from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.grok_connector.auth_store import SCHEMA, OAuthStore, token_hash
from kirabridge.grok_connector.provider import GrokOAuthProvider

ISSUER = "https://kirabridge.example"
CALLBACK = "https://grok.com/connector/callback"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


@pytest.fixture
def store(tmp_path):
    value = OAuthStore(tmp_path / "private" / "oauth.sqlite3", issuer=ISSUER)
    yield value
    value.close()


@pytest.fixture
def provider(store):
    return GrokOAuthProvider(store)


def client(**updates):
    return OAuthClientInformationFull(
        **{
            "client_id": "client-one",
            "client_name": "Grok application",
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "kirabridge",
            **updates,
        }
    )


def params(**updates):
    return AuthorizationParams(
        **{
            "state": "STATE_SENTINEL",
            "scopes": ["kirabridge"],
            "code_challenge": CHALLENGE,
            "redirect_uri": CALLBACK,
            "redirect_uri_provided_explicitly": True,
            "resource": ISSUER + "/mcp",
            **updates,
        }
    )


async def authorization(provider, *, client_id="client-one", method="none", grant_types=None):
    registered = client(
        client_id=client_id,
        token_endpoint_auth_method=method,
        client_secret=None if method == "none" else "s" * 64,
        grant_types=grant_types or ["authorization_code", "refresh_token"],
    )
    await provider.register_client(registered)
    registered = await provider.get_client(client_id)
    url = await provider.authorize(registered, params())
    request_id = urlsplit(url).path.rsplit("/", 1)[-1]
    provider.store.decide(request_id, True)
    redirect = provider.store.poll(request_id)["redirect_url"]
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    return registered, request_id, code


async def tokens(provider):
    registered, request_id, code = await authorization(provider)
    loaded = await provider.load_authorization_code(registered, code)
    assert loaded is not None
    result = await provider.exchange_authorization_code(registered, loaded)
    return registered, request_id, code, result


async def test_mobile_app_switch_does_not_expire_approved_code_after_two_minutes(
    provider, monkeypatch
):
    import time

    now = time.time()
    monkeypatch.setattr("kirabridge.grok_connector.auth_store.time.time", lambda: now)
    registered, request_id, code = await authorization(provider)
    expires = provider.store.db.execute(
        "SELECT expires FROM oauth_requests WHERE id=?", (request_id,)
    ).fetchone()[0]
    assert expires <= now + 600
    now += 180
    assert provider.store.poll(request_id)["status"] == "approved"
    assert await provider.load_authorization_code(registered, code) is not None
    now += 421
    assert provider.store.poll(request_id)["status"] == "expired"
    assert await provider.load_authorization_code(registered, code) is None


def test_private_database_permissions_and_symlink_rejection(tmp_path):
    path = tmp_path / "state" / "oauth.sqlite3"
    value = OAuthStore(path, issuer=ISSUER)
    value.close()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        path.chmod(0o644)
        with pytest.raises(BridgeError, match="owner-only"):
            OAuthStore(path, issuer=ISSUER)
        path.chmod(0o600)
        link = path.parent / "linked.sqlite3"
        link.symlink_to(path)
        with pytest.raises(OSError):
            OAuthStore(link, issuer=ISSUER)


@pytest.mark.parametrize(
    "issuer",
    [
        "http://bridge.example",
        "https://u:p@bridge.example",
        "https://bridge.example/",
        "https://bridge.example/path",
        "https://bridge.example?x=1",
        "https://bridge.example#frag",
    ],
)
def test_issuer_must_be_a_pinned_https_origin(tmp_path, issuer):
    with pytest.raises(BridgeError, match="HTTPS"):
        OAuthStore(tmp_path / "state" / "oauth.sqlite3", issuer=issuer)


@pytest.mark.parametrize(
    "callback",
    [
        "http://grok.com/callback",
        "https://evil.example/callback",
        "https://grok.com.evil.example/cb",
        "https://sub.grok.com/callback",
        "https://user@grok.com/callback",
        "https://grok.com/callback#fragment",
        "https://grok.com:444/cb",
        "https://grok.com/cb?code=evil",
    ],
)
async def test_registered_redirects_require_exact_operator_https_hosts(provider, callback):
    with pytest.raises(RegistrationError) as error:
        await provider.register_client(client(redirect_uris=[callback]))
    assert error.value.error == "invalid_redirect_uri"


async def test_public_and_supported_confidential_clients_are_persisted(provider, store):
    for index, method in enumerate(["none", "client_secret_post", "client_secret_basic"]):
        supplied = client(
            client_id=f"client-{index}",
            token_endpoint_auth_method=method,
            client_secret=None if method == "none" else "s" * 64,
        )
        await provider.register_client(supplied)
        loaded = await provider.get_client(supplied.client_id)
        assert loaded.token_endpoint_auth_method == method and loaded.issuer == ISSUER
    with pytest.raises(RegistrationError):
        await provider.register_client(
            client(client_id="jwt", token_endpoint_auth_method="private_key_jwt")
        )
    assert store.status()["counts"]["clients"] == 3


async def test_pending_console_views_are_redacted_and_decisions_pin_redirect_and_state(
    provider, store
):
    await provider.register_client(client())
    url = await provider.authorize(client(), params())
    request_id = urlsplit(url).path.rsplit("/", 1)[-1]
    assert url == ISSUER + "/oauth/consent/" + request_id
    pending = store.list_pending()[0]
    assert set(pending) == {
        "id",
        "client_name",
        "redirect_uri",
        "scopes",
        "created",
        "expires_at",
        "principal",
    }
    assert pending["principal"] == "grok_app" and pending["redirect_uri"] == CALLBACK
    assert "STATE_SENTINEL" not in json.dumps(pending)
    assert store.poll(request_id) == {"status": "pending"}
    decision = store.decide(request_id, True)
    assert set(decision) == {"id", "status", "expires_at"}
    assert store.decide(request_id, True) == decision
    approved = store.poll(request_id)
    redirect = urlsplit(approved["redirect_url"])
    assert redirect.scheme + "://" + redirect.netloc + redirect.path == CALLBACK
    fields = parse_qs(redirect.query)
    assert fields["state"] == ["STATE_SENTINEL"] and fields["iss"] == [ISSUER]
    assert len(fields["code"][0]) >= 43
    with pytest.raises(BridgeError, match="already been decided"):
        store.decide(request_id, False)


@pytest.mark.parametrize(
    "updates,error",
    [
        ({"resource": None}, "invalid_request"),
        ({"resource": "https://foreign.example/mcp"}, "invalid_request"),
        ({"scopes": ["admin"]}, "invalid_scope"),
        ({"code_challenge": "plain-verifier"}, "invalid_request"),
        ({"redirect_uri": "https://grok.com/different"}, "invalid_request"),
    ],
)
async def test_authorization_requires_resource_pkce_registered_callback_and_single_scope(
    provider, updates, error
):
    await provider.register_client(client())
    with pytest.raises(AuthorizeError) as failure:
        await provider.authorize(client(), params(**updates))
    assert failure.value.error == error


async def test_sdk_verifies_pkce_before_single_use_token_exchange(provider, store):
    registered, request_id, code = await authorization(provider)
    handler = TokenHandler(provider, ClientAuthenticator(provider))
    app = Starlette(routes=[Route("/token", handler.handle, methods=["POST"])])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ISSUER) as caller:
        data = {
            "grant_type": "authorization_code",
            "client_id": registered.client_id,
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": "wrong",
            "resource": ISSUER + "/mcp",
        }
        rejected = await caller.post("/token", data=data)
        assert rejected.status_code == 400 and rejected.json()["error"] == "invalid_grant"
        accepted = await caller.post("/token", data={**data, "code_verifier": VERIFIER})
        assert accepted.status_code == 200
        access = accepted.json()["access_token"]
        assert (await provider.load_access_token(access)).subject == "grok_app"
        replay = await caller.post("/token", data={**data, "code_verifier": VERIFIER})
        assert replay.status_code == 400
        assert await provider.load_access_token(access) is None
        assert store.poll(request_id) == {"status": "expired"}


async def test_tokens_are_hashed_and_survive_restart_with_exact_subject_resource_issuer(
    provider, store, tmp_path
):
    registered, _, _, issued = await tokens(provider)
    loaded = await provider.load_access_token(issued.access_token)
    assert loaded.subject == "grok_app" and loaded.resource == ISSUER + "/mcp"
    assert loaded.claims == {"iss": ISSUER}
    dumped = "\n".join(store.db.iterdump())
    assert issued.access_token not in dumped and issued.refresh_token not in dumped
    assert VERIFIER not in dumped
    reopened = OAuthStore(tmp_path / "private" / "oauth.sqlite3", issuer=ISSUER)
    try:
        other = GrokOAuthProvider(reopened)
        assert (
            await other.load_access_token(issued.access_token)
        ).client_id == registered.client_id
        assert await other.load_refresh_token(registered, issued.refresh_token) is not None
    finally:
        reopened.close()


async def test_changed_issuer_or_subject_never_accepts_old_credentials(provider, tmp_path):
    registered, _, _, issued = await tokens(provider)
    for issuer, subject in [("https://new-tunnel.example", "grok_app"), (ISSUER, "other_app")]:
        value = OAuthStore(tmp_path / "private" / "oauth.sqlite3", issuer=issuer, principal=subject)
        try:
            other = GrokOAuthProvider(value)
            assert await other.get_client(registered.client_id) is None
            assert await other.load_access_token(issued.access_token) is None
            assert await other.load_refresh_token(registered, issued.refresh_token) is None
        finally:
            value.close()


async def test_refresh_rotation_invalidates_old_access_and_replay_revokes_entire_family(
    provider, store
):
    registered, _, _, issued = await tokens(provider)
    refresh = await provider.load_refresh_token(registered, issued.refresh_token)
    rotated = await provider.exchange_refresh_token(registered, refresh, ["kirabridge"])
    assert (
        rotated.access_token != issued.access_token
        and rotated.refresh_token != issued.refresh_token
    )
    assert await provider.load_access_token(issued.access_token) is None
    assert await provider.load_access_token(rotated.access_token) is not None
    assert await provider.load_refresh_token(registered, issued.refresh_token) is None
    assert await provider.load_access_token(rotated.access_token) is None
    assert await provider.load_refresh_token(registered, rotated.refresh_token) is None
    assert store.status()["counts"]["families"] == 0


async def test_wrong_client_cannot_redeem_or_revoke_another_clients_family(provider):
    registered, _, _, issued = await tokens(provider)
    foreign = client(client_id="client-two")
    await provider.register_client(foreign)
    assert await provider.load_refresh_token(foreign, issued.refresh_token) is None
    assert await provider.load_access_token(issued.access_token) is not None
    refresh = await provider.load_refresh_token(registered, issued.refresh_token)
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(foreign, refresh, ["kirabridge"])
    assert await provider.load_access_token(issued.access_token) is not None


async def test_atomic_refresh_exchange_cannot_mint_twice_and_replay_commits_revocation(
    provider, store
):
    registered, _, _, issued = await tokens(provider)
    refresh = await provider.load_refresh_token(registered, issued.refresh_token)

    def exchange(_):
        try:
            return store.exchange_refresh(registered, refresh, ["kirabridge"])
        except TokenError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(exchange, range(2)))
    assert sum(value is not None for value in values) == 1
    minted = next(value for value in values if value is not None)
    assert await provider.load_access_token(minted.access_token) is None
    assert (
        store.db.execute("SELECT count(*) FROM oauth_tokens WHERE generation=1").fetchone()[0] == 2
    )


async def test_client_revocation_denial_and_expiry_are_durable(provider, store, monkeypatch):
    registered, request_id, code = await authorization(provider)
    loaded = await provider.load_authorization_code(registered, code)
    store.revoke_client(registered.client_id)
    assert await provider.get_client(registered.client_id) is None
    assert await provider.load_authorization_code(registered, code) is None
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(registered, loaded)
    assert store.poll(request_id)["status"] == "denied"
    await provider.register_client(client(client_id="deny-client"))
    denied_id = urlsplit(
        await provider.authorize(client(client_id="deny-client"), params())
    ).path.rsplit("/", 1)[-1]
    assert store.decide(denied_id, False)["status"] == "denied"
    assert store.poll(denied_id) == {"status": "denied"}
    import kirabridge.grok_connector.auth_store as module

    before = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: before + 1000)
    assert store.poll(denied_id) == {"status": "expired"}
    assert store.db.execute("SELECT count(*) FROM oauth_audit").fetchone()[0] > 0


async def test_record_use_is_metadata_only_and_audit_chain_is_ordered(provider, store):
    registered, _, _, issued = await tokens(provider)
    store.record_use(registered.client_id, tool="team_get", request_ref="private-request-reference")
    status = store.status()
    assert status["last_use"]["client_id_sha256"] == token_hash(registered.client_id)
    assert status["last_use"]["tool"] == "team_get"
    dumped = json.dumps(status)
    assert "private-request-reference" not in dumped and issued.access_token not in dumped
    previous = "0" * 64
    for row in store.db.execute("SELECT * FROM oauth_audit ORDER BY seq"):
        record = {
            "at": row["at"],
            "kind": row["kind"],
            "metadata": json.loads(row["metadata"]),
            "previous": row["previous"],
        }
        assert row["previous"] == previous and row["hash"] == digest(record)
        previous = row["hash"]
    audit = " ".join(row[0] for row in store.db.execute("SELECT metadata FROM oauth_audit"))
    assert "STATE_SENTINEL" not in audit and VERIFIER not in audit


async def test_client_and_pending_queues_are_bounded(provider, store, monkeypatch):
    import kirabridge.grok_connector.auth_store as module

    clock = [module.time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    for index in range(32):
        if index == 16:
            clock[0] += 61
        await provider.register_client(client(client_id=f"bounded-{index}"))
    assert store.status()["counts"]["clients"] == 32
    with pytest.raises(RegistrationError):
        await provider.register_client(client(client_id="over-capacity"))
    supplied = client(client_id="bounded-0")
    for _ in range(16):
        await provider.authorize(supplied, params())
    with pytest.raises(AuthorizeError) as error:
        await provider.authorize(supplied, params())
    assert error.value.error == "temporarily_unavailable"


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_sdk_confidential_client_authentication_requires_its_registered_secret(
    provider, method
):
    registered, _, code = await authorization(provider, method=method)
    handler = TokenHandler(provider, ClientAuthenticator(provider))
    app = Starlette(routes=[Route("/token", handler.handle, methods=["POST"])])
    data = {
        "grant_type": "authorization_code",
        "client_id": registered.client_id,
        "code": code,
        "redirect_uri": CALLBACK,
        "code_verifier": VERIFIER,
        "resource": ISSUER + "/mcp",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ISSUER) as caller:
        rejected = await caller.post("/token", data=data)
        assert rejected.status_code == 401
        if method == "client_secret_post":
            accepted = await caller.post(
                "/token", data={**data, "client_secret": registered.client_secret}
            )
        else:
            basic = base64.b64encode(
                (registered.client_id + ":" + registered.client_secret).encode()
            ).decode()
            accepted = await caller.post(
                "/token", data=data, headers={"Authorization": "Basic " + basic}
            )
        assert accepted.status_code == 200


async def test_expired_authorization_code_never_mints_a_token_and_audit_is_preserved(
    provider, store, monkeypatch
):
    registered, request_id, code = await authorization(provider)
    loaded = await provider.load_authorization_code(registered, code)
    import kirabridge.grok_connector.auth_store as module

    after_expiry = loaded.expires_at + 1
    monkeypatch.setattr(module.time, "time", lambda: after_expiry)
    assert await provider.load_authorization_code(registered, code) is None
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(registered, loaded)
    assert store.poll(request_id) == {"status": "expired"}
    assert store.db.execute("SELECT count(*) FROM oauth_tokens").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM oauth_audit").fetchone()[0] > 0


async def test_access_and_absolute_family_expiry_do_not_allow_refresh_after_seven_days(
    provider, store, monkeypatch
):
    registered, _, _, issued = await tokens(provider)
    import kirabridge.grok_connector.auth_store as module

    created = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: created + 3601)
    assert await provider.load_access_token(issued.access_token) is None
    refresh = await provider.load_refresh_token(registered, issued.refresh_token)
    assert refresh is not None
    monkeypatch.setattr(module.time, "time", lambda: created + 7 * 86400 + 1)
    assert await provider.load_refresh_token(registered, issued.refresh_token) is None
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(registered, refresh, ["kirabridge"])
    assert store.status()["counts"]["families"] == 0
    assert store.db.execute("SELECT count(*) FROM oauth_tokens").fetchone()[0] == 0


async def test_rotation_limit_bounds_family_storage_and_revokes_on_exhaustion(provider, store):
    registered, _, _, issued = await tokens(provider)
    refresh = await provider.load_refresh_token(registered, issued.refresh_token)
    store.db.execute("UPDATE oauth_tokens SET generation=256 WHERE kind='refresh'")
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(registered, refresh, ["kirabridge"])
    assert await provider.load_access_token(issued.access_token) is None
    assert store.db.execute("SELECT count(*) FROM oauth_tokens").fetchone()[0] == 2


async def test_code_only_client_sdk_flow_returns_access_without_any_refresh_grant(provider, store):
    registered, _, code = await authorization(provider, grant_types=["authorization_code"])
    assert registered.grant_types == ["authorization_code"]
    handler = TokenHandler(provider, ClientAuthenticator(provider))
    app = Starlette(routes=[Route("/token", handler.handle, methods=["POST"])])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ISSUER) as caller:
        accepted = await caller.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered.client_id,
                "code": code,
                "redirect_uri": CALLBACK,
                "code_verifier": VERIFIER,
                "resource": ISSUER + "/mcp",
            },
        )
        assert accepted.status_code == 200
        result = accepted.json()
        assert "access_token" in result and "refresh_token" not in result
        assert (await provider.load_access_token(result["access_token"])).subject == "grok_app"
        unsupported = await caller.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registered.client_id,
                "refresh_token": "x" * 64,
                "resource": ISSUER + "/mcp",
            },
        )
        assert unsupported.status_code == 400
        assert unsupported.json()["error"] == "unsupported_grant_type"
    assert (
        store.db.execute("SELECT count(*) FROM oauth_tokens WHERE kind='refresh'").fetchone()[0]
        == 0
    )
    family = store.db.execute("SELECT * FROM oauth_families").fetchone()
    assert family["expires"] - family["created"] == 3600


@pytest.mark.parametrize(
    "grants", [[], ["refresh_token"], ["authorization_code", "client_credentials"]]
)
async def test_registration_rejects_missing_code_or_unimplemented_grant_types(provider, grants):
    with pytest.raises(RegistrationError):
        await provider.register_client(client(grant_types=grants))


async def test_registration_rate_is_bounded_without_retaining_rejected_client_metadata(
    provider, store, monkeypatch
):
    import kirabridge.grok_connector.auth_store as module

    clock = [module.time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    for index in range(16):
        await provider.register_client(client(client_id=f"rate-{index}"))
    with pytest.raises(RegistrationError) as error:
        await provider.register_client(client(client_id="limited"))
    assert "rate limit" in error.value.error_description
    assert store.status()["counts"]["clients"] == 16
    clock[0] += 61
    await provider.register_client(client(client_id="after-window"))
    assert store.status()["counts"]["clients"] == 17


async def test_unauthorized_client_ttl_preserves_pending_and_once_approved_registrations(
    provider, store, monkeypatch
):
    import kirabridge.grok_connector.auth_store as module

    clock = [module.time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    await provider.register_client(client(client_id="unused"))
    await authorization(provider, client_id="approved")
    await provider.register_client(client(client_id="pending"))
    clock[0] += 3500
    await provider.authorize(client(client_id="pending"), params())
    audit_count = store.db.execute("SELECT count(*) FROM oauth_audit").fetchone()[0]
    clock[0] += 101
    assert store.status()["counts"]["clients"] == 2
    assert await provider.get_client("unused") is None
    assert await provider.get_client("approved") is not None
    assert await provider.get_client("pending") is not None
    clock[0] += 601
    assert store.status()["counts"]["clients"] == 1
    assert await provider.get_client("approved") is not None
    assert await provider.get_client("pending") is None
    assert store.db.execute("SELECT count(*) FROM oauth_audit").fetchone()[0] == audit_count


def test_original_schema_upgrade_preserves_clients_and_recovers_family_and_audit_approvals(
    tmp_path, monkeypatch
):
    import kirabridge.grok_connector.auth_store as module

    clock = [module.time.time()]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    path = tmp_path / "private" / "oauth.sqlite3"
    path.parent.mkdir(mode=0o700)
    original_schema = SCHEMA.replace(", authorized INTEGER NOT NULL DEFAULT 0", "")
    with sqlite3.connect(path) as db:
        db.executescript(original_schema)
        db.execute("PRAGMA user_version=1")
        for name in ("family", "audit-approved", "unused"):
            db.execute(
                "INSERT INTO oauth_clients VALUES(?,?,?,?,?,NULL)",
                (name, ISSUER, "grok_app", client(client_id=name).model_dump_json(), clock[0]),
            )
        db.execute(
            "INSERT INTO oauth_families VALUES(?,?,?,?,?,?,?,NULL)",
            ("family-id", "family", ISSUER, ISSUER + "/mcp", "grok_app", clock[0], clock[0] + 3600),
        )
        previous = "0" * 64
        for kind, metadata in [
            (
                "oauth.consent_requested",
                {"request_id": "old-request", "client_id_sha256": token_hash("audit-approved")},
            ),
            ("oauth.consent_approved", {"request_id": "old-request"}),
        ]:
            record = {"at": clock[0], "kind": kind, "metadata": metadata, "previous": previous}
            value = digest(record)
            db.execute(
                "INSERT INTO oauth_audit(at,kind,metadata,previous,hash) VALUES(?,?,?,?,?)",
                (clock[0], kind, canonical(metadata), previous, value),
            )
            previous = value
        before_clients = db.execute(
            "SELECT id,metadata,created FROM oauth_clients ORDER BY id"
        ).fetchall()
        before_audit = db.execute("SELECT * FROM oauth_audit ORDER BY seq").fetchall()
    path.chmod(0o600)
    for _ in range(2):
        upgraded = OAuthStore(path, issuer=ISSUER)
        try:
            assert [
                tuple(row)
                for row in upgraded.db.execute(
                    "SELECT id,metadata,created FROM oauth_clients ORDER BY id"
                )
            ] == before_clients
            assert {
                row["id"]: row["authorized"]
                for row in upgraded.db.execute("SELECT id,authorized FROM oauth_clients")
            } == {"family": 1, "audit-approved": 1, "unused": 0}
            assert [
                tuple(row) for row in upgraded.db.execute("SELECT * FROM oauth_audit ORDER BY seq")
            ] == before_audit
        finally:
            upgraded.close()
    clock[0] += 3601
    upgraded = OAuthStore(path, issuer=ISSUER)
    try:
        assert upgraded.status()["counts"]["clients"] == 2
        assert upgraded.get_client("family") is not None
        assert upgraded.get_client("audit-approved") is not None
    finally:
        upgraded.close()
