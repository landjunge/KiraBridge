<!-- readme-header-v1: Kopf nach ThreadDesk docs/contracts/readme-header-v1.md. Nicht von Hand umgestalten; scripts/readme_header.py apply/check verwenden. -->

**English** · [Deutsch](README.de.md)

<p align="center">
  <img src="assets/readme/normalized/KiraBridge-large.svg" alt="KiraBridge" width="256" height="256">
</p>

<p align="center">
  <a href="https://github.com/landjunge/threaddesk#readme" title="ThreadDesk"><img src="assets/readme/normalized/ThreadDesk-small.svg" alt="ThreadDesk" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass#readme" title="4AllPass"><img src="assets/readme/normalized/4AllPass-small.svg" alt="4AllPass" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/tollgate#readme" title="TollGate"><img src="assets/readme/normalized/TollGate-small.svg" alt="TollGate" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/agent-authority-lab#readme" title="Agent Authority"><img src="assets/readme/normalized/Agent-Authority-small.svg" alt="Agent Authority" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/blockdesign#readme" title="BlockDesign"><img src="assets/readme/normalized/BlockDesign-small.svg" alt="BlockDesign" width="48" height="48"></a>
</p>

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/design/wordmarks/KiraBridge-dark.svg"><img src="assets/design/wordmarks/KiraBridge-light.svg" alt="KiraBridge" width="312"></picture></p>

<!-- AUTO-DOWNLOADS:START -->
<p align="center">
  <a href="https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc49/KiraBridge-macos.tar.gz" title="KiraBridge-macos.tar.gz herunterladen / download"><img src="assets/readme/download-macos-intel.svg" alt="Download macOS Intel 0.8.0rc49" width="190" height="52"></a>
</p>
<!-- AUTO-DOWNLOADS:END -->

<p align="center"><strong>Talk to your AI. KiraBridge connects your voice to direct computer control.</strong></p>

## One tool family, one shared voice interface

**KiraBridge is the central connection in the NetzwerkPunkt tool family.** It turns authorized requests from ChatGPT, through chat or voice, into actions on your own computer and connects the other tools. The family consists of **KiraBridge** for connectivity and direct control, **ThreadDesk** for projects, work history and tasks, **4AllPass** for credentials and keys, **TollGate** for usage limits and budgets, and **Agent Authority** for read-only observation and evidence. Each tool has its own role. Operating the whole family through natural language is our shared development goal. Existing integrations, work in progress and planned capabilities are clearly distinguished.

