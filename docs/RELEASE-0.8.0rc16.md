# 0.8.0rc16 — unpublished integration candidate / unveröffentlichter Kandidat

Historical source-pinned draft. The combined source and tested package candidate are now RC17; see [consolidation](CONSOLIDATION-20261024.md) and [RC17 package evidence](ACCEPTANCE-MACOS-RC17.md). This historical asset was not overwritten.

Latest published release remains [v0.8.0rc14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14).
RC15 is a separate historical draft. RC16 includes that runtime and installer lineage,
plus fresh MCP discovery, safe visible-terminal dispatch and opt-in file-byte transfer.
`main` is a separate lineage; wholesale replacement would lose existing features.

Changes / Änderungen:
- Principal-scoped discovery revisions, effective permissions, live terminal/agent
  observations, MCP initialization version and downstream catalog refresh.
- ChatGPT direct commands use a confirmed idle visible Terminal.app shell or a
  separately created visible window. TTY, current-user shell PID and process identity
  are checked at dispatch. No background fallback or task interruption. Internal
  Codex/Grok workflows and the independent ThreadDesk route retain their boundaries.
- Accepted exact window tasks and automatic grants agree; manual approval and
  one-shot/replay checks remain. Root-owned login PID is distinguished from the
  current-user shell; stale targets are rejected.
- Modular selected-file/export sources, inventory, authorization, immutable staging,
  bounded streaming/checkpoints, byte hashes, ZIP validation, redacted diagnostics,
  and a versioned ThreadDesk MCP receiver port. Disabled by default; no grants added
  to existing configurations and no account-wide Library API claimed.
- Only independently fetched, strictly bound durable receipts count as file import.
  The ThreadDesk v1 receiver remains a proposed contract awaiting its implementation.

See [module review](MODULARITY-REVIEW-20261024.md),
[file transfer setup](FILE-TRANSFER.md), [receiver contract](THREADDESK-FILE-TRANSFER-V1.md),
[installation](INSTALL-MACOS.md) and [acceptance evidence](ACCEPTANCE-MACOS-RC16.md).

Reproduce from the clean source commit recorded in `release.json`:
`uv sync --locked --dev`, then
`uv run python scripts/build_release.py --out dist/rc16-build`.
Repeat in a different empty directory and compare `SHA256SUMS`.
Python 3.11 and uv 0.11.6 required. Hash-locked dependencies are downloaded, so this
is not an offline installer. No Apple signing/notarization. Existing launchd behavior
continues independently of Terminal/browser windows. No production installation changed.

**Release gates:** GitHub CI is blocked by account billing/spending limits. Required
CI/review and actual ThreadDesk product interoperability/storage acceptance are not
satisfied. Test fixtures do not establish product acceptance or a live ChatGPT file
selection. Apple Silicon and older macOS remain unverified. Do not publish or claim
an integrated/approved release while these gates remain.
