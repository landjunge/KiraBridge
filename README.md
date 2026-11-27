<!-- readme-header-v1: Kopf nach ThreadDesk docs/contracts/readme-header-v1.md. Nicht von Hand umgestalten; scripts/readme_header.py apply/check verwenden. -->

<p align="center"><strong>English</strong> &nbsp;|&nbsp; <a href="README.de.md">Deutsch</a></p>

<p align="center">
  <img src="assets/readme/normalized/KiraBridge-large.svg" alt="KiraBridge" width="256" height="256">
</p>

<p align="center">
  <a href="https://github.com/landjunge/ThreadDesk#readme" title="ThreadDesk"><img src="assets/readme/normalized/ThreadDesk-small.svg" alt="ThreadDesk" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass#readme" title="4AllPass"><img src="assets/readme/normalized/4AllPass-small.svg" alt="4AllPass" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/TollGate#readme" title="TollGate"><img src="assets/readme/normalized/TollGate-small.svg" alt="TollGate" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/AgentAuthority#readme" title="Agent Authority"><img src="assets/readme/normalized/Agent-Authority-small.svg" alt="Agent Authority" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/BlockDesign#readme" title="BlockDesign"><img src="assets/readme/normalized/BlockDesign-small.svg" alt="BlockDesign" width="48" height="48"></a>
</p>

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/design/wordmarks/KiraBridge-dark.svg"><img src="assets/design/wordmarks/KiraBridge-light.svg" alt="KiraBridge" width="312"></picture></p>

<!-- AUTO-DOWNLOADS:START -->
<p align="center">
  <img src="assets/readme/download-macos-apple-silicon.svg" alt="macOS Apple Silicon: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <a href="https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc59/KiraBridge-macOS-Intel.dmg" title="KiraBridge-macOS-Intel.dmg herunterladen / download"><img src="assets/readme/download-macos-intel.svg" alt="Download macOS Intel 0.8.0rc59" width="190" height="52"></a>
  &nbsp;
  <img src="assets/readme/download-windows.svg" alt="Windows: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <img src="assets/readme/download-linux-desktop.svg" alt="Linux Desktop: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <a href="https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz" title="KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz herunterladen / download"><img src="assets/readme/download-debian-server.svg" alt="Download Debian Server 0.8.0rc41" width="190" height="52"></a>
</p>
<!-- AUTO-DOWNLOADS:END -->

<sub>macOS DMG builds: not notarized by Apple. On first launch, macOS may require approval in System Settings → Privacy & Security. The existing macOS archive is not a DMG.</sub>

<p align="center"><strong>Talk to your AI. KiraBridge connects your voice to direct computer control.</strong></p>

## One tool family, one shared voice interface

**KiraBridge is the central connection in the NetzwerkPunkt tool family.** It turns authorized requests from ChatGPT, through chat or voice, into actions on your own computer and connects the other tools. The family consists of **KiraBridge** for connectivity and direct control, **ThreadDesk** for projects, work history and tasks, **4AllPass** for credentials and keys, **TollGate** for usage limits and budgets, and **Agent Authority** for read-only observation and evidence. Each tool has its own role. Operating the whole family through natural language is our shared development goal. Existing integrations, work in progress and planned capabilities are clearly distinguished.

