# KB-CHAT-REWORK-20261104-C6D1

Follow-up to the [RC37 local Terminal repair](TERMINAL-RECOVERY-20261104.md).
The operator authorizes only the two observed browserchat failures, focused local
tests, independent read-only review, and regular local Intel installation if gates
pass. One source writer, the existing Codex primary session. The final status must
be **ready for Chat acceptance**, not full end-to-end completion.

Baseline: worktree `terminal-focus-recovery-20261104` clean at04d5e2066b7861248cda7b9adaf9ba27bf3776d5;
actual runtime RC37/59fd9d05b9a5, PID56071, instance56d0c4bdfde743bebd71ad13a8e91770.
Source bundle, protected configuration/credential hashes, process births, supplied
replay and private observations preserved under
`~/.local/share/kirabridge/backups/chat-rework-20261104-c6d1`.
Original browserchat evidence: board482f593429ad/entry478091143da3.

## Return parser

The supplied installed-code replay is independently consistent with source:
`_codex_standalone_warning_footer` recognizes the complete exact model/warning
pair, while the wrapped branch additionally applied `all(codex_input_footer(row))`.
The warning row correctly fails alone, so that redundant row check rejected the
supported group. A shared complete-group predicate now serves both assess and
wrapped Return. Continuation shape, separate blank delimiter, model-first,
unknown-dialog/activity, bound turn, PID/TTY/birth, cursor and dispatch checks remain.
Eight focused positive/diagnostic/no-new-window cases fail against the old source.
The corrected scoped selection passes210 cases, including simulated cursor-bound
one-Return/no-paste behavior and malformed/extra warnings, live turn, stale capture
and permission refusals. These fixture calls never target an actual agent.

## Shell diagnosis

An OS process observation `busy=false` proves neither an empty line editor nor
permission to clear it. The previous `suitable` false result conflated process
occupation with unconfirmed input. Now the latter reports `visible_input_unknown`,
with idle-shell/unknown-input diagnostic fields. A safe existing shell is still
used beside an ambiguous candidate. If only unknown existing inputs remain,
selection refuses rather than creating another window. The conservative exact
`empty_shell_prompt` predicate is unchanged; no trimming, deletion or Return.

Fresh read-only observations of4542/ttys001/PID51674 and4543/ttys002/PID51675 currently
show one terminal-history trailing space and pass the existing predicate. This
does not establish why the historical view contained many spaces, or prove that
such spaces were rendering rather than user input. Existing observations do not
provide authoritative shell line-editor/cursor state for that historical moment.
That limit remains explicit, and the uncertain input is preserved.

## Acceptance boundary

The existing harmless Codex draft and historical tasks are data, not new work or
permission to press Return. No local replacement client may count as a successful
Chat test. Kira will later read the existing draft fresh, issue exactly one Return
through the original browserchat route, read the actual response, then perform a
suitable focus/tab-change test. This handover itself came through native Codex
queue, not a successful KiraBridge Return.
