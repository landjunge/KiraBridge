# Main, RC15, RC16 and repair consolidation / Zusammenführung

User explicitly requested consolidation on 24 October 2026. Development is isolated
in `.worktrees/current-release`, branch `integration/current-release-20261024`.
Parents: `main` `9d03ea8bf75616bfcd5514a9ea5af7f888cbf7b5` and repair branch
`48a512e52bf0b9a8999596bcd656cd233e078408`. The latter already contains RC15
`efb805a`, RC16 `a890375`, queue recovery and terminal/Whiteboard repairs.
No duplicate cherry-pick of RC15 or RC16; a real two-parent merge preserves ancestry.

The merged source uses **0.8.0rc17** consistently to distinguish it from existing
RC15/RC16 draft binaries. Published release remains RC14. A source merge is not
release acceptance, publication or deployment.

## Conflict review and preserved boundaries

46 conflicted files required inspection of both parent versions. The native team
worked on explicitly disjoint files in the isolated integration worktree:

- A `/root/terminal_repair`: Bridge/config/task store/runtime/readiness/handoff/
  approval. Preserve main-owned workflow stop, observations, knowledge, PNG models;
  combine RC16 queues/read lanes, completion, exact visible selection, paste-only,
  file transfer and output history. Preserve main's non-default-config state isolation,
  `install_wrapper=False` and service executable override. Remove duplicate identical
  handoff schema DDL, not audit or user data.
- B `/root/whiteboard_repair`: MCP/ThreadDesk/team integration and directly related
  tests. Preserve existing management/read/knowledge ports and new schema preflight,
  discovery/queue registration; retain address/ownership/role boundaries.
- C `/root/receiver_contract_audit`: CLI/setup/AgentManager/Grok/development status
  and related tests. Preserve native adapters, guided setup, verified installer,
  key protection and complete policy; combine visible-control/queue-hold/status routes.
  Preserve main `local_output_tokens`, handoff-status capacity and PNG assertions.
- Root: README EN/DE, architecture/history, version/lock, build and integration review.
  Preserve main's source-distribution inputs, guarded existing-output/symlink refusal,
  Linux source installer, examples, provider limits and historical evidence. Use the
  guarded macOS updater for macOS, not a second competing macOS installer.

Auto-merged models/security retain strict existing main interfaces. Main's workflow,
observations, knowledge and native adapter modules remain in the tree; they were
already partially present in the runtime ancestry and are not discarded by taking
an entire parent tree. Productive RC14, user profiles, OS permissions and other Codex
sessions remain untouched. Server & Sync is outside this session's scope.

## Validation and release gates

This integration changes previously divergent runtime contracts. Necessary validation
is the existing cross-module regression/security checks after conflict resolution,
plus release-builder guards and exact-source package/reproducibility acceptance.
Only affected failing checks will be repeated; earlier isolated native/Whiteboard
proofs are historical, not automatically RC17 product acceptance. Exact results follow
in this report when executed. No tests are currently claimed passed for this merge.

Required GitHub CI still reports account billing/spending-limit refusal before job
steps; independent review and native positive agent input acceptance remain open.
No merge into protected main, new published release or user-library import is claimed.
Existing draft assets must retain their source pin and historical checksums.

## Executed integration results

Actual Intel macOS15.7.4/Python3.11.15, isolated locked virtual environment:

- One regression pass stopped at eight failures: 815 passed,25 skipped. All remaining
  466 not-yet-executed node IDs were then run exactly once:447 passed,18 skipped,
  one additional failure. No already-passing suite was repeated. Collection1314 cases.
- All nine failures reconciled: older `selected()->None` test doubles replaced with
  valid agent-free tmux rows (two input-policy cases plus one voice case), old UI fixture
  now uses `operator_application`, shared main stylesheet restored to current center
  HTML, PNG limits tested against unchanged4096/16MiB constants, valid ancillary PNG
  metadata preserved while invalid CRC is rejected, and pure-read failures expect
  `failed` rather than an uncertain write outcome. No production rights/guards relaxed.
- Targeted proof: two input-policy cases passed, one voice case passed, one console
  asset/security case passed, six PNG/observation cases passed (includes one directly
  changed valid-PNG case). C's first PNG subset lost its completion output; after
  confirming no pytest process remained, only those six were repeated with saved log.
- Across the collected cases:1271 now have passing evidence,43 remain skipped, not
  accepted. Existing skip conditions concern optional pinned ThreadDesk/TollGate/AA
  integration sources and missing tmux. These integration paths still need their
  actual configured prerequisites; a skip does not establish product interoperability.
- Initial Ruff/format found proxy line length and older dynamic-ThreadDesk test layout.
  Only those two files were formatted/rechecked; passed. Changed follow-up tests and
  release builder lint/format passed. PDF fixture is marked binary in `.gitattributes`
  to preserve required xref spaces byte-for-byte instead of stripping them.

RC15/RC16 GitHub drafts now lead with historical-source warnings. Their original
source targets and asset counts were independently read back; assets were not replaced.
During the metadata update, GitHub returned temporary untagged draft names when tag
fields were omitted; explicit original tag/source fields were immediately restored
and verified. Both remain drafts with `published_at=null`.

Package builds/acceptance and normal PR/CI/review follow source commit. These results
do not turn the earlier refused native focus test into a positive input acceptance.

## Built and remotely tested candidate

Two-parent merge5089fca8f72bc0088a967eb057d85b0e461f0b55 is pushed to
`integration/current-release-20261024`; all main/RC15/RC16/repair pins verified as
actual ancestors. [PR28](https://github.com/landjunge/KiraBridge/pull/28) targets main,
OPEN/DRAFT, not merged. Verify40108852591 and macOSpackage40108852507 did not start
steps; Intel check120916129067 explicitly cites failed payments/spending limit.

Two exact-commit builds have identical all-four-artifact SHA256SUMS; all126 wheel
source members match committed bytes. [RC17 draft](https://github.com/landjunge/KiraBridge/releases)
holds the wheel, macOS update/source package, authenticated bootstrap, Linux source
package, checksum sidecars/manifests and evidence. It remains draft/unpublished.

One real authenticated RC17 download acceptance passed isolated Intel-macOS install,
RC14 upgrade, status/version, idempotence, preservation, restart/crash recovery and
rollback. Own test service absence independently verified after cleanup. The exact
template and expanded isolated invocation, hashes and remaining gates are in
[acceptance report](ACCEPTANCE-MACOS-RC17.md) and
[package evidence](evidence/package-rc17-20261024.json).

Documentation-only follow-up records these outcomes; packaged code remains pinned
to5089fca. No productive install or publication. Remaining43 skipped integration
cases, positive native agent input, mandatory CI and independent review are explicit
gates, not successes inferred from package acceptance. RC14 remains published latest.
