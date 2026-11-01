# RC23 continuation: scoped RC24 preflight repair · 1 November 2026

Revision 4. Preflight implementation and independent unit/HTTP review are complete.
The first physical UI run passed raw prompt/Return/response, then stopped at a
separate expanded-draft verification failure. Package, CI, publication and
installation gates remain unsatisfied. Exact-code CI has passed.
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

## Bound cursor-row model

The installed CLI identifies itself as Codex 0.166.0. Its official tag resolves to
commit `6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`.
The pinned [textarea wrapping implementation](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/codex-rs/tui/src/bottom_pane/textarea/wrapping.rs#L178)
adds an empty cursor insertion row at every full logical-line end. The fixed
composer bottom margin is separate. This explains the observed 128-cell final
row at a measured 131-column terminal.

An independent private execution of that unchanged wrapping algorithm confirms
five text rows for the recorded payload, six if a real newline is appended,
and a nonempty final row if a real space is appended. The initial arbitrary
spacer hypothesis is therefore superseded by a defined forward-rendering rule.
The original ambiguity report and failure evidence remain preserved.

The proposed central payload forward renderer modelled that insertion row only at the
maximum measured text width, `columns−3`. The optional narrower scrollbar width
had no such extension: without independently bound scrollbar state, its cursor
row can be confused with real extra input at the wider width. The existing
bounded simple-text and actual-softwrap restrictions still apply.
Footer comparison, including every remaining row, is unchanged.

The saved real draft is recognized with its measured 131 columns, and refused
without geometry or at the ambiguous 132-column interpretation. The implementer
passed 129 existing selected cases; independent boundary verification and a new
physical run must complete before this second repair is considered accepted.

The first own test Codex and its observed child were terminated with individually
pinned PID/start/TTY/image identities and SIGTERM only. No keyboard input or
uncertain prompt was replayed. The own shell/window was confirmed idle and
retained for reuse; the original user window remained present.

## Review stop and preserved development state

Independent boundary tests of the proposed cursor-row extension passed 25 cases
and failed one relevant extra-space case. The additional newline is distinguishable
under the pinned forward model, but an extra space on the empty row is not yet
independently proven distinguishable from the display serialization.
The two-line extension is therefore not approved, committed, published or installed.
Its exact patch, source and new regression file are preserved outside the worktree
in `cursor-row-unapproved-work/`, together with the failed review evidence.
The working source is restored to the reviewed preflight implementation.

Bounded public Terminal/System Events metadata probes did not yield a safely
bound caret observation. Some ended with AppleEvent error -1728, and later
observations found no live owned shell. These observations do not prove that
Terminal offers no caret attributes. No focus, keyboard input or permission
request was used to obtain a cursor observation.

Code commit `a42fbc57023ef553388ce2f5524db4648ac0df94` is pushed on
`fix/rc22-runtime-p0-20261101`.
[Verify 41308573003](https://github.com/landjunge/KiraBridge/actions/runs/41308573003)
completed successfully with all four actual jobs: Linux Python 3.11/3.13,
macOS Intel and ARM. This verifies the preflight change, not the failed UI gate
or the unapproved cursor-row proposal. No new release or package is claimed.

The operator then prioritised a working installation. The existing RC22/F97 was
confirmed through its supported visible installer, and its previously stopped
ChatGPT transport was restored under the standard service label.
See [the current installation record](WORKING-INSTALLATION-20261101.md).
