# RC23 continuation: scoped RC24 preflight repair · 1 November 2026

Revision 2. Preflight implementation and independent unit/HTTP review are complete.
The first physical UI run passed raw prompt/Return/response, then stopped at a
separate expanded-draft verification failure. Package, CI, publication and
installation gates are not yet attested.
The operator's verified RC22/F97 service remains active.

The shared starting point is the failed RC23 pre-paste test recorded in
[the RC23 report](RC23-RUNTIME-P0-20261101.md). Its exact historical cause remains
unproven. The later [RC22 recovery](RC22-RECOVERY-20261101.md) restored service and
Kira file/terminal discovery without replaying any historical task.

## Reproducible defects and change

Previously, exact native selection called the combined session catalogue.
An unrelated tmux read could abort a valid Terminal.app selection before input.
Exact selection now observes only the responsible transport through the existing
catalogue implementation; general discovery still combines both transports.
Authorization, current PID/TTY matching, duplicate-view detection, busy checks and
native target freshness remain in their existing owners.

Native process catalogue, process identity and shell-snapshot read timeouts, and
tmux read timeouts, previously escaped as raw TimeoutError. They now report
`session_observation_timeout` with a static responsible phase. Existing deadlines
and owned-read-process cleanup remain unchanged. A mutating tmux timeout retains
its uncertain-execution classification; cancellation is not translated to success.
No new input, Return, hidden fallback or automatic task retry was introduced.

## Independent verification

Eight targeted regressions were red before the implementation. The completed
independent cases include 23 isolation/identity/busy/timeout/cancellation tests and
two actual private HTTP tests through action_request, the regular handler and
task_get. Those HTTP tasks preserve failed/typed-phase evidence,
`terminal_input_attempted=false`, `automatic_retry=false`, `safe_to_retry=false`,
no input/Return and exactly one observed read-process spawn.

The affected suite initially reported 259 passed and one existing host-dependent
fixture failure: a capability test accidentally observed the real installed app.
Its metadata fixture is now explicitly isolated. The affected failed case and
both new HTTP cases then passed in the targeted three-case rerun.
The implementer's 117 existing selected cases also passed; overlapping counts
are not summed. Repository Ruff, format and diff checks passed.

Existing catalogue fakes accept the internal transport selector; their previous
assertions remain. Independent source and harness review found no open issues.
The P0 package harness now accepts an explicit expected version, preserving its
RC23 default and exact version/source/commit guards for an explicit RC24 run.

## Gates and continuation

RC23 already exists as a published tag. The successor candidate is RC24; neither
that old tag nor the running RC22 installation is relabelled.
The next gate is one actual isolated native/Codex run with the reviewed worktree
source, followed by exact-commit CI, artifact and upgrade/rollback acceptance.
Only then may a fresh candidate be published and visibly installed, followed by
its own actual productive acceptance and supported rollback on failure.

Private baseline, independent review, source checkpoints, prepared RC24 release
helpers and subsequent receipts are kept under
`~/.local/share/kirabridge/backups/rc23-preflight-team-20261101T123917Z/`.
The baseline source bundle was independently readable with git bundle verify.
No credentials, raw prompts, clipboard contents or private UI frames belong in
public release evidence.

## Actual physical run and newly isolated failure

`actual-ui-candidate-01` used one new owned window and a private HTTP Core,
never the installed service. Source manifest
`ab87b4159b9b84d89a27f5c23a1ee1dd532c871a83931e1561a22b88c17cd995`
passed real busy-shell refusal, stale PID refusal, Codex startup, one long literal
paste plus Return, durable completion, and an independently matched own Codex
answer in the screen and authoritative rollout.

The following new `agent.execute` case stopped with
`unknown/visible_handoff_unknown`. Its native receipt confirms one paste and
no Return; handoff events are `inserting → unknown`, reason
`visible_insert_unknown`. That uncertain input was not replayed.

Independent read-only analysis pinned the unchanged own process identities,
saved current screen and 131-column geometry. The entire requested 463-character
payload matches the forward-wrap representation. The verifier rejects exactly
one additional whitespace-only display row between the payload and otherwise
identical footer. This identifies this new failure's verification boundary; it
does not establish the cause of the historical RC23 pre-paste timeout.

The private Core was stopped. Automatic cleanup correctly refused to close a
nonempty own Codex draft. The original user window remains preserved. Controlled
cleanup and any subsequent test require fresh own-resource identity checks.
The next change must support only this narrowly bound renderer representation,
with independent negative cases; no global whitespace stripping or task replay.
