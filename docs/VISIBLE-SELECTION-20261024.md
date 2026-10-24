# Current visible-agent selection / Aktuelle sichtbare Agentenauswahl

Unreleased repair, based on `a813f08`; no production installation/configuration or
OS permission changed. Queue repair is preserved, not reimplemented.

## Cause and implementation

A freshly catalogued `session.input` target was still compared only against the old
operator-persisted agent PID/window. Agent restart or a newly selected native window
therefore failed with `visible_target_changed`, even when the request explicitly
selected its current handle. RC16's root-login/user-shell repair alone did not solve
that stale agent-binding condition.

- `session_manager.py` derives an ephemeral binding for the explicitly requested
  current window/TTY/shell PID/unique agent PID. It never writes a global/default
  assignment. A changed agent generation drops the old Codex rollout/thread pin.
  Old uncertain handoffs remain immutable; automatic delivery does not follow a new
  process/window. Missing/ambiguous targets fail closed.
- Selection authority is bound to `asyncio.current_task`, not merely a copied
  ContextVar. An inherited child context is rejected; no guard-less fallback.
- Native process capture validates UID/TTY/PPID and raw process image against the
  selected catalogue row; start time and complete identity are pinned. The native
  dispatch rechecks these observations, then selected focus/tab and the unchanged
  current viewport immediately before Paste/Return. `comm` is an OS observation,
  not binary signature validation or cryptographic agent identity.
- `visible_handoff.py` checks readiness again before Paste. Return additionally
  requires the original inserted marker/prompt, and explicit unsubmitted reconciliation
  uses its original binding and the same guards. It never creates a fresh paste.
- `terminal_app.py` freezes at most 8192 Unicode codepoints; JavaScript uses
  `Array.from` so astral characters match Python slicing. Focus errors contain only
  frontmost/window/TTY metadata. Existing user input/activity causes refusal, not a
  silent retry or alternate target. Clipboard preservation remains intact.
- Catalogue metadata separates `agent_candidate`, configured binding freshness and
  `agent_activity=not_probed`. Terminal.app `busy` means process presence and is not
  declared proof that an interactive coding agent is currently working.

## Executed checks / Belege

90 directly affected handoff/selection tests passed after the reviewed guards.
After raw image comparison was tightened, only the three affected catalogue/capture
cases were rerun: 3 passed. Unicode snapshot semantics also executed in the actual
macOS JavaScriptCore engine without GUI actions. No full suite was run.

One native probe on macOS 15.7.4 Intel x86_64 created a separate **owned interactive
head fixture**, not a coding agent or user task. It proved stale-process rejection
before Paste and changed-widget rejection before Return. The subsequent allowed
Paste was refused by the focus guard. The positive native input test is therefore
**NOT PASSED**, and final-source positive native acceptance remains outstanding.

A later non-input diagnostic refused its prerequisite; an exact read-only observation
then showed Terminal frontmost but another window (30575) ahead of the owned window
37925. This establishes an actual later focus mismatch, not the precise cause of the
first refusal. No guard was weakened and no user window was refocused for a retry.
The own waiting fixture was independently reidentified by exact window/TTY,
private output FD/inode and immediately repeated UID/start/parent/image identity;
only that head process was terminated and its now-idle single-tab window closed.
No user process was stopped. Evidence: [JSON](evidence/visible-selection-20261024.json).

## Deliberate limits

A process name is not an authenticated agent identity. Only a later independently
validated KiraBridge principal receipt can attest acknowledgement; viewport/OS
observations alone do not attest execution or project completion.

Grok widgets without a supported current renderer and Codex history without reliable
bound lifecycle evidence can remain `unknown`. This repair does not loosen those
conditions merely to report an idle window. Actual Codex/Grok restart and positive
native input acceptance are not claimed from unit mocks or the head fixture.

Reproduce the narrow native fixture only in a controlled GUI session using
`scripts/accept_visible_selection.py --root <new-private-test-directory>` through
the development interpreter. The script persists fixture identity/FD evidence before
input and preserves a still-busy changed fixture on failure. Do not rerun unknown user
handoffs or change productive permissions to make the test pass.
