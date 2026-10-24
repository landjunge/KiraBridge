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

## Installed b54f462 and remaining native focus repair

The productive upgrade to b54f462 actually completed on Intel macOS15.7.4. Both
Kira and Codex health routes reported RC17, PID35689 and instance0c98a902. All126
installed package files matched the built wheel. Raw configuration/credential
hashes and modes were unchanged; the4203 previously captured tasks,271 messages
and45 handoffs remained intact; SQLite quick_check passed. Installer backup:
`install/backups/20261024-185958-81d93e8a`. Authorized bounded log-file read passed.

The positive native input task `rc17-live-submitfalse-20261024-01` returned
`unknown/visible_focus_changed`, with Return not sent. Own target readback did not
contain the test payload. It was not automatically retried. Reserved-TTY and
wrong-PID negative checks both refused before input. Another owned test window
later disappeared; cause unproven, no fallback into another window.

Actual focus-only probes disproved that merely setting window.frontmost fixes
activation reliably. Activation/index changes can restore a different key window;
collection-derived window references also depend on changing window order. The
repair binds the parent by immutable window ID, selects the tab, and, when direct
activation still targets a different window, selects the exact unique current
Window/Fenster menu entry. Duplicate, changed, disabled or missing entries refuse.
The original frontmost-app/window-ID/TTY guard, process identity, viewport and
pre-Paste/Return checks remain. No keyboard input or clipboard access occurs in
focus-only probes. The final source focus-only probe passed on the owned window
42963/ttys000; this is not yet a passing installed-service paste test.

Only three directly related checks ran: generated insertion/Return JavaScript
compilation on macOS and task-local native identity/pre-Paste guard regression.
All3 passed. Initial formatting/import findings were corrected and only affected
lint/format checks repeated. Warm-upgrade acceptance now reads the prior wheel's
actual METADATA version and records its SHA-256 and explicit verified source pin,
so RC17→RC17 patch installation and rollback can be checked without repeating
unchanged full lifecycle tests. RC14 remains the default prior source pin.

## Confirmed ChatGPT/ThreadDesk interface diagnosis

An actual Kira/chatgpt `threaddesk.manage` appended the regular work-memory entry
`KB-RC17-INSTALLED-AND-KIRA-TD-DIAG-20261024-01`; the validated mutation receipt and
independent `get_thread` readback confirmed revision30 and the complete exact note.
There is no evidence of a historical failed write. ThreadDesk text writes are not
generally blocked.

Cached Apps tool declarations still require completion_subscription and describe
Events as mandatory. The live RC17 tools/list instead requires only request,
provides action aliases, and declares Events optional. Both identities reached the
same live daemon. The compatible legacy call with an empty subscription worked.
Already injected external Apps schemas cannot be replaced by changing permissions
or repeatedly submitting tasks. Refresh the host connector's metadata; no refresh
control is exposed in this session. The standard stdio proxy already forwards
catalogue changes. The optional Events facade lacks that monitor; this is a
possible improvement, not proof it causes this host's cached schema. No facade,
ThreadDesk, permission or production configuration change was made for diagnosis.

File transfer has separate prerequisites: absent file_transfer configuration means
enabled=false; neither current principal has files.prepare/transfer/inspect; the
active pinned ThreadDesk adapter lacks file_import_* receiver tools. Existing
sender modules are reused, not rebuilt. Text-management permission does not grant
binary transfer. No original files, permissions or receiver implementation changed.

## Follow-up: health polling and actual full-access grant

The6fd1518 package passed isolated actual Intel-macOS RC17b54→RC17 upgrade,
status/version/data preservation and rollback. Logged authenticated status pinned
the actual source package to6fd1518 (Python source fingerprint17326f87…). The
isolated launchd label was absent after cleanup. Productive installation then
reported RC17/PID51827/source6fd1518;4269 tasks,271 messages and45 handoffs,
configuration/credential hashes/modes and the prior unknown input record remained
intact. Backup: `install/backups/20261024-194038-00a3c128`.

Practical input acceptance was then blocked by repeatable terminal_read_busy on
both the direct and actual Kira queued read route. Root cause in code: each
stdio proxy polls bridge_health every second, and health performed discovery.live,
using the same bounded terminal read slots as actual foreground reads. Multiple
connections can saturate that lane. A new real-HTTP six-monitor regression failed
before the repair (two catalog probes); passive-default health now performs none.
Explicit observe_terminals=true, operation_catalog and agent_inventory still
refresh bounded observations. Cached observations keep timestamps, explicitly
are not input proof, and are discarded after permission drift. Passive polling
alone does not discover window changes. Input paths retain independent fresh guards.

Required focused checks: concurrent health/read, explicit fresh discovery, revoked
cache and reserved stop capacity passed4 cases. Independent team audit caught a
denial-status semantic issue; it was fixed, and only explicit denied/manual plus
directly related cache checks ran again (3 passed). No whole suite repeated.

The user's subsequent instruction explicitly authorizes complete ChatGPT access.
Actual policy already had automatic/full, filesystem and terminal roots `/`, any
executable, and configured agents; only files.prepare/transfer/inspect were missing.
A separate source bug used operation names as full-access capabilities, missing
files.inspect. Full selection now includes each registered operation's actual
capability, preserving existing grants and revocations. New reproduction failed
before the fix; full-capability and existing revocation checks then passed2 cases.
This fixes explicit operator selection, never self-authorizes ordinary MCP calls.
Any subsequent productive policy change is separately authorized by that new user
instruction; earlier preservation proofs correctly describe their earlier scope.

PR32 remains open: GitHub Actions annotation explicitly says jobs were not started
because recent account payments failed or spending limit must increase. No required
checks are configured according to gh, but failed/not-started controls are not
bypassed. No merge or release publication is claimed.
