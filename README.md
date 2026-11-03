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

**macOS · Intel — [0.8.0rc30](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc30) · November 3, 2026 · Preview**

### [Download KiraBridge — app and installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc30/KiraBridge-0.8.0rc30-Intel-Installer.zip)

[Checksums](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc30/SHA256SUMS)
· [All releases](https://github.com/landjunge/KiraBridge/releases)

Downloads require a GitHub account with access to this private repository.
This is a preview; there is no stable release yet. RC30 is available for Intel Macs.

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
See [RC30 installation evidence](docs/RC30-HOTPATHS-20261103.md) for the current
package and [earlier installation and help](docs/INSTALL-EN.md) for the RC20 guide.

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

## License

Private, non-business use is free under the
[Netzwerkpunkt Personal Use License 1.0](LICENSE). Business use requires separate
written permission. The German license text governs.

[Developer documentation](docs/DEVELOPERS.md)
