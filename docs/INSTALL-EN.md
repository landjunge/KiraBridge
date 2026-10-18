# Install KiraBridge · 0.6.0rc3

**Private release candidate for acceptance. No public installation yet.**
The included `LICENSE` is the Netzwerkpunkt Personal Use License1.0. German
text governs; English is a translation. Private non-business use is free;
business use, resale and paid services need separate written permission.
No general redistribution permission. Custom source-available terms, not an
OSI standard or legal review. Third-party licenses and historical rights remain. The project site `kirabridge.netzwerkpunkt.de` is planned;
this does not establish DNS, hosting or publication.

Built specifically for Vibe Coding: discuss what to build or change with ChatGPT;
ChatGPT passes tasks through KiraBridge to Codex or Grok on your computer. Both
can collaborate on the same project with configured permissions. Further CLI
integrations are planned.

## Choose the right source, service and package first

| State | Meaning |
| --- | --- |
| New private RC3 `0.6.0rc3` | The full source pin is in `release.json` and the evidence manifest; includes project/workflow code through reviewed base `612a5c8`. |
| Documented operator Mac `0.5.2` with selected backports | A separate installed service with its own source/config/runtime evidence, not defaults for new users. |
| Frozen private RC2 `57bee99` | Historical artifacts remain unchanged. Newer options are absent; do not use it with today's operator configuration. |

[RC3 acceptance and publication gates](RELEASE-ABNAHME-20261019-RC3.md) remain
separate. A source pin is not usability acceptance. Inspect the loaded service
with `kirabridge status` and concrete readiness. Preserve healthy existing setup.

## Normal quick start

Obtain the approved original package for your computer. This RC supplies packages
for **macOS15 Intel x86_64 / Apple Silicon arm64** and **Ubuntu24.04 x86_64 with a systemd user session**.
Windows, other distributions and servers without user sessions do
not have a complete installation acceptance claim. Network access to GitHub,
PyPI and uv's Python distribution is required. Agent tasks require separately
installed, signed-in Codex/Grok CLIs. KiraBridge creates no accounts and does not
take over existing interactive sessions. CLI detection is not a login/model test.

1. Compare the archive's SHA-256 with the `SHA256SUMS` supplied with the approval:
   `shasum -a 256 FILE.tar.gz` on macOS, `sha256sum FILE.tar.gz` on Linux.
   A checksum is not a signature or independent proof of origin.
2. Extract the archive, open its folder in Terminal and run **one start command**:

   ```sh
   sh install.sh --language en
   ```

The guide detects prerequisites, obtains a pinned user runtime after consent,
and walks through local installation and ChatGPT setup. No Python or package
manager knowledge required. No administrator privileges or sudo prompts. It
uses uv0.11.6 from its original publisher with an embedded SHA-256, Python3.11.15
and hashed dependencies in `uv.lock`; an existing matching uv is reused. This is
a network installation, not an offline bundle.

Choose the specific project folder. New identities use **manual** task approval.
Scope is shown before creating local setup and before giving ChatGPT the existing
local policy. Existing permissions are never expanded. Program/folder allowlists
are not an OS sandbox: an allowed interpreter or agent still has the user's OS rights.

Versioned programs: `~/.local/share/kirabridge/releases/`; command:
`~/.local/bin/kirabridge`. If absent from PATH, invoke that full path. No shell
profile is changed. Configuration/separate keys: `~/.config/kirabridge/` (0600
files); data/queue/audit: `~/.local/share/kirabridge/` (0700).

## Connect ChatGPT in the same flow

