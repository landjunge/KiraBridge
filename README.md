[Deutsch](README.de.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-256.png">
  <img src="assets/design/icons/light/KiraBridge-light-256.png" alt="KiraBridge" width="160" height="160">
</picture>

# KiraBridge

**Talk to your AI. Get the work done on your computer.**

KiraBridge connects ChatGPT to **Grok Build and Codex running in terminal windows
on your computer**. Discuss what you need in chat, pass the work to those terminal
agents and follow their replies while choosing what they may access.

**macOS · Intel — [0.8.0rc36](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36) · November 4, 2026 · Preview**

### [Download KiraBridge — app and installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc36/KiraBridge-0.8.0rc36-Intel-Installer.zip)

[Checksums](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc36/SHA256SUMS)
· [All releases](https://github.com/landjunge/KiraBridge/releases)

Downloads require a GitHub account with access to this private repository.
This is a preview; there is no stable release yet. RC36 is available for Intel Macs.

The earlier RC33 release includes a [Windows 11 development preview](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc33/KiraBridge-0.8.0rc33-Windows-Dev-Kit.zip)
with native keyboard, shortcuts and guarded window control. It is a separate
development kit; general Windows file, process and terminal tools remain outside
its scope. See [RC33 package checks, installation status and limits](docs/RC33-DELIVERY-20261104.md).

The published [Windows setup wizard 0.8.0rc37.dev1](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc37.dev1)
has verified download and separate Windows installation evidence.
All seven native phases for that limited development preview passed. Extract the package and open
**Einrichtung-starten.cmd** for four guided steps. Account sign-in and a real
ChatGPT connection test with your account remain yours to complete.
[Evidence and limits](docs/WINDOWS-SETUP-20261104.md) ·
[Setup guide, German](docs/WINDOWS-SETUP.md).

**Reviewed repository implementation: 0.8.0rc41 at `a81cd1052e2a472eeae4ac388cb8c89e10af4c1d`.**
This tip includes the integrated Windows standalone source and is newer than the published Linux package source `350d368`.
The installed Intel package, read again on 2026-11-07 from its `release.json` and package version, remains 0.8.0rc40 at `d12838a`.
The published Intel download above remains RC36 at `d4aebdd`.
[Release, artifact and installed-source evidence](docs/evidence/readme-current-20261107.json).
The [earlier PR61 installation report](docs/RC40-PR61-SHIM-INSTALL-20261106.md)
describes the previous RC40 source `a5d381a`.

The standalone installer source is integrated ([Windows standalone package](docs/WINDOWS-STANDALONE-20261107.md)); no standalone ZIP or newer Windows package is published.
Windows feature parity with the Intel app remains open. The published Windows preview does not include general
file, process or terminal tools, or Windows service installation. No published RC40 download is offered here.


## What KiraBridge helps you do

- **Work on local projects:** let your connected AI read project files and logs,
  edit files or run commands within the access you have granted.
- **Work with terminal agents:** send tasks to Grok Build and Codex in their
  configured terminal sessions on your computer.
- **Follow the work:** see requests, messages and results in the local control window.
- **Choose the permissions:** decide which folders and actions are allowed and
  when a task needs your approval.

ThreadDesk and other integrations are optional. KiraBridge's core works independently.

## Get started

1. **Install or update.** Download and fully extract the Intel installer ZIP.
   Open `KiraBridge-Installer.app` and follow its confirmation and visible Terminal
   installation. Use a separate Terminal window; preserve running agent sessions.
2. **Open the app.** The installer updates the service and desktop app together.
   Open `KiraBridge.app` in `~/Applications`. Existing settings and credentials
   remain; the installer creates a rollback backup.
3. **Connect your chat.** Follow the [ChatGPT connection guide](docs/CHATGPT.md#english-connect-then-confirm-the-actual-task).
   Start by asking it to read a small file from an allowed folder. Approve the
   request if asked, then check the result in your chat.

**Requirements:** Intel Mac, tested on macOS 15.7.4; Python 3.11 and uv 0.11.6
already available in Terminal; internet access to download dependencies.
Install with your regular user account. AI accounts and any provider charges are
separate; the chat connection needs the corresponding account permissions.
For terminal-agent tasks, install and sign in to Grok Build or Codex, then
configure its terminal session as a target in KiraBridge.

This preview has known terminal limitations, and the app is not Apple-notarized.
See [RC36 fixes, checks and limits](docs/TERMINAL-MINIMIZED-RC36-20261104.md) for the current
package; see [installation, verification and help](docs/INSTALL-EN.md).


## Linux / Debian server

The [integrated server implementation in PR72](https://github.com/landjunge/KiraBridge/pull/72)
provides a private loopback HTTP MCP service with bearer authentication and health
checks, plus installation, update and rollback through `systemd --user`.
Its target platforms are Debian 13 and Ubuntu 24.04 x86_64. The online installer
needs a running user manager; logout/reboot lifetime follows the host's session policy.
It does not configure linger, administrator rights, a firewall or public HTTPS.

This is a headless server, with no macOS GUI, Terminal.app or native keyboard.
Clipboard support is optional (`wl-clipboard`/`xclip`). ChatGPT/account linking and
remote access need separate configuration.

The 0.8.0rc41 archive is natively accepted on Debian 13.6 x86_64 and
[published in its separate server release](https://github.com/landjunge/KiraBridge/releases/tag/linux-v0.8.0rc41). The downloaded
archive matches GitHub's digest and the release checksums. Ubuntu 24.04 is a
supported target; no new native Ubuntu acceptance is claimed here.
[Linux x86_64 archive](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz) ·
[Checksums](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/SHA256SUMS).
[Install/update/rollback guide](docs/INSTALL-LINUX-SERVER.md) ·
[Source, native and download evidence](docs/evidence/readme-current-20261107.json).

[Final native/release evidence](docs/evidence/debian-dirktest-release-20261107.json).
[Archive SHA-256](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256).

As a normal user with repository access, install with:

```sh
gh release download linux-v0.8.0rc41 -R landjunge/KiraBridge -p 'KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz*'
sha256sum -c KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz
cd KiraBridge-0.8.0rc41-Linux-x86_64
sh install.sh --yes --language en
```

To update, download and verify the new release in a fresh directory, then run its
`sh install.sh --yes --language en` with the same destinations. Keep the previous
runtime for rollback; [explicit paths and rollback commands](docs/INSTALL-LINUX-SERVER.md)
also cover hosts with shared parent directories.

## Keyboard sequences and fewer cloud calls

`keyboard_sequence` executes up to 32 genuine key-down/key-up pairs in order,
without the clipboard, under one idempotent task. Use separate calls when the
next key depends on feedback from the preceding one. Block text is a separate
operation and does not replace requested key events.

Known read tools can share one handoff through
`read_query(query={"operation":"tool.batch","calls":[...],"result_format":"structured"})`.
The optional structured format removes only proven equivalent JSON text copies;
all structured values, errors and metadata remain. The default is `full`.
Permissions stay current. Read an uncertain task's status instead of replaying it.

[RC28 sequences](docs/RC28-E2E-LATENCY-20261103.md) ·
[RC29 call reduction](docs/RC29-CLOUD-CALL-REDUCTION-20261103.md) ·
[RC30 measurements, installation and limits](docs/RC30-HOTPATHS-20261103.md).
The same eight large read results needed one instead of two Apps calls in the
measured RC30 comparison; median 22.72 → 13.02 seconds over three groups per version.
Cloud latency remains; this is not a new physical keyboard or Voice benchmark.

RC31 adds direct native JSON reads through `read_query` with `operation="native.read"`
and bounded Accessibility subtrees with `max_depth>0`, reducing repeated UI reads
and persisted task traffic. Task-event reads also avoid loading large outputs.
See [RC31 implementation, measurements and delivery status](docs/RC31-NATIVE-READS-20261103.md).

RC32 also batches attributes inside optional UI subtree reads. In a controlled
native test, the same twelve owned AppKit buttons took 8.14 instead of 16.86 ms
median over twenty alternating rounds. See [RC32 measurements and limits](docs/RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md).

## License

Private, non-business use is free under the
[Netzwerkpunkt Personal Use License 1.0](LICENSE). Business use requires separate
written permission. The German license text governs.

[Developer documentation](docs/DEVELOPERS.md): Python 3.11 or later, the locked uv
environment, CLI quickstart, source directories and scoped checks. Start from a
repository checkout; the published installer and development environment are separate.

Local CLI-module candidate: [Terminal/Codex/Grok adapter boundaries and test limits](docs/plans/TERMINAL-CLI-MODULES-20261104.md).
This development package is separate from the published RC36 download and still
requires real browserchat acceptance.

Local Big Plan coordinator adapter: [approved-task loop, Codex/Grok review and agent reports](docs/COORDINATOR-LOOP.md). Uses a separate opt-in profile; existing visible sessions and published packages retain their current behavior.

The [standing-mandate supervisor](docs/COORDINATOR-CONTINUATION-20261106.md) continues coordinator-assigned ThreadDesk tasks without another user approval. It reconciles existing claims and results, skips completed work and keeps task-local problems separate from independent work.

[The November 6 integration checkpoint](docs/BIGPLAN-INTEGRATION-STATUS-20261106.md) records accepted packages, combined remote/crash tests and the gates open at that time. Use the [November 7 verification](docs/evidence/readme-current-20261107.json) for the reviewed source and installed pin; dated checkpoints retain their historical results.

The integrated coordinator source also supports native Core activation, owner-scoped MCP `coordinator_status` and durable accepted/stopped notices through the existing completion inbox. It follows pinned tasks after successful review and checks without loading a skill. See [native coordinator contract and validation](docs/COORDINATOR-NATIVE-20261106.md); desktop and live deployment acceptance remain separate.

Its status projects recorded queue, execution and acceptance times from the bound Core and receipt. Missing or invalid timestamps remain unknown; reading the projection starts no work.

The optional [native worker routing](docs/COORDINATOR-NATIVE-ROUTING-20261106.md) reuses the verified CLI matrix for sealed managed tasks, preserving visible sessions and the separate structured Grok review protocol. Requested model/effort and observed metadata remain distinct; local fixture tests do not establish provider or deployment acceptance.

[CLI return-message behavior and inbox-only delivery](docs/NATIVE-COMPLETION-RETURNS-20261106.md): the integrated source keeps answers/results in the requesting client's inbox. `--inbox-only` avoids terminal dispatch; completion acknowledgements do not require another agent turn.

[Earlier Windows preview dev2](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev2):
native keyboard and local MCP acceptance passed in a dedicated Windows 11 VM.
[Results and limits](docs/WINDOWS-DEVELOPMENT-20261103.md); macOS stays separate.

[Earlier Windows desktop preview dev3](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev3): all six native
guest phases passed, including Ctrl/Alt/Shift shortcuts and guarded window control.
Published downloads and the separate Windows 11 installation were verified.
[Evidence and limits](docs/WINDOWS-DESKTOP-20261104.md); dev2 remains available for rollback.
