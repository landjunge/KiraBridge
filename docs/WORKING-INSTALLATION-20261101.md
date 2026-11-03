# Verified working installation · 1 November 2026

The operator explicitly requested a working installation before more RC23
development. The original RC22/F97 package was hash-verified and run through
its supported visible installer in the single own installation window.
The installer confirmed that this exact version was already activated and valid.
It did not replace the running service with the RC24 worktree.

## Running identity

- Core: RC22, PID 4837, instance `1018a5a4e4b44df783963c76fe6cfe87`.
- Release commit: `f97ab1cdeebe1d06648febe685f7ebb738ca93a9`.
- 144 Python files, manifest
  `03bae2fd8715d4a7581e007096bf03633f7d978d6c590aec044a026512ab3986`.
- App: PID 4890; operator console observed active as PID 9355.
- Authenticated health: dispatcher active, maintenance absent, new work accepted.

Actual `file.read` task `working-install-kira-read-20261101T130724Z`
completed as principal `chatgpt`. Its initial queued receipt was subsequently
read by that same task ID; it was not resubmitted.
A fresh authenticated `session_catalog` returned available with two sessions.
These are actual local Kira-permission checks, not a claimed response inside
an external ChatGPT conversation.

## ChatGPT connection

The previous test-labelled tunnel service was stopped. Starting it established
healthy/ready transport, but its old label and command were not the regular
operator-managed ChatGPT service.

The supported RC22 `OperatorControl.service_action("chatgpt", "start", ...)`
created and started `com.kirabridge.chatgpt` using the existing named profile.
The old test label was booted out and its unchanged plist moved to the private
backup outside LaunchAgents, preventing a second runtime at login.
No remote tunnel, key, account grant or OS permission was created or changed.

The standard service runs as PID 9277. Independent process/socket observation
bound its actual loopback port 50775 to that PID. Both `/healthz` and `/readyz`
returned HTTP 200; the operator panel reports Core, ChatGPT and console active.
The official [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
describes these health and readiness checks separately from a ChatGPT tool call.

The tunnel client's separate alias registry still references historical PID
93493 and reports that cached process absent. That stale registry is not a
current process observation. No claim is made that its aggregate CLI
`connected` field is true or that a target ChatGPT chat has displayed a result.

Configuration, credentials, tunnel profile, Core plist and installation manifest
remain byte-identical to the new baseline. The old service definition is preserved.
The RC24 preflight implementation and renderer investigation remain separate.

## Recovery material

Private installer, dispatch, baseline, service migration, health, preservation
and Kira task receipts:
`~/.local/share/kirabridge/backups/working-install-priority-20261101T130724Z/`.
The RC22 runtime archive hash is
`a79ca78943e27e8089873335c90761e99b621c44028b10646242e63606203e10`;
the wheel hash is
`0bb0ece82e37d97d0891e774e6400e6bf5d9e42110067bc3032e43fb5df2f192`.
Restoring the legacy tunnel requires stopping the standard service first, then
returning its preserved plist and bootstrapping that single legacy label.
Never start both, restore an old database over current data or replay unknown work.
