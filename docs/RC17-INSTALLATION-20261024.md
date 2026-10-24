# RC17 completion and authorized Mac upgrade · 2026-10-24

User order: finish/verify concrete package → safely upgrade existing Mac and verify
actual service/input/log access → only then separate Braille/pink design preview → stop.
The current instruction authorizes the productive upgrade, preserving configuration,
permissions, credentials, Whiteboards and originals. Historical no-deployment statements
describe earlier instructions. No design has started at this report's source snapshot.

## Verified starting state

Mainc0f94886 includes PR28/a74fe613 and documentation PR29. Published release RC14;
RC17 release422826930 remains draft. Reproducible c0f package/hash/download and real
Intel-macOS upgrade/rollback evidence already exist and are reused; no whole-suite retry.
Actual responding productive service: RC14/PID58776, managed install2f5d2fa. Its original
configuration digest was e4f3d2aab9b35727a211ca77cc57523b39618cd6bb36c4616998092fb43601f8.
Config/credential contents are not copied into repository evidence.

Three queued jobs prevented a safe switch. All addressed to this Codex identity:
dc52c315-b9d5-48c5-8de6-3fdf69970b9b (Library),
b1f665de-f94e-42b7-b56e-b588104a67c6 (team continuation),
febea059-0211-42ec-9f78-0893312b8be8 (terminal repair).
Each full original was read, then received and acknowledged through the existing
authorized MCP inbox, with its actual receipt. RC14's existing receiver records
`externally_acknowledged=true`, `run_id=null`, outcome `not_executed`. Delivery-job
completion means receipt in this ongoing session, NOT Library completion, Terminal
delivery or agent execution. No resend, SQL cancellation, forged execution receipt,
history deletion or unknown-handoff retirement. Active task/receiver counts became0.

## Concrete remaining defects before installation

1. Native agent process presence was treated as activity even for `require_idle=true`:
   `SessionManager.insert` rejected before checking current agent readiness. Two
   focused cases reproduced the failure. Only a task-owned native process selection
   can now use fresh readiness instead of the transport busy flag; actual working/
   unknown widgets, invalid identities and busy unowned shells remain refused.
2. An old unknown handoff reserved every window for the same agent name. Explicit
   `submit=false` now may use an independently confirmed different window AND TTY
   with disjoint shell/agent PIDs, task-owned native identities and fresh readiness.
   Same task/window/TTY/PID, active handoffs, automatic delivery and submitted turns
   retain existing guards. Old row/binding/events/receipts remain unchanged; no replay
   or global index migration. Correct reproduction failed `visible_target_busy`.

Required tests only:4 idle/identity/busy-shell cases passed;7 resource-isolation
cases passed;4 directly affected permission/activity/durable-unknown/no-replay cases
passed. No whole suite. New reservation fixture initially omitted conversation,
used an inappropriate automatic work route and the wrong renderer; these fixture
errors were corrected and only affected cases rerun. Those failures are not counted
as product bug reproductions. Independent native-team read-only safety check found
no remaining identified issue; it required realistic native identity fixtures for
the two pre-existing durable-paste cases. Guards were not loosened for fixtures.

The existing package acceptance script adds `--upgrade-only`: the new concrete wheel
must pass actual isolated RC14 upgrade, version/status/data preservation and rollback,
without repeating unchanged idempotence, KeepAlive and fresh-install checks. Default
full acceptance remains unchanged. Actual installation/input results follow only
after execution. GitHub Actions billing failures are not local test successes.
