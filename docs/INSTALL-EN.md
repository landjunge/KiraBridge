# Install and update KiraBridge · 0.8.0rc20

[Deutsch](INSTALL-DE.md) · [README](../README.md)

The [published Intel preview](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20) is dated October 30, 2026.
Its code is pinned to `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4`.
[Release and download verification](README-REVIEW-20261031.md).

## Requirements

Regular user without sudo; Python 3.11, uv 0.11.6, a GitHub account with private
repository access, and Internet to GitHub/PyPI. The Terminal download command
below additionally needs an authenticated GitHub CLI (`gh`). Actual local testing
used macOS15.7.4 Intel x86_64. AppleSilicon, macOS26 and older macOS are unverified
by that evidence. A2015 iMac hardware label does not establish OS support.
The app is ad-hoc signed, without Apple notarization. No global Gatekeeper/TCC
changes or forced package-manager/compiler/Python installation are made. Set up agent/provider accounts separately.
Never put credentials in commands, logs or Git.

## Install or update

1. Download and fully extract the **App and service installer** ZIP from the
   [README](../README.md). Its included `INSTALLIEREN-DE.txt` gives the package instructions.
2. Open `KiraBridge-Installieren.command`. It launches the service installer in a
   visible Terminal window. Do not run it inside a working Codex/Grok session.
3. After successful installation, copy `KiraBridge.app` into `~/Applications`
   (create that folder if needed) and open it. Close an existing app before replacing it.

The separate **App only** ZIP needs an already installed service. Neither ZIP
includes Python or uv; provide Python 3.11 and uv 0.11.6 in Terminal first.
The installer does not connect a ChatGPT account automatically. Only if that
connection is missing, run `~/.local/bin/kirabridge chatgpt setup --language en`
in your local Terminal and follow the [connection guide](CHATGPT.md).

For a Terminal installation, retain the existing authenticated bootstrap route:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc20 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --require-visible-terminal --language en)
```

This downloads the installer to a file, checks it and then checks the pinned
service archive. For the fully extracted service archive, the direct entrypoint is:

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
original failure](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC14-ROLLBACK-20261026.md).

For BUSY, inspect the stated jobs; do not kill sessions or empty queues blindly.
For visibility changes, check the owned window instead of using another agent.
For checksum failure, stop and reacquire the authorized original. For403/404,
check private GitHub access. Preserve foreign services/ports. A readiness timeout
is a failure requiring logs and transaction review, never a success message.

## Known limitations in RC20

Interactive agent commands such as `/resume` sent through KiraBridge can arrive
as work instructions instead of opening the agent's menu. Enter those commands
directly in the agent's Terminal. Some ready Codex sessions can also be reported
as unavailable. Later local repairs are not part of the published RC20 download.

Apple Silicon, other macOS versions and other platforms have not been validated
by the Intel release tests. A received or approved request is not yet a finished
task; inspect an uncertain result before resubmitting it. Saved results do not
automatically wake an inactive chat. Availability in every chat or voice mode is
not guaranteed. [Release details and evidence](README-REVIEW-20261031.md).

## If macOS blocks the app

The app has no Apple notarization. Check that the download is from the linked
release and matches `SHA256SUMS-INTEL`; if it does not match, stop. If macOS blocks
an app you have verified and trust, use its per-app approval in System Settings →
Privacy & Security, if offered. Do not disable Gatekeeper globally. [Apple’s instructions](https://support.apple.com/en-us/102445).

## Other platforms and optional integrations

RC20 publishes no ready-to-install Linux, Windows or Apple Silicon package.
The independent Linux source installer remains available; Ubuntu24.04-x86_64
package acceptance is separate from macOS and ARM. Its own `sh install.sh
--language en` front door preserves guided setup and provider configuration.
ThreadDesk and vendor integrations are optional, not core installation requirements.

[macOS contract](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INSTALL-MACOS.md) · [Team operation](TEAM-ORCHESTRATION.md) ·
[ChatGPT setup](CHATGPT.md) · [RC20 release notes](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc20/docs/RELEASE-0.8.0rc20.md).
