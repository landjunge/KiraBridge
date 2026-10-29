# Intel release closure · 29 October 2026

## Scope and decisions

Operator request: build a reproducible, actually installable Intel package from
811b271; reuse existing integrations/installers; isolate every lifecycle test;
keep productive RC17 intact. Work only in this Codex tab. No other agent sessions,
new Terminal windows, historical queue replay, merge or publication are authorized.
Local tests and their own temporary launchd service are expressly authorized.

- Candidate: new version0.8.0rc18, branch feat/intel-release-rc18-20261029.
- Parent: PR50 /811b271 on PR49 /36a7c5c. Both are pushed, open draft PRs.
- Source changes: version identity and versioned command only; no second installer.
- Productive RC17: PID60636, instance31849a4ff7c346f396b99e31d6fd807d,
  started2026-10-29T05:14:06.133578+00:00; source startup SHA
  4bb8e3b989a005568ed26a3b0cc1df4459c3cbfd22ca0e53177694455cbf7b8d.
- ARM and paid GitHub macOS jobs deferred, never counted as passed. No manual
  workflow dispatch or paid retry. Existing workflow triggers are retained;
  automatically triggered jobs are reported by their actual state.
- Release preparation means an unpublished new draft and immutable candidate assets.
  No old release/asset is overwritten. Publication still needs fresh approval.

## Backup before modifications

Private0700 directory:
`~/.local/share/kirabridge/backups/intel-release-20261029-rc18`.
Candidate and RC17-source Git archives, statuses/patches, full Git bundle,
consistent SQLite online backup, private config/credential copies, production
service plist and preexisting GitHub release metadata. Seventeen file hashes
reread; bundle verification and SQLite integrity_check passed. No production restore.

## State of acceptance

IN PROGRESS: exact-head Intel integration suite; reproducible double build;
isolated RC14 upgrade/fresh install/restart/KeepAlive/rollback and current RC17
rollback fixture; authenticated draft download/install-command check; independent
fixture cleanup and production-preservation check. Concrete results are added
only after observation. Initial failures remain recorded.

OPEN: separate approval for merge, versioned publication, then actual published
URL/installation-command verification. Productive installation is a separate
approval and remains outside this development/test step. RC17 is currently a
GitHub draft; preserving its authenticated download is not a claim of public release.

## Existing evidence, not repeated implementation

[Queue repair](QUEUE-DIRECT-ADMISSION-20261029.md),
[prior PR49 Intel acceptance](evidence/pr49-local-macos-20261029.json),
[ordered repair gates](REPAIR-SEQUENCE-20261024.md).
Full Linux Verify40945132909 on811b271: Python3.11/3.13 each1826passed/17skipped.
Previous PR49 Intel acceptance covers71bfbb9, not this new version's package.

## Masterplan delta

KB-INTEL-20261029: packaging/acceptance IN PROGRESS; publication OPEN pending
operator approval; ARM/hostedMac EXTERNALLY BLOCKED/DEFERRED. Queue repair remains
implemented and tested at811b271; production activation remains OPEN. Existing
five-product/masterplan work is not recreated. Source of truth for this delta is
this report plus existing work-memory board188ce4729a62, appended once by operationID.