The development console has a compact product header: the original two-color wordmark on the left, five original app icons centered (32 px art inside 44 px targets), and German/English on the right. Decorative contours are quiet; controls and keyboard focus retain their contrast. The shared module is the unchanged **1.2.2** copy. Selecting an icon passes only its catalog ID to the native host, which calls `kirabridge --principal local family switch TARGET --source-pid OWN_NATIVE_PID` directly. Only a verified JSON receipt confirms focus; opening does not confirm a peer connection. Reopen preserves the existing main view. [Source evidence and limits](docs/FIVE-TOOL-DESIGN-20261107.md#family-header-follow-up--12-november-2026): native broker integration and installed five-app acceptance remain separate; KBLive is not delivered by this UI change.

The development console presents voice assistants and agent CLIs as compact cards in a three-pane, resizable workspace. Status, detected CLI versions, and the coordinator role come from the local Bridge inventory; light/dark appearance and sidebar preferences are stored locally. This describes source code and does not imply that an installed release contains the new view.

The desktop app wraps the console in the Agent Authority shell: header with the five product icons (installed products in colour, others grey, the active product with a quiet glow), a bridge status dot with a confirmed restart, a title bar with sidebar, permissions and settings buttons, and `--snapshot <file.png>` to render the window chrome to an image without screen-recording permission.


Terminal tabs are identified by the TTY of the single tab and the process tree on it, never by the window title (the profile may show the active process and arguments, so titles change). `kirabridge terminals` lists agents that still run on a closed tab (re-parented to launchd), background agents without a TTY (never touched) and bindings whose tab or processes are gone; `--apply` sends SIGTERM to the orphaned agents and removes the stale bindings after writing a backup of `config.toml`. See `docs/TERMINAL-TAB-IDENTITY-20261126.md`.

## Directly control your computer

**KiraBridge is more than a gateway to terminal AI agents.** Direct computer control is a core capability: open or focus applications, switch windows, enter text directly, write and edit notes, press individual keys and use keyboard shortcuts. Direct typing can work without relying on the clipboard. With the necessary permissions and a compatible interface, mouse, window and screen operations are also available. This allows an AI to interact with existing applications through their ordinary user interfaces, without requiring a custom AI integration for every app.

For example, ask the AI to write down a note. It can open or select the notes app, bring the appropriate window forward and enter your words. Workflows can likewise combine shortcuts, text input and window changes. The goal is not merely to send a command, but to produce a visible action and verifiable result on your computer. Success depends on the application, the operating system's accessibility support, granted permissions and connection stability.

In the development source, MCP clients can request only the schemas they need through `operation_catalog`. Setting `compact=true` returns the selected catalog, the required permission context and a lightweight discovery revision; the full catalog response remains the default. This addition is in source and is not confirmed in a new installed version.

## Voice control for everyone, with accessibility built in

**KiraBridge's primary goal is to make computers, applications and AI tools operable through natural language.** Instead of memorizing complex sequences, describe the desired outcome: open an app, write a note, switch windows or task an AI agent. Voice-driven operation is designed for everyone, whether for everyday tasks, productive work, hands-free control or complex workflows.

**Accessibility is considered from the outset, but it is not the sole or primary product purpose.** People with disabilities, reduced mobility or difficulty using a mouse and keyboard can particularly benefit from spoken instructions and understandable feedback. Greater independence is a valuable additional benefit of general-purpose voice control. Clear responses, verifiable results and human oversight matter to all users.

Development is ongoing: KiraBridge cannot yet reliably or fully control every application. Some capabilities have been implemented and tested; other workflows remain slow or depend on permissions and the environment. We keep improving usability, reliability, speed and feedback. Important operations may still require confirmation.

## AI agents and project workflows

Codex inventory and Doctor now separate executable-file presence from [passive package-layout observations](docs/providers/CODEX-PACKAGE-DIAGNOSTICS.md). Covered official 0.169 metadata can expose missing companions/resources; opaque launchers and other versions remain unknown. No CLI or login is started, no execution is blocked, and observed files do not prove matching versions, package integrity or working tools.

Alongside direct control, KiraBridge can pass work to **Codex and Grok** through configured visible terminal sessions and track their replies. As of November 10, the local inventory also reports executable adapters for **Claude Code, OpenCode, Gemini CLI and Copilot**. OpenCode can additionally use its local HTTP API with Basic authentication from environment variables; that adapter creates one new session per task and reports status and results back. Finding an adapter does not prove sign-in, a ready session or a successful end-to-end task.

The development source also inventories known agent CLIs and configured executable paths, probes their versions, and records observed versions in the audit only. A CLI version never blocks, gates or marks a CLI unsupported, and sends no team message; adapters check concrete capabilities instead. See [CLI version inventory](docs/CLI-VERSION-INVENTORY.md). The background re-probe is cached, sequential and runs every `cli_version_probe_seconds` (default 900 s) or when a binary changes; a changed installation set is recorded only after two equal observations.

The development source supports interim questions to an explicitly selected, working Codex session without stopping its work or submitting another agent job. Proven delivery-only steering does not consume the conversation/hourly model-run budgets; claimed managed attempts still count, including failed or unknown outcomes. The current native route uses the existing macOS terminal; uncertain delivery is retained without automatic repetition, and users can disable interim messages. Live macOS acceptance and native Windows/Linux/server transport acceptance are recorded separately and remain open.

The development source also offers an optional [native Codex root binding](docs/NATIVE-CODEX-BINDING.md) for new direct messages on macOS with Codex 0.169. It verifies the assigned logical root on the existing host for every attempt, refreshing host process and socket observations automatically instead of retaining an old terminal handle. Parallel sessions keep their own identities; acceptance, recipient acknowledgement and reply remain separate. This route is not activated or live accepted by the source tests.

The 0.8.0rc81 source line (versions between rc59 and rc80 were skipped on purpose) extends this route: the native Codex host is pinned to 0.172, verified Codex bindings survive tab moves and Core restarts, and the coordinator role is persisted so direct messages and handovers follow it. Verified TeamWork milestones can reach the ChatGPT team inbox while a turn is still running, and team reply and acknowledgement status is readable. Managed macOS shells get a private zsh readiness signal (ZLE), and Linux release scratch no longer fills the RAM-backed temporary directory. These are source-level results with local tests; install and live acceptance are recorded separately.

The source also includes [Qwen Code via ACP and task-scoped MCP](docs/providers/QWEN.md): explicit existing authentication, native session model/effort readback, configurable operator budgets and policy-filtered KiraBridge tools for read or explicitly granted coding tasks. Codex remains available. Same-session recovery requires a proven owned binding; native turn completion remains separate from project acceptance. Production activation and full task acceptance remain gated.

The development source now includes a shared ACP client and an `opencode_acp` adapter for isolated text-only tasks, with session validation, bounded output and explicit timeout or disconnect results. This adapter creates its own process; observing that same session in the OpenCode app and the full macOS workflow still require acceptance. These changes have not been installed in the published runtime.

A separate development adapter `opencode_http_v2` targets the installed shared OpenCode 2.2.7 app's `/api` surface (session create/get, prompt with a stable message id, paged message list). It correlates its own admitted prompt causally because V2 assistant messages carry no `parentID`/`sessionID`, and it fails closed on foreign or ambiguous inputs. The legacy V1 HTTP path stays unchanged and there is no protocol or POST fallback after an unclear start. This adapter is not installed and its live acceptance remains a separate gate. An observed idle outcome of `failed` or `interrupted` remains unconfirmed even if an assistant message has text and `finish=stop`.

Team assignments also keep the proven provider session for each worker. A later assignment to the same worker resumes that session only while it is idle and for the unchanged agent, adapter and working directory; a still-running or unconfirmed (unknown) session is never reused. `team_session_get` exposes the binding and `team_session_clear` tombstones it, so a turn still in flight cannot resurrect a cleared session. Resume currently covers Codex, Grok ACP, sealed idle Qwen ACP sessions and the separate native OpenCode HTTP path; the OpenCode CLI and `opencode_acp` adapters are rejected for resume because their isolated profile has no persisted session store. Resumption is restricted to sealed team work, survives a bridge restart and never replays a claimed core task. The live acceptance with Codex, Grok and OpenCode/DeepSeek across a bridge restart is recorded in `docs/evidence/team-coordination-live-20261112.json`.

### Source: team scope, resume and error fields

- New in the development source: owner-only `kirabridge team onboard <team_id> <identity> [--coordinator]`. The daemon tool `team_onboard_register` accepts only the owner identity `local`, appends `[principals.<id>]` plus `[team.workers.<id>]` and a generated token only after the candidate config validates against the strict model, keeps timestamped backups, restores both files on any failure, is idempotent on re-run and never returns token values. The running daemon keeps a start-up config snapshot, so the CLI orchestrates the rest: idle-guarded service reload (active team work or `--no-restart` stops it), one role call with revision CAS and a single renewed attempt, then a mandatory readback of owner, coordinator, revision, membership and the pending inbox page. Not an installed release.
- `execution_scope = "existing_native_codex_root"` runs one team turn on the single loaded, parentless Codex root whose resolved cwd equals the resolved worker cwd, through app-server `turn/start`. Among at most 16 loaded ids, any other count raises `native_codex_root_not_unique`. A missing or longer id list, and a running turn, raise `native_codex_target_not_ready`. The path records `terminal_input_attempted = false` and does not select a pane, terminal PID or rollout path. Host identity is checked; a patch release of the same minor line stays valid. `protocol_version` accepts only `0.169.<patch>`. The route needs `[visible_handoffs.native_codex]` with `codex_home`, `host_executable` and `protocol_version`. The worker's agent and kind must be `codex`. See [Native Codex root binding](docs/NATIVE-CODEX-BINDING.md).
- `team.coordinator_resume` defaults to off. When it is on, finished delegated work (`finish`, `fail` or manual `work_complete`) records one completion notice, source `team`, target `team:<team_id>`, and `TeamManager.resume_coordinators` creates one idempotent coordination task for an assigner that has `agent` set. The link is stored in `team_coordinator_resumes`. Work assigned to its own assignee records no notice.
- Source only: a replayed `team send` and the bridge start restore a missing delivery ticket (idempotent through its `team:<id>` key, only unacknowledged waking messages younger than `queue_stale_seconds`; failures are logged as `team.message_delivery_failed` / audit entries, never swallowed), and queued tickets that never reached input are admitted again at start, so nothing is lost silently in the install/drain window.
- Source only: every message to the current coordinator carries a short role prefix (fixed rules: coordinate and delegate, never build or install, Sonnet only at low thinking effort, never Opus, team channel only, no permission bypass, the `impeccable` and `design-taste-frontend` skills are only an optional hint for UI work; plus the configured CLI names). It is read per message from the team record, so a role change applies at once; it is read at delivery time, not at send time (a retry after a role change can send a different prompt; body, key and hash stay equal); it grants no permissions and is skipped for workers and when it would exceed a prompt limit.
- Source only: a team delivery ticket always gets its job when the receiver is a configured visible terminal. While presence is unproven (`unknown`/`stale`) it waits unsent as `waiting_for_visible_target`, a connection retry no longer overwrites that marker (so the retry deadline is evaluated), and delivery happens once the exact binding is ready and not busy.
- Source only: the receive hook of `messages_overview` (`team.auto_ack_on_observe`, default `chatgpt`) also applies to the current coordinator, read per call from the team record: it acknowledges the returned messages from the listed principals to that coordinator, ends for the previous holder after a role change and never applies to workers. The coordinator's own report to ChatGPT is not automated in the bridge yet.
- Source only: a terminal catalog or `selected()` timeout is not absence. An observed `available` receiver presence for the same exact binding is kept (the failed observation is only noted in its evidence, freshness keeps ageing; presence carries the observation start time and an older, slower result never overwrites a newer one) instead of flipping to `unknown`/`stale`; proven absence still downgrades.
- Source only: one inbox per participant: `team inbox` / MCP `team_messages` without a team id reads your own mailbox over all teams plus the legacy direct store (read-only). `messages_overview` is a deprecated alias of the same view; `message_receive`/`message_get` stay only for delivery receipts and are deprecated for reading. Reading is delivery: for `chatgpt` (`team.auto_ack_on_observe`) and the current coordinator, a finished `team_messages` read (with or without a team id) acknowledges exactly the messages it returned to the caller; every item carries `read`/`new`, the result `new_count`, `unread_count` and `total`.
- Source only: the receiver reads its internal delivery ticket back through a receiver-internal claim instead of the reader view (which hides `team:` tickets), so a ticket delivery no longer fails with `receiver_delivery`. A ticket counts as delivered only when its input starts, not when it is read.
- Source only: `team send` is the one send path. A new team message to a worker or the current coordinator with a bound terminal (not Codex) also creates an internal delivery ticket for the existing visible/native handoff machine (idempotency key `team:<id>`, hidden from every read) instead of the coordinator-inbox work item (native Codex ping unchanged); the outcome is written back as `team.message_delivered` / `team.message_delivery_failed` and is never an acknowledgement. The visible binding of the `local` coordinator matches the Claude TUI process (named `claude`), so its presence can become available and the wake is dispatched. `message_send` is a deprecated alias of it for such recipients (the one shared team, else `kirabridge-team`); Codex, replies, tasks and managed receivers keep the legacy direct path. Internal delivery tickets are never readable: `message_receive`, `message_get` and the inbox views hide them; `message_get`/`message_ack` on a team message id read/acknowledge the team message (deprecated aliases, there is only the team channel). A terminal-bound coordinator has no session record; the coordinator-route check at delivery uses the same rule as at addressing, so a role change in between still fails with `coordinator_route_changed`. CLI and MCP texts now say so: there is only the team channel.
- Source only: `adapter_for` resolves the same alias table as `process_is` (`local` is the Claude TUI), so visible readiness and handoff to the `local` coordinator no longer stop with `unsupported_cli_program`.
- Source only: acknowledging a team message (`team ack`, or the inbox read hook) also closes its internal delivery ticket, so a waiting wake cannot type an already handled message into the terminal again.
- `agents.<name>.model` is optional. `grok_reasoning_effort` is accepted only for `kind = "grok_acp"` and must match `^[a-z]{1,16}$`. The Grok ACP adapter passes a set model as `--model` and a set effort as `--reasoning-effort`.
- Source only: the `team send` / `team_message_send` result of a question, work or note carries `wake_state` (`waking`, `inbox_only` or `failed`) and `wake_reason` (`native_ping`, `coordinator_notification`, `delivery_ticket`, an error code, or the inbox-only reason such as `no_visible_binding`), so the sender sees at once whether anything was woken. Answers and results report none; a replay returns the stored message without it.
- When an execution returns a failure, the task stores `error` as `{code, kind, retry_safe}`, plus `exit_code` when the result has an integer exit code. Codes from that normalization are `command_exit_nonzero`, `command_timeout`, `command_killed`, `agent_exit_nonzero` and `operation_failed`. A nested peer `value.error.code` is kept when it matches `^[a-z][a-z0-9_]{0,79}$`; otherwise the code is `tool_rejected`. `retry_safe` is true only for that peer form when `evidence.request_sent` is false. Dispatcher restart and shutdown store `error.code` `dispatcher_restart` or `dispatcher_shutdown` without that normalized object. The completion payload copies `error.kind` to `error_kind`.
- A short terminal catalog raises `session_catalog_incomplete` with `provider_error.reason = "catalog_truncated"`. A complete catalog that no longer matches the selected pane raises `session_selection_changed` with `provider_error.reason` `expected_pid_changed`, `window_changed` or `pane_missing`.
- Source only: MCP `completion_ack_all(before_seq, target)` marks all of the caller's own unacknowledged completion notices up to `before_seq` as acknowledged in one step (nothing is deleted, no limit, audit entry `completion.bulk_acknowledged` with the count); `completion_receive` stays newest-first.
- Gemini and Copilot CLI failures can set `provider_error.diagnostic` from non-empty stderr only, sanitized and at most 200 characters. `opencode_http` and `opencode_http_v2` record `provider_error.http_status` on status failures. An unexpected ACP response id raises `agent_identity` with shape fields only: `response_id`, `message_keys`, `pending_requests`, `adapter`, `reason` and `already_answered`.

ThreadDesk adds projects and work history to this workflow, while the other family tools are intended to work together through the shared voice interface. Each tool remains independent; integration plans are not presented as shipped functionality.

In the development source, the opt-in ThreadDesk tool proxy accepts bounded JSON Schema 2020-12 references within the supplied schema, including embedded domain resources. References cannot load schemas from the network or disk; cyclic, ambiguous and unsupported schemas remain excluded. Existing tool permissions and operation receipts still apply. See the [proxy contract](docs/DYNAMIC-THREADDESK-PROXY.md).

Development source also separates routine MCP liveness from storage diagnostics, protects running ThreadDesk calls during catalogue recovery, and offers compact verified write responses. Unknown writes still require reconciliation against the original operation. Known lifecycle rejections such as `object_in_trash` retain their structured codes without exposing private peer messages. Write-field limits are reported only for validated size failures in the corresponding management request; reads and unknown errors no longer inherit unrelated write limits. These changes apply to the shared Mac/Linux code; they do not establish a new installed version. See [behaviour and verification limits](docs/THREADDESK-OPERATIONS-RELIABILITY.md).

Readiness now distinguishes permission, platform support and unprobed transport. Pending approval and known blockers report false; an untested session or ThreadDesk connection reports unknown. This changes status reporting without granting access or starting commands.

In development source, valid macOS system users with negative UIDs, such as `nobody`, no longer block the entire Terminal catalog. Their processes remain foreign; malformed process data and busy input targets are still rejected.

The release smoke fixture limits its temporary local identity to health and `file.read` checks with automatic approval. Normal installation defaults continue to require approval.

**Server edition:** KiraBridge also runs on Debian; server source and local macOS installation are tracked separately. A server source revision is not itself a published installer. / **Server-Version:** KiraBridge läuft auch auf Debian; Quellstand und veröffentlichte Downloads sind getrennt.

## Downloads and installation profiles

The buttons above link directly to published installation files and show their
versions. The macOS desktop and Debian Remote server have independent release
tracks, so their version numbers can differ.

| Download | Intended use | Installation guide |
| --- | --- | --- |
| **macOS Intel** | Desktop app and local KiraBridge service. Current verified Intel download is linked above. | [Install, verify and get help](docs/INSTALL-EN.md) |
| **macOS Apple Silicon (M-series)** | Native Apple Silicon desktop installation. **No verified Apple Silicon installer published yet; download button will appear once available.** | [All releases](https://github.com/landjunge/KiraBridge/releases) |
| **Windows Desktop** | Local Windows computer control. **No current downloadable installer in the selected desktop release.** | [Windows setup guide](docs/WINDOWS-SETUP.md) |
| **Linux Desktop (Ubuntu / Debian Desktop)** | Local graphical computer control. **No separately verified desktop installer currently linked.** This is not the server package. | [All releases](https://github.com/landjunge/KiraBridge/releases) |
| **Debian Server (Debian Remote)** | Headless Debian/Linux x86_64 server with remote-agent and MCP capabilities; **not a Linux desktop app**. The separate server download is linked above. | [Debian server installation](docs/INSTALL-LINUX-SERVER.md) |

[All releases, checksums and release notes](https://github.com/landjunge/KiraBridge/releases)
are public; downloading does not require a GitHub account. Releases may be
previews. Check each release's notes for its status, requirements and limits.
AI-provider sign-in and any provider charges are separate.

The download buttons refresh automatically when a release is published, edited
or deleted, when the updater changes, and every six hours for later asset uploads.
Only complete, verified downloads are offered. Desktop buttons use the newest
published desktop release; missing platforms are not filled from older desktop
releases. Debian Remote is selected independently from the newest published
`linux-*` server release. Apple Silicon and Windows desktop buttons appear when
that desktop release actually includes their packages.

The source repository can contain newer changes than the published packages.
Check the app or `kirabridge status` for the version actually running on your
computer. A source commit, a successful build and an installed version are
separate pieces of evidence.

In the macOS development build, the About window shows the app’s own build
commit as **App-Build**, alongside the package version.

**Earlier Windows development previews:** the [RC33 package report](docs/RC33-DELIVERY-20261104.md)
and [Windows setup report](docs/WINDOWS-SETUP-20261104.md) describe their limited
keyboard, shortcut and guarded-window support. They do not establish current
Windows feature parity or a current general-purpose Windows installer.
[Windows setup guide](docs/WINDOWS-SETUP.md).

[Historical release and installation evidence](docs/evidence/readme-current-20261107.json)
remains available as dated evidence, not as the current installed version.

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
- **Newest board text (development source):** `order="newest"` reads the latest whiteboard page, and `whiteboard_search` finds text in one board. Not a new installed release.
- **Technical board entries:** `progress`, `claimed`, `task` and `problem` stay in KiraBridge as the latest in-process state only, with no audit row and no database write. Turn off with `[threaddesk]` `route_technical_entries = false`.

ThreadDesk and other integrations are optional. KiraBridge's core works independently.
If ThreadDesk is configured, the package brings the pinned ThreadDesk library and the
installer points `[threaddesk]` `source_root` and `command` at it and at the release's
Python; rollback restores both values. Other settings stay unchanged.

## Get started

1. **Install or update.** If your download is a DMG, open it, drag `KiraBridge.app`
   to `Applications` and launch it. Otherwise download and fully extract
   `KiraBridge-macos.tar.gz`, then run `sh ./install.sh --desktop
   --require-visible-terminal` from the extracted `KiraBridge` directory in a
   separate Terminal window. Follow its confirmation. Preserve running agent
   sessions.
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
See the notes accompanying the selected download and [installation, verification
and help](docs/INSTALL-EN.md). The [RC36 report](docs/TERMINAL-MINIMIZED-RC36-20261104.md)
remains a historical record.


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

Development source identifies terminal routes by host: a confirmed visible shell on macOS, native owned PTYs on Linux, and `windows.console.handoff` on Windows. On Linux, `terminal_control` / `terminal.visible` and ChatGPT's default `terminal.execute` execute exact argv in a fresh temporary PTY, returning its PID/TTY, output, observed exit status and cleanup evidence. Existing user sessions are preserved; `create_if_needed` controls macOS windows only. Explicit pane targets and privileged direct execution are unsupported on Linux. Separate interactive owned sessions use `session.open`; discovery lists them even without tmux, and input/close retain exact handle/PID checks. Existing permissions, executable and working-directory limits still apply. This source change does not update published downloads or establish live Voice acceptance of the new route.

Linux discovery identifies its provider as `linux.existing_native`. It distinguishes bound file, process and owned-PTY adapters from unprobed transport availability: a binding reports `state=unknown`, `runtime_availability=not_probed` and does not assert `available=true`. Desktop transports remain unsupported. These passive metadata do not change operation descriptors, permission checks or terminal dispatch; macOS and Windows retain their existing paths. Installed-version and native platform acceptance require separate evidence.

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
Every push to `main` is built on GitHub; fetch it with `python3 scripts/fetch_release.py` instead of building locally.

Local CLI-module candidate: [Terminal/Codex/Grok adapter boundaries and test limits](docs/plans/TERMINAL-CLI-MODULES-20261104.md).
This development package is separate from the published RC49 download and still
requires real browserchat acceptance.

Local Big Plan coordinator adapter: [approved-task loop, Codex/Grok review and agent reports](docs/COORDINATOR-LOOP.md). Uses a separate opt-in profile; existing visible sessions and published packages retain their current behavior.

Source update: the coordinator reports substantive status changes instead of resending unchanged states every minute. Local observations stay current; report attempts retain their identity across restarts, including uncertain outcomes. Running services require a separately verified update.

The source command `bigplan-loop --profile <fixture-profile> preview --fixture <fixture.json>` checks private offline fixtures only and shows a possible selection or hold with the evaluated route. Preview is neither approval nor a claim and starts no task; it reads no live board or Core.

Lost team-submit responses retain the original Core task. New marked submission ambiguities can reconcile one proven successful original attempt without submitting another turn. Historical UNKNOWNs remain held. For a reviewed zero-action result, the stopped supervisor's owner can use `bigplan-loop --profile <profile> reconcile --request <TeamWorkReprocess.json> --expected-profile-sha256 <sha256>`: it holds the existing singleton lock, checks the profile identity/reporting scope and original work ownership, and applies the existing owner operation. The request must bind the original work/Core IDs, request SHA256, receipt, attempt and native-result SHA256. It starts no Bridge, dispatcher, provider or successor; the normal supervisor processes the existing result after restart. All original native turns must have completed within the original execution lease. This result-only path runs the existing pinned acceptance checks, publishes the original receipt through the existing outbox and processes its completion ACK; it does not extend the lease or start another turn. Other stop reasons remain held. Back up the current state first; preserve current status, grant files, outbox, unrelated UNKNOWNs and leases.

Trusted `continuation.task_routing` entries bind a Codex `WorkerRouting` policy to an assigned task ID. Preview and execution resolve the same policy; tasks without an override retain global worker routing. Legacy `continuation.assignments` profiles require explicit migration and are never silently rewritten.

[The November 6 integration checkpoint](docs/BIGPLAN-INTEGRATION-STATUS-20261106.md) records accepted packages, combined remote/crash tests and the gates open at that time. Use the [November 7 verification](docs/evidence/readme-current-20261107.json) for the reviewed source and installed pin; dated checkpoints retain their historical results.

The configured coordinator and the freshly verified immutable owner of its configured team can read the same bounded `coordinator_status`, including recorded timings. Team ownership grants this status view only; control, completion ACKs and private Core data retain their existing permissions.

Development source also distinguishes the stored `ledger_state` from task workflow status. A bound terminal rejection, failure or stop can replace a stale displayed `waiting` only with matching task/source metadata and known terminal work/Core states; active or unknown bindings stay unchanged. Counts follow the displayed workflow state. This read-only projection does not stop native effects, release leases or verify project completion; installation and live acceptance remain separate.

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

Development source keeps CLI startup independent of the optional Linux PTY module: POSIX terminal dependencies load only when that backend executes. The generated Windows CMD launcher preserves child exit codes, including a rollback that rewrites the caller. A bounded public Windows CI job checks imports, CLI help and this launcher contract; it is not desktop or installer acceptance. Current package and unelevated Windows installation still require their own native evidence.

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

The native Postfach page shows the newest 30 team messages (it walks the 50-message pages to the end and keeps the tail) instead of the first page. Choosing the coordinator stays in the web console ("Erweitert"): it needs a handover with session, generation and revision, which the read-only native data access does not cover.

The native sidebar rows are keyboard-operable (Up/Down/Home/End move, Return or Space select) with a selection bar and focus ring. Agent states are shown localized (active/inactive/retired), the overview list carries status dots and an empty state, and bridge reachability is shown once, in the header; the first overview card names the coordinator. The inbox poll re-reads the retained 30 messages, so acknowledgements update.

The new central path module `kirabridge.paths` resolves the directory-architecture-v1 layout under `<FAMILY>/KiraBridge` but returns the legacy paths until a migration marks the layout active; `kirabridge paths` is read-only and `--write-manifests` only writes `tool.json`/`family.json`.

After a verified install the installer keeps at most 5 rollback backups (the active one plus the 4 newest) and the active, previous and one spare release, never a release a service still uses.
Completion notices are tidied in small batches: acknowledged notices are deleted 7 days after acknowledgement (never unacknowledged ones), and notices of the unattended watch targets `default` and `ki-gesamtabschluss-watch` are marked acknowledged after 24 h with an audit entry holding the count.
The diagnostic overflow archive now closes its segment daily, removes rotated segments older than 7 days (each removal anchored in the audit chain) and caps archive writes at 32 MiB per day and process; existing audit rows are untouched.
