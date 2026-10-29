# Intel release closure · 29 October 2026

## Result and approval boundary

**Intel acceptance PASSED. Publication STILL OPEN.** New version0.8.0rc18 has
reproducible actual installable assets on GitHub as an **unpublished draft**, with
authenticated download/install/rollback proven. The published versioned URL and
final public installation command require the separate publication approval and
then a real download test. Productive RC17 was not replaced or restarted.

[Machine-readable evidence](evidence/intel-release-rc18-20261029.json) is the exact
source for counts, SHA256, commands, fixture versions and preservation checks.
[Draft review](https://github.com/landjunge/KiraBridge/releases/tag/untagged-7e6f116bdfb28ec1dc8b) ·
[PR52](https://github.com/landjunge/KiraBridge/pull/52) ·
[future published version](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc18).
The future link is not represented as a working public download before publication.

## Decisions, branches and commits

- User requested safe Intel completion from811b271, no second implementation.
- PR49: feat/managed-message-route-20261028 /36a7c5c452eee8b94454ac78833f37855a9b3477,
  33 commits, draft against main4f4747d449ffb772adc031929a2857af722d0e4c.
- PR50: fix/queue-direct-admission-20261029 /811b2715334493175b7b3e7e6412fe1b03c6f87a,
  one repair commit on PR49, pushed draft.
- PR52: feat/intel-release-rc18-20261029, candidate source**15d071ebaa95d3bef2eed506c21fe7bfd043464c**;
  version metadata/locked project identity and versioned command only.
  The only application-source change from811b271 is __version__17→18.
- Existing builder, guarded transactional installer, MCP/receiver and adapters reused.
- Subsequent README/evidence/documentation commits refer to the immutable source
  above; they do not silently rebuild assets or claim those assets came from a later head.
- Only this existing Codex tab used; no subagents, Terminal windows, focus changes,
  live agent input, queue clear/restore/retire/withdraw or old-message replay.

## Build environment and reproducibility

Actual hardware iMac17,1 (Intel2015), macOS15.7.4/24G517, x86_64,
Python3.11.15, uv0.11.6. Builds require clean exact Git commit.
Two runs of `uv run python scripts/build_release.py --out <private-output>` produced
identical SHA256SUMS. Independently checked387 manifest files and all122 Python
wheel files byte-for-byte against source15d071e. Ruff/format passed392 files;
lock consistency and git diff --check passed.

| Intel artifact | SHA256 |
| --- | --- |
| KiraBridge-macos.tar.gz | 8ec622ca2c6a3ff621c017d55c0f4648d55a738929b5b5be80960778637a388d |
| kirabridge-0.8.0rc18-py3-none-any.whl | a3d66f885da27b76cee5ed05b3976d4dd11c7af70a71f2d43a2d6ef4a112d24c |
| install-macos.sh | 13b9ce3064a66c1ffaaae933a039b463c2cc08915e94c15e7e564e243af07249 |

Only selected Intel assets are attached. The existing builder also emitted a Linux
archive; no new Linux package acceptance/publication is inferred. INTEL-SHA256SUMS
covers the selected files; individual bootstrap/package hashes and the embedded
package pin are retained. No signing/notarization and no offline dependency bundle.
The generic manifest mentions ARM support, but acceptance scope is Intel only.

## Tests and exact results

One actual Intel full suite, source15d071e: **1842passed,1skipped**, no failures,
313.80s pytest time. Actual ThreadDesk770bbc9f0c0a02699cc93cad47d2e2c3782f7080 and
TollGate53fc57cc2e082d022e65e5929cb2a1e186fba852 sources were privately extracted and
supplied through the existing test environment. No configured productive peer was used.
The skipped optional AA reader was then run once against private reviewed
361aef02f2aca7cd9cda46c718db050e9732990b with both expected source hashes: **1passed**.
These are separate observed runs, not a fabricated zero-skip full-suite run.
No precautionary whole-suite repeat was performed.

Full RC14→RC18 local package lifecycle: **10 checks passed**: original pinned RC14
start; upgrade while an authenticated completion_receive read remained open;
healthy new version; preservation of config/credentials/database/user file;
independent launchd lifetime after installer exit; idempotent repeat with same PID;
real restart; crash/KeepAlive recovery; actual rollback to RC14; fresh installation.
Actual stop was verified by test-service bootout and independent absence113.

Then the exact README/scripts/install-command.sh download flow was executed with
explicit isolated installer arguments using **RC17→RC18→RC17**, including an open
MCP completion read: **5 checks passed**. All9 initial draft assets were downloaded
from GitHub and checked against local bytes and GitHub digests. No mock download.
Productive installation, its visible-terminal activation flag, real paid-provider
work, voice Host and OS-entitled AA collector are not established by these fixtures.

Both exact testlabels were absent with independent launchctl print return113:
`com.kirabridge.test.accept-rc18-local-20261029` and
`com.kirabridge.test.accept-rc18-download-20261029`. No other service was stopped.

## Backup, restore and productive preservation

Private0700 root: `~/.local/share/kirabridge/backups/intel-release-20261029-rc18`.
Before edits: candidate/RC17-source archives, statuses/patches, full Git bundle,
consistent SQLite online backup, credential/config copies, productive service plist,
preexisting release metadata. Seventeen file hashes independently reread, SQLite
integrity_check=ok and bundle verified. Privately restored591 source files have
correct bytes and Git modes. An initial comparison wrongly used Git archive0664
metadata against correctly filtered0644 extraction; this failed check is retained
in initial-restore-mode-failure.json, not counted as a successful first attempt.
No productive chmod or restore occurred.

RC17 before/after: PID60636, instance31849a4ff7c346f396b99e31d6fd807d,
started2026-10-29T05:14:06.133578+00:00; startup source SHA
4bb8e3b989a005568ed26a3b0cc1df4459c3cbfd22ca0e53177694455cbf7b8d.
Config/effective config hashes, credential bytes/modes, productive plist and runtime
identity unchanged. The3 protected historical message/job rows (61ccf5a9 unknown,
ed182f06/013a112e blocked) and entire queue_holds/queue_withdrawals tables match the
preflight snapshot. Unknown outcomes remain explicit. Full raw evidence is private;
selected sanitized reports/test logs have hashes in the machine-readable evidence.

## Retained versions and fallback plan

All9 preexisting GitHub releases and their asset IDs/names/digests were independently
compared unchanged (download counters may increase). RC14 published original wheel
and RC17 draft wheel/archive were actually downloaded and hashed. RC17 is still an
authenticated draft, not silently converted into a published release.
RC17 wheel SHA e334e29b5af3a6a3a4c0cebde2f66d954b1591ec5cbd9f14d39597e06c6f3693;
RC14 wheel SHA c5d33839b70badf36371d1fef03ea3a4370e00165db4699647ccacfa3700fadd.
Actual isolated rollback returned a responding RC17 from fde9d87, preserving data.
The productive live-source startup identity is separate from that historical asset.

Before any later productive action: confirm the current actual runtime and idle
state again; take a new consistent backup; preserve the old release/transaction.
On activation failure use only the owned installer recovery/rollback transaction,
then authenticate the responding previous version and verify data preservation.
Do not bulk restore old database state, replay historical work, kill agent sessions
or rewrite old assets. If a guard refuses, stop and reconcile evidence.

## External gates and next approval

ARM and paid hosted-macOS jobs are explicitly deferred. Existing workflows still
triggered from push/PR, but hosted jobs started no steps due account payments OR
spending-limit requirements; ARM capacity advisory also recorded. No manual dispatch,
paid retry, billing modification, check bypass or false pass. Local Intel success
does not turn GitHub macOS failures green or establish ARM acceptance.
Parent811b271 Linux Verify40945132909 passed1826/17 on Python3.11 and3.13.
PR52 workflow outcomes are recorded separately with their actual commit/run state.

**Pending decision:** approve the reviewed integration chain PR49→PR50→PR52 and
publication of the immutable RC18 candidate above, with ARM/hostedMac explicitly
left outside the Intel acceptance scope and required repository gates honored.
Resolve any mandatory failing check through an explicit acceptable gate decision;
never bypass protections. After approval: merge in order, verify final source
content equivalence to the tested candidate, publish a versioned prerelease without
replacing older releases, then actually download/hash/test the published command in
isolated paths. A productive RC17 replacement/restart needs separate approval.

## Masterplan status delta · KB-INTEL-20261029

DONE: versioned Intel build, reproducibility, integrations, real isolated install/
restart/stop/rollback, verified backups, draft download and updated documentation.
OPEN: merge/publication approval and actual published URL/command verification;
productive activation separately open. DEFERRED/EXTERNAL: ARM and paid hostedMac.
Existing811b271 queue repair remains complete in development; no duplicate integration
or installer work is planned. This delta links into the existing development plan
and work-memory Whiteboard188ce4729a62; existing history is preserved. The exact
external Library Masterplan29Oct original has not been identified, so no update to
that unlocated source is claimed.
