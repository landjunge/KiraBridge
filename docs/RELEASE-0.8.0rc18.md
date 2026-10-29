# KiraBridge 0.8.0rc18 · Intel macOS candidate

This is a new version based on queue repair `811b2715334493175b7b3e7e6412fe1b03c6f87a`
and PR49 base `36a7c5c452eee8b94454ac78833f37855a9b3477`. Existing RC17 artifacts,
release history and the productive RC17 service are preserved. No implementation
of the existing installer, receiver or integrations is duplicated.

## Changes

- One bounded admission attempt for new visible work; concrete busy/selection errors.
- Pinned dynamic target identity and idempotency; historical work never auto-replays.
- Protected unknown outcomes; rejection holds only for proven pre-input failures.
- Concurrent claim/shutdown, restart and late-ACK/reply recovery fixes from PR50.
- New version identity only; application logic is otherwise exactly the PR50 baseline.

## Acceptance and limits

Local Intel acceptance is being performed on the operator Intel iMac with
macOS15.7.4 x86_64, Python3.11.15 and uv0.11.6. The authoritative completed evidence,
exact artifact source commit, hashes and approval decisions are tracked in
[the Intel release work report](INTEL-RELEASE-20261029.md). This static candidate
note does not assert a test result or a publication before it occurs.

The package contains a portable Python wheel plus source, locked dependencies,
the existing guarded transactional installer and version/source/file manifests.
It requires Python3.11, uv0.11.6, authenticated GitHub access and network access
for locked dependency downloads. It is not an offline installer, Apple-signed
application or notarized distribution. macOS15.7.4 Intel is the intended
acceptance target; an iMac2015 model name does not certify older macOS support.

ARM, macOS26 and paid hosted-macOS jobs are explicitly deferred. Existing GitHub
macOS failures are external payment/spending-limit blocks, not passed tests.
Local evidence does not turn those checks green. Linux artifacts emitted by the
existing builder are not part of this Intel release acceptance or asset selection.

## Publication and rollback

Merge, publication and productive installation each require separate operator
approval after the actual Intel results are reviewed. Draft assets are accessible
only to authorized draft readers; the final public/versioned URL is not claimed
working before publication and an actual download test.

[Version/download status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc18)
· [all retained releases](https://github.com/landjunge/KiraBridge/releases)
· [macOS installer contract](INSTALL-MACOS.md)

The installed RC17 and its startup identity are recorded in the private preflight
backup. Rollback operates only on a proven owned installation transaction and
must confirm the responding previous version. It must not overwrite newer results
with an old database, replay unknown messages or terminate agent sessions.
