# macOS system and communication modules · 31 October 2026

Revision 5, RC22 published, installed and running acceptance. Continues the completed RC21 adapter and body-only
handoff work; it does not replay historical uncertain tasks. The operator explicitly
requested the remaining system communication modules, team review and deployment.

## Architecture and operation inventory

The Python Bridge remains the sole policy, task, ownership and completion authority.
Its modular macOS provider uses one lazy, private native App worker per Core.
The worker runs the signed release-local `native/KiraBridge.app --system-operation`:
bounded serialized JSON Lines bind each request/reply to protocol, request ID,
principal, exact source commit, executable, helper PID and generation. Installed
native bytes are pinned by the release descriptor and binary SHA-256. An old or
invalid application is unavailable; discovery does not launch it to guess support.
Cancellation, timeout and parent death reap only the owned worker. No automatic
replay follows an uncertain native effect.

| Module | Operations | Contract |
| --- | --- | --- |
| System | `system.info`, `system.displays`, `system.volumes` | Public native inventory; display revision is also used by capture. |
| Processes | `system.processes`, `system.process`, `system.signal` | Public `sysctl` metadata and Security kernel-guest GUI executable paths, exact PID/kernel start token, bounded revision pages; no argument/environment reads. Signals require fresh ownership, identity, path and protected-lineage checks. |
| Permissions | `system.permissions`, `system.permission_request` | Status never prompts. A separate explicit write operation requests only AX, screen capture or notifications. The OS decides. |
| Applications | `apps.list`, `apps.inspect`, `apps.launch`, `apps.quit`, `app.focus` | Public NSWorkspace/NSRunningApplication; exact PID/start and path scope. Existing agent terminals are protected. |
| Windows | `windows.list`, `windows.inspect`, `windows.focus` | Public CG/AX inventory, target PID/start, revisions and unique AX identifier for focus. Titles are opt-in. |
| Accessibility | `accessibility.status`, `accessibility.inspect`, `accessibility.action`, `accessibility.set` | Public AX attributes/actions, secure-field redaction, principal-bound references with helper generation, target identity, TTL and revision. No arbitrary script execution. |
| Capture | `capture.window`, `capture.display` | Permission-bound, revision-checked PNG snapshots; byte/dimension/hash validation and MCP image delivery. |
| Notifications | `notifications.status`, `notifications.post` | Public UserNotifications API; task/principal-derived identifier, bounded text, no implicit permission request. |
| Preferences | `preferences.read`, `preferences.write`, `preferences.reset` | Own application domain only; typed appearance/sound/capture/window-size keys, compare/readback revision and restoration. |
| Reports | `system.report` | Fixed public `system_profiler` reports for hardware, software, storage, network, audio, displays, USB, Bluetooth, power, printers and applications. No caller command arguments. |
| Data ranges | `file.list`, `process.output` | Stable directory continuation; persisted owner-scoped byte ranges for complete stdout/stderr instead of a truncated preview. |

There are 27 native system operations. `system.report` uses the existing managed
process path with fixed executable/arguments. Native capabilities remain subject
to each principal's configured whitelist and the OS. The update must activate new
capabilities through the supported configuration transaction; merely adding code
does not grant them.

AX inspection has two different revisions: top-level `revision` binds traversal
and continuation order; each `element.revision` binds an actual mutation.
Tokens also require the same worker PID/generation and observed application start.
Window/process start tokens are kernel epoch-microsecond strings; application/AX
start identities use NSRunningApplication launch timestamps. They are not
interchangeable. The own acceptance fixture actually observed Cocoa launch
`1793469332.226911` and kernel start `1793469332.231754`; exact equality between
those two different start timestamps would incorrectly refuse a legitimate app.

## Communication behavior

Visible input remains exactly the supplied body: no automatic header, history,
ACK/reply instructions or end marker. Wrapped multiline and blank-line comparison
uses the observed full widget rendering and actual terminal columns. It never
normalizes away user whitespace or sends a speculative extra Return.

The default request for a reply may observe a completed local Codex turn through
an independently bound writer file descriptor, session header, thread, CWD and
pre-paste cursor/hash. It requires the exact new user body, final answer and turn
completion. It reports `scope=local_agent_turn`, `agent_confirmed=false`, and no
verified project/work completion. It creates neither a mailbox ACK nor a fake
reply message. Genuine authenticated mailbox responses retain priority.
Explicit `wait_for_reply=false` continues to report delivery only.
Cached local results are fully validated during recovery; malformed or historical
uncertain states are not replayed. Other agents without this independently proven
local protocol retain the authenticated mailbox path.

