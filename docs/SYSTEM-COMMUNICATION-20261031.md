# macOS system and communication modules · 31 October 2026

Revision 2, RC22 candidate. Continues the completed RC21 adapter and body-only
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
CLI paths remain explicitly unavailable; signal control then refuses. A changing
PID census allows at most three read-only snapshot acquisitions before any effect.
A signal itself is never repeated. See [Apple Code Signing Services](https://developer.apple.com/documentation/security/seccodecopyguestwithattributes(_:_:_:_:)).
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

Remaining gates at this revision: final independent integration review, real
owned native fixture and Codex reply acceptance, exact clean-commit build,
upgrade/rollback and fresh release-download checks, publication, visible supported
installation, capability activation, running identity/data/session verification
and owned-target cleanup. The previous verified productive RC21 remains installed
until these gates succeed. Actual release/runtime results belong in the later
revision and structured evidence, not in advance success claims.

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
No candidate has been published or installed productively at this revision.
