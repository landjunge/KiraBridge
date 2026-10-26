# Install and update KiraBridge · 0.8.0rc17

RC17 Intel acceptance and explicit operator approval are recorded in
[Intel acceptance](INTEL-ACCEPTANCE-20261026.md). Actual
[release status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17)
and the responding installed service remain separate; a draft is unpublished.

## Requirements

Regular user without sudo; Python3.11, uv0.11.6, authenticated GitHubCLI with
private repository/draft access, and Internet to GitHub/PyPI. Actual local testing
used macOS15.7.4 Intel x86_64. AppleSilicon, macOS26 and older macOS are unverified
by that evidence. A2015 iMac hardware label does not establish OS support.
No Apple signing/notarization, no global Gatekeeper/TCC changes, no forced
package-manager/compiler/Python installation. Set up agent/provider accounts separately.
Never put credentials in commands, logs or Git.

## Install or update

Use the single authenticated install/update command in the [README](../README.md).
It verifies the bootstrap and package before execution. After verified extraction,
the direct visible entrypoint is:

```sh
sh KiraBridge/install.sh --require-visible-terminal --language en --motion full
```

`--motion reduced` disables motion. These presentation switches are not
claimed supported by older archives. The hashed stdlib renderer is optional;
real progress, errors and prompts take priority. Unknown terminal capabilities
fall back to static Unicode/plain text. Human graphics never enter MCP or statusJSON.

Reuse one confirmed owned visible work/install window. Verify front window,
selected tab, TTY and current process identities before activation. Never type
into a live Codex/Grok session and never substitute a hidden terminal.

Fresh installation creates user-owned state. The versioned updater preserves
configuration, credentials, rights, Whiteboards, database and user files, checks
idle/ownership/integrity, and keeps a recovery record. Busy work, foreign services
and changed definitions stop activation. Unknown work is never blindly replayed.

The launchd user service continues when Terminal/browser windows close; login,
logout, sleep and shutdown are distinct. Presentation does not own the daemon.

## Status, errors and rollback

`~/.local/bin/kirabridge status` reads the responding version and service state.
`python3.11 KiraBridge/installer/install.py status` also reports the installed commit.
Only after active work is resolved, the operator can restart using
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge`, then read status again.

Logs: `~/.local/share/kirabridge/install/logs/`. Versioned runtimes/backups:
`~/.local/share/kirabridge/install/`. Configuration/credentials:
`~/.config/kirabridge/`. The updater does not rewrite shell profiles or PATH.

Use the retained package and transaction backup for
`python3.11 KiraBridge/installer/install.py rollback`. Do not replace new results
with an old database backup. A responding previous daemon proves recovery; a
restored pointer or timeout does not. [Actual focused rollback evidence and
original failure](RC14-ROLLBACK-20261026.md).

For BUSY, inspect the stated jobs; do not kill sessions or empty queues blindly.
For visibility changes, check the owned window instead of using another agent.
For checksum failure, stop and reacquire the authorized original. For403/404,
check private GitHub access. Preserve foreign services/ports. A readiness timeout
is a failure requiring logs and transaction review, never a success message.

## Other platforms and optional integrations

The independent Linux source installer remains available; Ubuntu24.04-x86_64
package acceptance is separate from macOS and ARM. Its own `sh install.sh
--language en` front door preserves guided setup and provider configuration.
ThreadDesk and vendor integrations are optional, not core installation requirements.

[macOS contract](INSTALL-MACOS.md) · [Team operation](TEAM-ORCHESTRATION.md) ·
[ChatGPT setup](CHATGPT.md) · [Release notes](RELEASE-0.8.0rc17.md).
