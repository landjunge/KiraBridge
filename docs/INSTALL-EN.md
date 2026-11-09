# Install and update KiraBridge · 0.8.0rc36

[Deutsch](INSTALL-DE.md) · [README](../README.md)

The [published Intel preview](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36) is dated November 4, 2026.
Its code is pinned to `d4aebdd89a206045731f2692a3f363fddaa15ee0`.
[Release and download verification](evidence/readme-current-20261107.json).
This guide installs that published package. The separately installed local RC40
runtime at `d12838a` is a later source build, with no published RC40 download.

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

1. Download and fully extract **KiraBridge-0.8.0rc36-Intel-Installer.zip** from the
   [README](../README.md). The release also provides `SHA256SUMS` for verification.
2. Open `KiraBridge-Installer.app`, confirm and follow the visible Terminal
   installation. Do not use a working Codex/Grok session as the install window.
3. The installer updates the service and desktop app together, with a rollback
   backup. After success, open `KiraBridge.app` in `~/Applications`.

This ZIP includes the app/service payload; Python and uv remain prerequisites.
Provide Python 3.11 and uv 0.11.6 in Terminal first.
The installer does not connect a ChatGPT account automatically. Only if that
connection is missing, run `~/.local/bin/kirabridge chatgpt setup --language en`
in your local Terminal and follow the [connection guide](CHATGPT.md).

For a Terminal installation of the same app and service, use the authenticated bootstrap:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc36 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --desktop --require-visible-terminal --language en)
```

This downloads the installer to a file, checks it and then checks the pinned
service archive. For the fully extracted service archive, the direct entrypoint is:

```sh
sh KiraBridge/install.sh --desktop --require-visible-terminal --language en --motion full
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
`python3.11 KiraBridge/installer/install.py rollback --bundle KiraBridge --require-visible-terminal`
(the same package that was installed; without `--bundle` the desktop step aborts).
Do not replace new results
with an old database backup. A responding previous daemon proves recovery; a
restored pointer or timeout does not. [Actual focused rollback evidence and
original failure](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC14-ROLLBACK-20261026.md).

For BUSY, inspect the stated jobs; do not kill sessions or empty queues blindly.
For visibility changes, check the owned window instead of using another agent.
For checksum failure, stop and reacquire the authorized original. For403/404,
check private GitHub access. Preserve foreign services/ports. A readiness timeout
is a failure requiring logs and transaction review, never a success message.

## Known limitations in RC36

RC36 fixes window creation with minimized Terminal windows, but its subsequent
native checks reproduced a tab-switch failure. Later local RC37–RC40 repairs are
not included in this download. See the [RC36 report](TERMINAL-MINIMIZED-RC36-20261104.md)
and [subsequent recovery](TERMINAL-RECOVERY-20261104.md).
Interactive agent menus such as `/resume` are not equivalent to ordinary work
prompts; use the agent's own Terminal when its menu is needed.

Apple Silicon, other macOS versions and other platforms have not been validated
by the Intel release tests. A received or approved request is not yet a finished
task; inspect an uncertain result before resubmitting it. Saved results do not
automatically wake an inactive chat. Availability in every chat or voice mode is
not guaranteed. [Release details and evidence](evidence/readme-current-20261107.json).

## If macOS blocks the app

The app has no Apple notarization. Check that the download is from the linked
release and matches `SHA256SUMS`; if it does not match, stop. If macOS blocks
an app you have verified and trust, use its per-app approval in System Settings →
Privacy & Security, if offered. Do not disable Gatekeeper globally. [Apple’s instructions](https://support.apple.com/en-us/102445).

## Other platforms and optional integrations

The separate [Windows setup development preview](WINDOWS-SETUP-20261104.md)
provides a limited keyboard/window/MCP package, not current macOS feature parity
or a Windows service installer. Windows/installer and Linux/Debian server work is
in progress. Older published Linux artifacts do not establish acceptance of that
current server work. The source contains a separate Linux installer; its packaging
and native acceptance are independent of this Intel macOS guide.
ThreadDesk and vendor integrations are optional, not core installation requirements.

[macOS contract](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INSTALL-MACOS.md) · [Team operation](TEAM-ORCHESTRATION.md) ·
[ChatGPT setup](CHATGPT.md) · [RC36 release notes](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc36/docs/RELEASE-0.8.0rc36.md).
