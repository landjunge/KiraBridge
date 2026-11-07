# KiraBridge 0.8.0rc41 · Debian/Linux server test release

DEBIAN-DIRK-RELEASE-20261107. Separate Linux x86_64 prerelease
`linux-v0.8.0rc41`; the macOS desktop download remains separate.

- Debian 13 host support added to the existing user-level installer; Ubuntu
  24.04 remains accepted. Explicit isolated destination paths and fresh-config
  port selection are supported.
- Fixed the bootstrap lock left behind before activation. Fresh-install
  rollback disables/removes its user unit and reloads the manager.
- Existing systemd-user installation, HTTP MCP, bearer authentication, health,
  source identity checks, update and rollback reuse the Grok implementation.
  Config, credentials, permission policy, live task data and UNKNOWN states
  are preserved. Rollback does not restore an old database over newer data.
- Exact older guided-install units remain unchanged and compatible through
  their stable launcher. Intervening edits and foreign definitions are preserved.
  Optional environment files are scoped to the selected configuration.
- Native Debian acceptance, JUnit, artifact checksum and the actual GitHub
  download comparison are release gates recorded in the evidence assets.
  Earlier macOS mocks are not counted as native Debian acceptance.

Installation: [Deutsch](INSTALL-LINUX-SERVER.de.md) ·
[English](INSTALL-LINUX-SERVER.md). Normal user; no sudo. Online prerequisite
bootstrap (uv 0.11.6, Python 3.11.15, locked dependencies); no offline guarantee.
A running systemd user manager is required; linger is never enabled automatically.

No macOS GUI, Terminal.app, native keyboard or general desktop parity.
Clipboard helpers are optional. Remote ChatGPT/account/tunnel setup is separate.
No Windows changes or productive Mac installation belong to this release.
Private GitHub repository access is required to download directly.
