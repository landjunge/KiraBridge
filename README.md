**English** · [Deutsch](README.de.md)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-256.png">
    <img src="assets/design/icons/light/KiraBridge-light-256.png" alt="KiraBridge" width="256" height="256">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/landjunge/threaddesk/blob/main/README.md" title="ThreadDesk"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/ThreadDesk-dark-128.png">
    <img src="assets/readme/ThreadDesk-light-128.png" alt="ThreadDesk" width="48" height="48">
  </picture></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass/blob/main/README.md" title="4AllPass"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/4AllPass-dark-128.png">
    <img src="assets/readme/4AllPass-light-128.png" alt="4AllPass" width="48" height="48">
  </picture></a>
  &nbsp;
  <a href="https://github.com/landjunge/tollgate/blob/main/README.md" title="TollGate"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/TollGate-dark-128.png">
    <img src="assets/readme/TollGate-light-128.png" alt="TollGate" width="48" height="48">
  </picture></a>
  &nbsp;
  <a href="https://github.com/landjunge/agent-authority-lab/blob/master/README.md" title="Agent Authority"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/Agent-Authority-dark-128.png">
    <img src="assets/readme/Agent-Authority-light-128.png" alt="Agent Authority" width="48" height="48">
  </picture></a>
</p>

<h1 align="center">KiraBridge</h1>

<p align="center"><strong>Talk to your AI. Get the work done on your computer.</strong></p>

KiraBridge connects ChatGPT to **Grok Build and Codex running in terminal windows
on your computer**. Discuss what you need in chat, pass the work to those terminal
agents and follow their replies while choosing what they may access.

**macOS · Intel — [0.8.0rc21](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc21) · October 31, 2026 · Preview**

### [Download KiraBridge — app and installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-0.8.0rc21-Intel-macOS.zip)

[App only, if the service is already installed](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-App-0.8.0rc21-Intel.zip)
· [Checksums](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/SHA256SUMS-INTEL)
· [All releases](https://github.com/landjunge/KiraBridge/releases)

Downloads require a GitHub account with access to this private repository.
This is a preview; there is no stable release yet. RC21 is available for Intel Macs.

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

1. **Install the service.** Download and fully extract the app-and-installer ZIP.
   Open `KiraBridge-Installieren.command` and follow the installer in Terminal.
2. **Open the app.** Copy `KiraBridge.app` to the `Applications` folder in your
   home folder (`~/Applications`; create it if needed), then open it. The app
   uses the service installed in step 1.
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
Read [installation and help](docs/INSTALL-RC21.md) for setup, updates and known issues.

Visible handoffs to terminal agents send your text unchanged. Confirmed delivery is separate from an agent reply or completed work.

## Planned collaboration

The five products remain independent. The goal is a shared workflow with **KiraBridge as the communication hub**:

| Product | Role in the shared workflow |
| --- | --- |
| [ThreadDesk](https://github.com/landjunge/threaddesk/blob/main/README.md) | Keeps project context, knowledge and results. |
| [KiraBridge](https://github.com/landjunge/KiraBridge/blob/main/README.md) | Relays tasks, questions and replies between chat, local agents and tools. |
| [4AllPass](https://github.com/landjunge/4AllPass/blob/main/README.md) | Manages credentials; is intended to enable specifically approved access. |
| [TollGate](https://github.com/landjunge/tollgate/blob/main/README.md) | Checks connected calls and enforces usage limits and stops. |
| [Agent Authority](https://github.com/landjunge/agent-authority-lab/blob/master/README.md) | Shows observations, contradictions and missing evidence; does not approve actions. |

Some interfaces already exist. A fully configured and verified workflow across all five products is still planned. Approvals stay with the responsible tool and the human. KiraBridge and Agent Authority require access to their private repositories.

## License

Private, non-business use is free under the
[Netzwerkpunkt Personal Use License 1.0](LICENSE). Business use requires separate
written permission. The German license text governs.

[Developer documentation](docs/DEVELOPERS.md)
