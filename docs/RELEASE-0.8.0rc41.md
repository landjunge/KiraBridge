# KiraBridge 0.8.0rc41 · Debian/Linux server test release

DEBIAN-DIRK-RELEASE-20261107. Separate Linux x86_64 prerelease
`linux-v0.8.0rc41`; the macOS desktop download remains separate.

Published November 7, 2026: [release and evidence assets](https://github.com/landjunge/KiraBridge/releases/tag/linux-v0.8.0rc41).
Source `350d36854fc9dd37725d7c00a91b72cd1bd32b15`, integrated by
[PR72](https://github.com/landjunge/KiraBridge/pull/72) as `2bbf6d9`.
Archive SHA-256: `1b851236bd603fcfaf5984c075be08b52b81b9cdbc4b93ff08d1001ae3a9d41f`.
All 40 initial release assets were actually downloaded again from GitHub and compared
byte for byte; all 1,271 manifest file digests passed. [Final delivery report](evidence/debian-dirktest-release-20261107.json).

Native Debian 13.6/systemd 257 acceptance: 25 cases on source `428271a`, with identical
runtime, installer, lock and guide bytes in the final archive; five additional native
cases directly accepted the exact `350d368` archive. CI [42374701083](https://github.com/landjunge/KiraBridge/actions/runs/42374701083)
passed on Python 3.11 and 3.13 (each 5,009 passed, 254 skipped, four subtests;
29 remote tests with zero skips). Skips are not native acceptance.

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