Process output keeps raw owned stdout/stderr separately from response previews.
Per-stream/total limits, capture failures and EOF versus completed capture are
explicit. Directory pages bind path, metadata and an order-independent namespace checksum
verified by a second scan. This detects changes within one filesystem clock tick;
it is a change checksum, not an authenticated or immutable snapshot. Output pages
are checked against the persisted complete stream SHA-256 and the same observed
range bytes, with a 64 MiB stream verification bound. A concurrent change requires
a fresh read rather than silently returning mixed data.

## Public API and compatibility limits

The minimum native target is macOS 12. ScreenCaptureKit availability is checked
and weak linking preserves startup on the minimum OS. The screenshot operation
requires macOS 14 or newer; its capability is unavailable on earlier versions. The local certification
will apply only to the actual Intel Mac used. No ARM or other-OS native pass is
inferred from compilation or mocks.

Process enumeration uses Apple's public `sysctl`/`kinfo_proc` approach, not
`libproc` interfaces marked private/unstable by the SDK. NSWorkspace supplies only GUI candidate PIDs. The path comes from the current
Security kernel guest via `SecCodeCopyGuestWithAttributes`, `SecCodeCopyStaticCode`
and `SecCodeCopySigningInformation` / `kSecCodeInfoMainExecutable`, bounded by
unchanged kernel metadata before/after. An AppKit cache never supplies that path.
These public APIs do not establish signature trust or grant execution rights.
CLI paths remain explicitly unavailable; signal control then refuses. The
read-only inventory uses the complete bounded kernel rows as an observation
interval. Before a mutation, two complete bulk observations must agree on the
target, its ancestors and entire descendant set, and worker/Core ancestry. Only
those relevant GUI paths are bound twice between the two observations. At most
three pre-effect attempts are allowed; the signal itself is never repeated. See [Apple Code Signing Services](https://developer.apple.com/documentation/security/seccodecopyguestwithattributes(_:_:_:_:)).
`kill` cannot atomically compare a kernel process-start token: the documented
guarantee is a fresh preflight followed by one positive-PID call, not a promise
that PID reuse is impossible. A signal acknowledgement is not proof of termination.

CFPreferences has no global compare-and-swap against arbitrary external writers;
its guarantee is serialized worker comparison plus readback. Known shells/agents
and their ancestry are protected using observed names and process metadata, not
an absolute identification of every renamed executable. Secure UI, SIP/TCC,
locked sessions, unsupported apps and denied OS rights can refuse operations.
The existing desktop lock heuristic is not a comprehensive public lock-state API.
The earlier missing original planning/research documents remain missing evidence.

## Verification and release gates

Current candidate evidence is private under
`~/.local/share/kirabridge/backups/system-communication-20261031T163358Z/`.
`combined-root-final-integration.log`: 244 passed. Communication targeted run:
406 passed; receiver fix run: 142 passed; independent receiver delta: 34 passed.
Those runs overlap and must not be added into a synthetic total. Native worker,
package, public process models and output/directory checks have separate checkpoint
files in that directory. Ruff and format pass across current Python sources.
Swift full-source typecheck passed; a previous development prototype is not a
final shipped-binary or running-Core acceptance claim.

The final gates below are completed. Earlier candidate findings are retained as
history, with their then-current pending gates; they do not describe the final
installed state. The detailed final identities and failure/recovery history are
also recorded in [structured evidence](evidence/system-communication-20261031.json).

## Candidate gate findings and corrections

The first clean candidate `696d38a` passed the real 18-check Codex chain and an
independent byte/turn/cleanup review. It reproduced a noncollapsed wrap rejected
by the old verifier and accepted by the corrected one. Default local reply, exact
body, blank lines, one Paste/Return, duplicate task ID, explicit Return, resume menu
and busy/stale/approval guards all passed. The private package smoke passed too.

Its actual installed isolated native worker passed own-window focus/inspection,
AX value set/button press/secure-field redaction, own-window PNG capture and own
preference write/reset/restoration. Process census churn refused the inventory,
so no signal was attempted. The fixture and worker were removed and the preference
restored. The new bounded census/Security-path acquisition addresses that concrete
pre-effect failure; real final-binary acceptance is still required.

Both Linux jobs exposed same-clock-tick directory/output tampering gaps, corrected
with namespace and full-stream content verification. Two old tests still assumed
a single Swift source and an injected managed-message header; their fixtures now
assert all four native sources and the exact original body. No failure is hidden
by weakening the relevant guard.

The first isolated upgrade stopped while starting the unchanged RC21 predecessor,
before any RC22 upgrade. A targeted fresh unique-label diagnosis then confirmed
that same RC21 code healthy. Its runner reported a redundant cleanup-stop error;
subsequent independent reads proved the exact owned label and PID absent. The
first 30-second readiness failure has no established cause. Original failure logs
are retained; the final candidate must pass a fresh real upgrade/rollback gate.
At that candidate stage nothing had been published or installed productively.

The second native run still refused AX/process operations because the entire
world PID set changed during 391–608 ms of path inspection. A subsequent read-only
diagnosis identified a terminated own `sed` and an unrelated `bash` birth/death;
all six kernel buffer calls succeeded. The fix consumes the complete kernel rows
directly. Read inventory reports its observation interval and optional path
completeness separately. Mutation guards independently compare full relevant
process projections before/after fresh path checks; an unrelated process change
can be ignored only when both complete graphs place it outside that projection.
Relevant membership, reparenting, start/UID/TTY/name/path changes and incomplete
observations still refuse before any effect. The final signal check is kernel-only
and the existing single signal call is unchanged. Public fork/exec races after
preflight remain an explicit limit. Compiled pure cases and independent review
passed; the final shipped native binary still requires its real fixture gate.

## Final product-code acceptance · F97

Product code is `f97ab1cdeebe1d06648febe685f7ebb738ca93a9`. The following
acceptance-only change does not alter any shipped Python source, any of the four
compiled desktop Swift sources, installer or build code: the synthetic fixture now
records its public NSWindow.windowNumber and the tester waits, read-only and
bounded, for exactly that owned ID. It no longer assumes an immediate singleton
CG-window list. The failed first-window assertion in run03 remains recorded.

Run04 passed all eight native stages against the managed F97 package and exact
`bc923f131efc1de41249aae93c4eebab8dcea343268a386a14fae19de3fbd2f5`
app binary: window inspection/focus, AX text/button/secure redaction, own-window
PNG, preference restoration, complete public process inventory, exact process
inspection and one TERM to the owned fixture. Fixture and worker absence were
independently checked. The synthetic fixture's preference was restored. No user
window or historical task was used. Notification status was read; no notification
was posted and no OS permission was requested.

The same F97 app was also observed in a separate launchd-parented read-only probe.
That worker reported current AX and Screen Recording grants and notification
authorization status0 (not determined). It closed cleanly and its temporary label
was removed. This is a separate actor/process-context observation, not an assertion
that the productive Core had already been upgraded.

Both Linux CI jobs for F97 passed 2688 tests/40 skips, Ruff/format and build.
Hosted Mac jobs executed zero steps due to current billing refusal. Local compiled
Intel evidence is used explicitly; no hosted Mac or ARM pass is substituted.
The packaged F97 smoke passed. The preceding complete RC21 upgrade/rollback,
fresh-install/restart/open-completion test passed for the byte-identical Python
source03bae2fd… and installer; the final downloaded F97 bundle must still pass
its own supported download/upgrade/rollback gate before publication.

The native permission and UI observations use the same Python source as the
18-check independently reviewed communication chain:144 files, canonical
path-to-file-SHA manifest hash
`03bae2fd8715d4a7581e007096bf03633f7d978d6c590aec044a026512ab3986`.
The native harness separately hashes path+NUL+raw bytes, producing
`59dab86ea7cdc854269c3ade334bba0928ab94feef360294d9719ab4f6d81524`
for those same source bytes. The algorithms are explicitly distinct.

Publication, productive installation/activation and final running-identity/data
verification subsequently passed, as recorded below.

A separate later observation found former idle shell40801 absent; a bounded
read-only check found no recorded KiraBridge `session.close` for its PID/pane.
The cause is not established. The active original Codex36878 remains with its
previous identity. A newly observed unrelated busy Terminal8818 is preserved.
The final operator report must distinguish that external-state observation from
cleanup of the positively owned fixture/worker, and must not claim every historic
original process still exists. No fixture operation targeted40801.


## Final release and productive running state

Release [v0.8.0rc22](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc22)
is published on exact product commit `f97ab1cdeebe1d06648febe685f7ebb738ca93a9`.
The branch also contains acceptance-harness and documentation-only commits; those
do not change the shipped runtime. All 15 assets were freshly downloaded after
publication and compared bytewise with local files and GitHub digests. The exact
downloaded bootstrap passed ten actual isolated checks: RC21 upgrade, configuration/
credentials/database/user-file preservation, idempotence, restart, KeepAlive,
rollback and fresh installation. An open authenticated completion read settled by
connection closure without replay. The isolated service was independently absent.

| Actual component | Identity |
| --- | --- |
| Productive launchd Core | RC22, PID73332, started `2026-10-31T19:18:46.037312Z`, instance `56196e47d725461f96f6704ae1686e8a` |
| Installed Python | 144 files, canonical SHA `03bae2fd8715d4a7581e007096bf03633f7d978d6c590aec044a026512ab3986`; each file byte-equal to F97 Git |
| Core-owned native worker | PID73364, actual parent73332, generation `235F3F03-F08F-4046-AE40-A5ABB93BA2B0`, native SHA `bc923f131efc1de41249aae93c4eebab8dcea343268a386a14fae19de3fbd2f5` |
| Visible Companion | PID73375, local start31Oct20:18:58 CET, `~/Applications/KiraBridge.app`; exact F97/native bytes and strict signature verified |
| Full Intel ZIP | SHA `550fe51f2e9a2b78c30e149da5379ab6f01345569a94d4e4aa847fa7d54a9f37` |
| Runtime tar | SHA `a79ca78943e27e8089873335c90761e99b621c44028b10646242e63606203e10` |
| Wheel | SHA `0bb0ece82e37d97d0891e774e6400e6bf5d9e42110067bc3032e43fb5df2f192` |

Installation used the supported installer in the already owned visible Terminal
8743/TTY001. Only the existing full profiles gained the new module capabilities
through supported compare-and-swap activation. This does not grant OS consent.
Actual Core-owned permission status reports AX=true, Screen Capture=true and
notifications0/not determined; no permission request or notification post occurred.
Final health confirms `maintenance=null`, dispatcher active and accepting new work.
The eight configuration files and modes were checked; exceptions are exactly the
authorized capability lists and private600 login-ticket rotation. Protected rows
remain exact:28 holds,9 unknown handoffs,23 unknown/queued jobs,70 unknown tasks,
26 associated messages. SQLite integrity is `ok`; no historical task was replayed.

The actual installed Core then started a new owned Codex in8743, verified readiness,
pasted the exact374-character German body with a blank line and129-column wrapping,
and sent one Return after `literal-widget-v3` exact-widget verification. Output
showed the expected `KB_RC22_PRODUCTIVE_20261031_01` final answer. This literal task
correctly reports `agent_confirmed=false` and `execution_confirmed=false`; it is
not a fabricated work/mailbox acknowledgement. The default local reply protocol
was independently tested in the separate18-check chain with the exact144 shipped
Python bytes; a second productive default-reply roundtrip was not claimed.
A second actual task was refused `session_busy` before input while the own shell
was running an own sleep. Only own Codex73592/proxy73622/shell58164/tab8743 were
closed. Separate absence and preservation checks retain original Codex36878,
Terminal8193 and unrelated8818, Console15308 and Tunnel25909. The older unexplained
40801 absence remains a separate observation, not an attributed fixture effect.

### Refusals and recovery retained in the final record

The first visible install refused its second visibility check before changing
current.json, launcher or service. Their prior hashes/modes and Core50602 remained
unchanged; a fresh explicit visible attempt succeeded. No rollback was applied to
that untouched RC21, which would otherwise have reverted the wrong installation.
The first capability activation reached a new Core but failed restart verification,
compensated configuration bytes and held `failed_blocked`. Supported
`operations.recover()` restored and verified the previous loaded configuration.
A new explicit activation succeeded with unchanged predicates, timeouts and effect
semantics. Its eight RPC observations include two successful health reads and six
transient `peer_connection` failures during restart. The first failure's cause is
unproven; a short verification/readiness window remains an operational limit.
No barrier was cleared with manual SQL and no unknown effect was retried.

The verified fresh private backup is
`~/.local/share/kirabridge/backups/system-communication-20261031T163358Z/productive/preinstall/`:
full database,1352 previous-release entries, old App,8 configuration files and
Git bundle/archive. The active supported code rollback point is
`~/.local/share/kirabridge/install/backups/20261031-201543-c582d365`.
It retains RC21; rollback preserves new database results and credentials. No code
rollback was required productively. The actual configuration recovery described
above was required and verified. Retained installer rollback and old App/source
artifacts provide recovery without deleting current development or new results.

Remaining limits are explicit: notifications have no OS consent/post test;
hosted MacCI could not start due billing, ARM/other OS versions are untested;
short activation readiness can require explicit recovery; public API observations
and process preflights are not globally atomic. Missing original research and the
existing lock heuristic remain evidence/compatibility limits. Core health proves
this Core and performed operations, not every configured external peer/device.

The actual connected ChatGPT app independently returned the same live Core73332,
instance/source hash and79 authorized capabilities. This is a concrete connector
health check, not proof of every external peer or every operation from that client.

The requested earlier17264-character clipboard report was written and read back
exactly. A later independent read found45 characters with a different hash; its
cause is unattributed and no unchanged-clipboard preservation claim is made. The
reviewer neither disclosed nor restored that later content. The user's requested
updated report is copied as the final separate operator step and gets its own
readback receipt outside Git; the old report remains in the private backup.