The development console has a compact product header: the original two-color wordmark on the left, five original app icons centered (32 px art inside 44 px targets), and German/English on the right. Decorative contours are quiet; controls and keyboard focus retain their contrast. The shared module is the unchanged **1.2.2** copy. Selecting an icon passes only its catalog ID to the native host, which calls `kirabridge --principal local family switch TARGET --source-pid OWN_NATIVE_PID` directly. Only a verified JSON receipt confirms focus; opening does not confirm a peer connection. Reopen preserves the existing main view. [Source evidence and limits](docs/FIVE-TOOL-DESIGN-20261107.md#family-header-follow-up--12-november-2026): native broker integration and installed five-app acceptance remain separate; KBLive is not delivered by this UI change.

## Directly control your computer

**KiraBridge is more than a gateway to terminal AI agents.** Direct computer control is a core capability: open or focus applications, switch windows, enter text directly, write and edit notes, press individual keys and use keyboard shortcuts. Direct typing can work without relying on the clipboard. With the necessary permissions and a compatible interface, mouse, window and screen operations are also available. This allows an AI to interact with existing applications through their ordinary user interfaces, without requiring a custom AI integration for every app.

For example, ask the AI to write down a note. It can open or select the notes app, bring the appropriate window forward and enter your words. Workflows can likewise combine shortcuts, text input and window changes. The goal is not merely to send a command, but to produce a visible action and verifiable result on your computer. Success depends on the application, the operating system's accessibility support, granted permissions and connection stability.

## Voice control for everyone, with accessibility built in

**KiraBridge's primary goal is to make computers, applications and AI tools operable through natural language.** Instead of memorizing complex sequences, describe the desired outcome: open an app, write a note, switch windows or task an AI agent. Voice-driven operation is designed for everyone, whether for everyday tasks, productive work, hands-free control or complex workflows.

**Accessibility is considered from the outset, but it is not the sole or primary product purpose.** People with disabilities, reduced mobility or difficulty using a mouse and keyboard can particularly benefit from spoken instructions and understandable feedback. Greater independence is a valuable additional benefit of general-purpose voice control. Clear responses, verifiable results and human oversight matter to all users.

Development is ongoing: KiraBridge cannot yet reliably or fully control every application. Some capabilities have been implemented and tested; other workflows remain slow or depend on permissions and the environment. We keep improving usability, reliability, speed and feedback. Important operations may still require confirmation.

## AI agents and project workflows

Alongside direct control, KiraBridge can pass work to **Codex and Grok** through configured visible terminal sessions and track their replies. As of November 10, the local inventory also reports executable adapters for **Claude Code, OpenCode, Gemini CLI and Copilot**. OpenCode can additionally use its local HTTP API with Basic authentication from environment variables; that adapter creates one new session per task and reports status and results back. Finding an adapter does not prove sign-in, a ready session or a successful end-to-end task.

The source also includes [Qwen Code 0.27.2 via ACP and task-scoped MCP](docs/providers/QWEN.md): explicit existing authentication, native model/effort selection, configurable operator budgets and policy-filtered KiraBridge tools for read or explicitly granted coding tasks. Same-session recovery requires a proven owned binding; native turn completion remains separate from project acceptance. Production activation and full task acceptance remain gated.

The development source now includes a shared ACP client and an `opencode_acp` adapter for isolated text-only tasks, with session validation, bounded output and explicit timeout or disconnect results. This adapter creates its own process; observing that same session in the OpenCode app and the full macOS workflow still require acceptance. These changes have not been installed in the published runtime.

A separate development adapter `opencode_http_v2` targets the installed shared OpenCode 2.2.7 app's `/api` surface (session create/get, prompt with a stable message id, paged message list). It correlates its own admitted prompt causally because V2 assistant messages carry no `parentID`/`sessionID`, and it fails closed on foreign or ambiguous inputs. The legacy V1 HTTP path stays unchanged and there is no protocol or POST fallback after an unclear start. This adapter is not installed and its live acceptance remains a separate gate. An observed idle outcome of `failed` or `interrupted` remains unconfirmed even if an assistant message has text and `finish=stop`.

Team assignments also keep the proven provider session for each worker. A later assignment to the same worker resumes that session only while it is idle and for the unchanged agent, adapter and working directory; a still-running or unconfirmed (unknown) session is never reused. `team_session_get` exposes the binding and `team_session_clear` tombstones it, so a turn still in flight cannot resurrect a cleared session. Resume currently covers Codex, Grok ACP, sealed idle Qwen ACP sessions and the separate native OpenCode HTTP path; the OpenCode CLI and `opencode_acp` adapters are rejected for resume because their isolated profile has no persisted session store. Resumption is restricted to sealed team work, survives a bridge restart and never replays a claimed core task. The live acceptance with Codex, Grok and OpenCode/DeepSeek across a bridge restart is recorded in `docs/evidence/team-coordination-live-20261112.json`.

ThreadDesk adds projects and work history to this workflow, while the other family tools are intended to work together through the shared voice interface. Each tool remains independent; integration plans are not presented as shipped functionality.

In the development source, the opt-in ThreadDesk tool proxy accepts bounded JSON Schema 2020-12 references within the supplied schema, including embedded domain resources. References cannot load schemas from the network or disk; cyclic, ambiguous and unsupported schemas remain excluded. Existing tool permissions and operation receipts still apply. See the [proxy contract](docs/DYNAMIC-THREADDESK-PROXY.md).

**Server edition:** KiraBridge also runs on Debian; server source and local macOS installation are tracked separately. A server source revision is not itself a published installer. / **Server-Version:** KiraBridge läuft auch auf Debian; Quellstand und veröffentlichte Downloads sind getrennt.

**Verified runtime status (November 11, 2026):** The Intel Mac is running **KiraBridge 0.8.0rc48** (`48c635137b4b`), verified through the live KiraBridge daemon and the published macOS pre-release `v0.8.0rc49`. The separately published Debian/Linux archive is still **0.8.0rc41** (`350d368`); this is a published server package, not the installed Mac build. **Installed, repository-source, and downloadable versions must not be conflated.**

**Published macOS Intel download:** [0.8.0rc49](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc49) · November 4, 2026 · Preview.

### [Download KiraBridge — app and installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc49/KiraBridge-macos.tar.gz)

[Checksums](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc49/SHA256SUMS)
· [All releases](https://github.com/landjunge/KiraBridge/releases)

The current downloads are the published macOS Intel archive and the separate Debian server archive.
This is a preview; there is no stable release yet. RC49 is available for Intel Macs.

The earlier RC33 release includes a [Windows 11 development preview](docs/RC33-DELIVERY-20261104.md)
with native keyboard, shortcuts and guarded window control. It is a separate
development kit; general Windows file, process and terminal tools remain outside
its scope. See [RC33 package checks, installation status and limits](docs/RC33-DELIVERY-20261104.md)
and [Windows setup evidence](docs/WINDOWS-SETUP-20261104.md).

The [Windows setup wizard 0.8.0rc37.dev1](docs/WINDOWS-SETUP-20261104.md)
has historical evidence for a separate Windows installation.
All seven native phases for that limited development preview passed. Extract the package and open
**Einrichtung-starten.cmd** for four guided steps. Account sign-in and a real
ChatGPT connection test with your account remain yours to complete.
[Evidence and limits](docs/WINDOWS-SETUP-20261104.md) ·
[Setup guide, German](docs/WINDOWS-SETUP.md).

The linked Intel download is the verified published RC49, **not** the newer locally installed RC45. The verified installed runtime is listed in the opening status. The historical November 7 evidence below predates RC45.
[Release, artifact and installed-source evidence](docs/evidence/readme-current-20261107.json).
The [earlier PR61 installation report](docs/RC40-PR61-SHIM-INSTALL-20261106.md)
describes the previous RC40 source `a5d381a`.

Windows feature parity and a standalone installer remain development work. The published Windows preview does not include general
file, process or terminal tools, or Windows service installation. No new package
for those ongoing projects or published RC40 download is offered here.


## What KiraBridge helps you do

- **Work on local projects:** let your connected AI read project files and logs,
  edit files or run commands within the access you have granted.
- **Work with terminal agents:** send tasks to Grok Build and Codex in their
  configured terminal sessions on your computer.
- **Follow the work:** see requests, messages and results in the local control window.
- **Choose the permissions:** decide which folders and actions are allowed and
  when a task needs your approval.
- **No late surprises:** at most three tasks wait at a time; a fourth cancels the
  oldest waiting one. Work that waited longer than an hour is stopped and reported,
  never run later. Large outputs are kept short in the database, the audit trail stays complete.

ThreadDesk and other integrations are optional. KiraBridge's core works independently.
If ThreadDesk is configured, the package brings the pinned ThreadDesk library and the
installer points `[threaddesk]` `source_root` and `command` at it and at the release's
Python; rollback restores both values. Other settings stay unchanged.

## Get started

1. **Install or update.** Download and fully extract `KiraBridge-macos.tar.gz`.
   Run the included `install.sh` in a separate Terminal window and follow its
   confirmation. Preserve running agent sessions.
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
This development package is separate from the published RC49 download and still
requires real browserchat acceptance.

Local Big Plan coordinator adapter: [approved-task loop, Codex/Grok review and agent reports](docs/COORDINATOR-LOOP.md). Uses a separate opt-in profile; existing visible sessions and published packages retain their current behavior.

The [standing-mandate supervisor](docs/COORDINATOR-CONTINUATION-20261106.md) continues coordinator-assigned ThreadDesk tasks without another user approval. It reconciles existing claims and results, skips completed work and keeps task-local problems separate from independent work.

[The November 6 integration checkpoint](docs/BIGPLAN-INTEGRATION-STATUS-20261106.md) records accepted packages, combined remote/crash tests and the gates open at that time. Use the [November 7 verification](docs/evidence/readme-current-20261107.json) for the reviewed source and installed pin; dated checkpoints retain their historical results.

The integrated coordinator source also supports native Core activation, owner-scoped MCP `coordinator_status` and durable accepted/stopped notices through the existing completion inbox. It follows pinned tasks after successful review and checks without loading a skill. See [native coordinator contract and validation](docs/COORDINATOR-NATIVE-20261106.md); desktop and live deployment acceptance remain separate.

Its status projects recorded queue, execution and acceptance times from the bound Core and receipt. Missing or invalid timestamps remain unknown; reading the projection starts no work.

The optional [native worker routing](docs/COORDINATOR-NATIVE-ROUTING-20261106.md) reuses the verified CLI matrix for sealed managed tasks, preserving visible sessions and the separate structured Grok review protocol. Requested model/effort and observed metadata remain distinct; local fixture tests do not establish provider or deployment acceptance.

[CLI return-message behavior and inbox-only delivery](docs/NATIVE-COMPLETION-RETURNS-20261106.md): the integrated source keeps answers/results in the requesting client's inbox. `--inbox-only` avoids terminal dispatch; completion acknowledgements do not require another agent turn.

[Earlier Windows preview dev2](docs/WINDOWS-DEVELOPMENT-20261103.md):
native keyboard and local MCP acceptance passed in a dedicated Windows 11 VM.
[Results and limits](docs/WINDOWS-DEVELOPMENT-20261103.md); macOS stays separate.

[Earlier Windows desktop preview dev3](docs/WINDOWS-DESKTOP-20261104.md): all six native
guest phases passed, including Ctrl/Alt/Shift shortcuts and guarded window control.
The documented Windows 11 installation was verified.
[Evidence and limits](docs/WINDOWS-DESKTOP-20261104.md); the earlier dev2 record remains for rollback notes.

### Design source · November 7, 2026

The shared header with five original icons is implemented and locally reviewed.
The [design record](docs/FIVE-TOOL-DESIGN-20261107.md) describes status/version
boundaries and passed browser checks; the installed native app remains unverified.
This source delivery does not establish a new download or installed runtime.

### Native family window switching (source)

The fixed five-icon hosts can call `kirabridge --principal local family switch
TARGET --source-pid OWN_NATIVE_PID`. The macOS broker reuses the installed native
system helper and existing policy, without initializing the task database. It
preserves allowed `roots` and state-directory exclusions before Launch/Reopen;
registration and automatic capability grants cannot broaden path access. It
checks registered installation/PID/start/UID and caller ancestry, transfers actual
outer window bounds, confirms target focus, then hides only other registered
family windows. Processes and UI state remain; 4AllPass lock policy is unchanged.
Unknown effects are durably blocked from blind retry. Missing or ambiguous targets
are errors. [Registration, exact JSON ABI and acceptance](docs/FAMILY-WINDOW-BROKER.md)
remain separate from installation; current downloads are not changed by source.