The flow reuses `kirabridge chatgpt setup`. A missing official tunnel client can
be downloaded from its original publisher after consent and checked against an
embedded hash. Existing clients are preserved. Other versions:
[official releases](https://github.com/openai/tunnel-client/releases/latest).

Complete account steps yourself on the displayed official pages. You need a
**restricted tunnel runtime key**; an ordinary API key or Codex login is not a
substitute. Enter it hidden in your local Terminal; it is stored separately with
0600 permissions, never placed in command arguments. Do not paste secrets into
chat or logs. Check account access and possible charges in the target account;
availability is not guaranteed for every ChatGPT workspace.
[Official tunnel setup and permissions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

The final status distinguishes:

- Authenticated response from the local dispatcher.
- Tunnel process, health and readiness.
- A real `bridge_health` call **from the intended ChatGPT chat** with its result.
  Only the actual chat call proves this connection; local readiness is insufficient.
  Before a concrete workflow, use `bridge_readiness` with the functions/paths it
  needs. For manual task approval open `~/.local/bin/kirabridge approvals` locally.

Setup does not publish a public plugin. Existing incomplete/unready tunnel
configuration is preserved with a concrete next inspection step; keys are not
replaced. Connection errors never justify blindly resubmitting uncertain writes.

## First confirmed task and explicit agent permissions

After local status and ChatGPT connection, select an existing authorized project
file. The [DE/EN ChatGPT guide](CHATGPT.md) shows one harmless read with a stable
task ID, manual approval when required and subsequent `task_get`. Only the actual
result proves that path; health alone proves neither file access nor agent writes.

In current source, `agents.codex.sandbox_mode` defaults to `read-only`; the operator
must explicitly choose `workspace-write` for the structured adapter. This is not an
extra `kirabridge ask` flag. Principal/CWD checks remain, and child MCP is disabled.
The native Codex MCP identity, ChatGPT App principal and a managed Codex child are
separate contexts. The broader authorized App profile on the operator Mac is not
a new installation default.

Grok ACP local tools need all three opt-ins: `agents.<name>.allow_local_tools`,
principal capability `agent.local_tools` and task argument `local_tools=true`. A Grok
API text turn gains no local tools or complete budget/stop control from this.
Neither adapter takes over an existing interactive session.

Separate grants cover [PNG images](IMAGE-READ-20261018.md),
[ThreadDesk management](THREADDESK-ADAPTER-20261018.md),
[knowledge](THREADDESK-KNOWLEDGE-20261018.md) and
[observer-only audit export](WORKFLOW-OBSERVATION-EXPORT.md). New setup profiles
do not automatically receive all of them. Optional
[owned workflow control](WORKFLOW-CONTROL-CONFIGURATION.md) is `stop_only`: cost
unknown, no hard dollar cap or universal control over arbitrary programs.
Installation alone does not enable it. TollGate and ThreadDesk are not bundled
or automatically installed; they need separately reviewed source pins, local
setup and explicit operator configuration. See [security limits](SECURITY.md).

## Rerun and update

Rerun the same start command. Existing settings, credentials, permissions and
data are recognized and retained. The healthy developer installation is not
reconfigured just to demonstrate this flow.

For a **managed release installation**, verify/extract the new original package
and run its installer. Active/pending tasks and receiver jobs must finish first;
updates are refused otherwise. Only the recorded hash-checked launcher is
replaced, with its predecessor backed up. Previous program folders are retained.
No database rollback or credential restore occurs. Other CLI sessions and tunnels
are not stopped. Existing proxies may still run the older client code; reconnect
your own tunnel deliberately when appropriate, keeping original task IDs and
never replaying uncertain writes.

Custom/developer installations without `installation.json` are **not** converted.
The guide reports this condition and preserves their service/update mechanism.
For a manual migration, back up configuration, drain queues, record the old
service path and switch explicitly. Do not overwrite a healthy custom setup
merely to try the wizard.

## Stop and uninstall, retaining data

Finish your work and inspect `kirabridge tasks`, `pending` and, for receiver jobs,
`kirabridge message status`. Stop your own configured tunnel runtime with its
existing `tunnel-client runtimes stop kirabridge`; never stop someone else's
session or delete the remote tunnel/key. On macOS unload the user service:

```sh
launchctl bootout "gui/$(id -u)/com.kirabridge.bridge"
```

On Linux: `systemctl --user disable --now kirabridge.service`. If the optional
local approval page is installed, also stop its own service (`com.kirabridge.approvals`
on macOS; on Linux gracefully stop the approval process you started). Then remove
only the recorded owned launcher and service file: macOS
`~/Library/LaunchAgents/com.kirabridge.bridge.plist`; Linux
`~/.config/systemd/user/kirabridge.service`, followed by `systemctl --user daemon-reload`.
Previous release program directories can be removed individually after inspection.
**Do not recursively remove** `.local/share/kirabridge` or `.config/kirabridge`:
these retain data, audit, queue, configuration and keys for resumption or a
separate explicit deletion decision. OS/uv caches are not automatically deleted.
Custom installations follow their own recorded service paths.

## Troubleshooting and limits

- Wrong package/checksum: obtain the matching original; do not bypass checks.
- Download failure: check network/disk space and rerun the same command.
- Foreign launcher/service: preserved; use its custom update procedure.
- `service_busy`: finish pending/active work normally; never delete the database.
- No Linux user systemd bus: check your user session; no sudo/linger change is forced.
- Missing account feature: the operator must establish target workspace/Platform access.
- Intel macOS uses `cryptography48.0.1`, since upstream stopped Intel wheels in49.
  The RC limits this pin to Intel macOS and prevents a surprise compiler build.
  Security/maintenance review of this older dependency line remains a publication gate.
- No independent security audit, universal account availability or permanent tunnel
  guarantee. Linux clipboard needs a graphical session. Automatic multiuser OAuth
  integration is not included.

## Optional developer installation

In an authorized private checkout: `uv sync --locked`, then `uv run kirabridge setup`
and on macOS `uv run kirabridge service install`. Manual Linux templates/configuration
remain in the private operations guide. The setup command refuses to overwrite
existing configuration (`already_configured`); inspect status/readiness instead of
repeating initial setup. The normal release path needs no repository
layout knowledge or developer commands.
