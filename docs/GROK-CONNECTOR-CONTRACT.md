# Grok app connector implementation contract

Worktree: `.worktrees/grok-app-connector-20261019`, base main fdbca29.
Existing runtime remains separate and all foreign edits are preserved.

Identity: existing `grok` is the CLI/ACP worker; new `grok_app` is an external,
manual team member for the Grok mobile/web application (including Eve if its
voice mode actually calls custom tools). Do not claim app/voice proof before a
real authenticated call from that app. No paid voice API or new AI account.

## Root configuration and setup

`Config.grok_connector: GrokConnectorConfig` default disabled. Fields:
`enabled=False`, `public_origin: str|None=None` (HTTPS origin only, no path,
credentials/query/fragment), `principal='grok_app'`, `port=8767`,
`redirect_hosts=['grok.com','accounts.x.ai','console.x.ai']` exact hosts,
`max_requests=16`, `max_body_bytes=2097152`.
`state_dir(config)` = config.state_path/'grok-app-connector'.
`OAuthStore` path = state_dir/'oauth.sqlite3'. The local authenticated console
uses the same store to review one initial connector authorization; this is not
per-task approval. The existing automatic task policy remains in force.
The separate gateway binds loopback. An outbound TLS tunnel may expose only
that gateway; never expose local operator console or the whole private daemon.

## team_domain owns auth_store.py, provider.py and matching tests

New package `src/kirabridge/grok_connector/` (root owns __init__, runtime/setup).
`OAuthStore(path:Path, *, issuer:str, principal:str='grok_app',
redirect_hosts:list[str]|None=None)` with .issuer and .principal.
`issuer` is the configured canonical HTTPS origin; resource is issuer+'/mcp'.
Use SDK OAuthAuthorizationServerProvider with MCP 1.30 (already installed), not
an invented OAuth transport. Code/refresh redemption atomic, persisted after
restart; no plaintext long-lived access/refresh tokens in database or logs.
Store static client secrets only in private 0600 data if needed by SDK auth.

Public operator methods (sync):
- list_pending()->list[dict]: id, client_name, redirect_uri, scopes, created,
  expires_at, principal; never code/token/state/verifier.
- decide(request_id, allow:bool)->dict: local operator approval/denial only.
- poll(request_id)->dict: status pending/approved/denied/expired; approved has
  redirect_url pinned to original registered URI + code + state + issuer.
- status()->dict sanitized counts and last receipt evidence, no secrets.
- revoke_client(client_id)->None; close().

`GrokOAuthProvider(store)` implements SDK provider methods. `authorize` returns
issuer+'/oauth/consent/'+opaque request id. Require resource exact issuer+'/mcp',
PKCE S256 validated by SDK, registered exact HTTPS redirect URI on operator
allowed hosts, no fragment/userinfo. Single scope `kirabridge`. Support public
clients and SDK supported confidential methods; fixed authenticated subject is
store.principal. Refresh rotates access/refresh and reuse revokes family.
Audit own ordered chain metadata IDs/hashes only. Bounds: clients32,
pending16, token families64; expired cleanup does not delete audit history.
Access1h, refresh7d, pending10min, code2min. Issuer/resource is bound on every
stored grant/token; changed tunnel origin never accepts old credentials.

Code-only clients receive no refresh token; omitted grant types mean code-only.
Registration is limited to 16/minute and unused, unapproved clients expire after
one hour. Authorized-client metadata and ordered audit history remain intact.
An additive migration preserves approvals from the original connector schema.

## team_dispatcher owns gateway.py and transport/integration tests

`create_gateway(config, *, transport: httpx.AsyncBaseTransport|None=None)` returns
Starlette/ASGI app with own lifespan. It opens OAuthStore above and provider,
uses SDK `create_auth_routes` + protected-resource metadata; mounts `/mcp` with
OAuth bearer/resource/scope validation. Enforce resource also at /token because
SDK token handler does not pass token-request resource into provider methods.

Proxy authenticated /mcp to `peer(config,config.grok_connector.principal)` at
fixed loopback endpoint; replace bearer with local token, never forward external
OAuth token or user-supplied principal. Only GET/POST/DELETE MCP routing, bounded
request/response/concurrency; stateless JSON responses, no blind retries or
forwarding approval/operator routes. Validate Host against configured origin /
loopback; reject hostile Origin. /oauth/consent/{id} serves minimal safe page
with external script /oauth/consent.js and finite polling of /oauth/poll/{id}.
No account passwords or provider API keys requested. Remote browser waits for
one approval in local console. Optional clean direct link to local console only
for users physically at Mac. Read-only unauth /health may disclose only version,
gateway healthy; no private bridge metadata. Disable access logs at serve.
Attach auth store on app.state.oauth_store for operator/test inspection.
No CORS wildcard, redirects or private token in error/log output.
Both consent windows display the final twelve request-ID characters in uppercase
as a connection reference, without adding another input or per-task approval.
Integration: real OAuth DCR/authorize/local decision/PKCE/token/MCP call and
expired/wrong audience/replay/refresh/restart/forged sender/foreign task checks;
controlled temporary fixtures only, no paid models or production changes.

## team_console owns console.py, its tests and docs/GROK-APP-CONNECTOR.md

`GrokConnectorConsole(bridge,authenticate)` supplies .routes. Read current config
settings; no auth-store creation when connector is disabled. Routes:
`/grok-connector`, `/grok-connector.js`, `/grok-connector.css`,
GET `/api/grok-connector`, POST `/api/grok-connector/{request_id}/decision` with
JSON `{allow:true|false}`. Authenticate using same local bearer and inherited
Host/Origin/CSP protections; fixed operator local, not user-selected fields.
Open store per request and close; callback and client metadata render text only.
Show pending approvals, public connector URL, current status plus honest voice
unverified state. Approve linkage once; no change to per-task automatic grants.
Root integrates routes/nav and CLI, handles tunnel/runtime and activation.
