# Codex footer correction · 4 November 2026

The operator authorized push and installation after the read-only investigation.
This is a focused RC34 correction, based on main `ad6b458`, for Codex 0.166.0.
The distinct RC33 generic `keyboard_unsupported` issue remains unresolved.

## Verified cause

`windows_installer_prompt_1104` (1014 characters, RC33) and
`kb_merge_team_prompt_20261104` (1078 characters, RC30) both pasted successfully
enough to display `[Pasted Content N chars]`, then stopped before Return with
`exact_widget_mismatch / visible_insert_unknown`. The complete text is not
recovered from this count display and application processing is not claimed.

The saved capture texts match the original tasks' before/after verification
SHA256 values exactly. Before paste, the final row contained the shortcut hint
and F2 warning. After paste, the hint disappeared and the same warning remained
at the same column. The literal verifier only normalized badges on the GPT row;
the shortcut remover required a bare hint. Return's footer grammar rejected the
standalone warning too. These three parser files were byte-identical in the
installed RC30 and RC33 releases; the upgrade did not introduce this mismatch.

`windows_installer_enter_1104` failed before input with `visible_target_unknown`
after the cursor, pane, shell/agent PID and unchanged-screen checks. The stored
cursor selects the affected capture. Its exact internal protocol observation
was not retained; this is not proof of a lost OS identity.

`kb_merge_return_newline` used generic `keyboard.control` for Terminal and was
refused by `macos_terminal_route_required`. The separate `session_busy` start
attempt followed a `session.open(argv=["codex"])` which had already launched
Codex. Neither is repaired by weakening target guards.

## Change and validation

The new literal exception requires the same exact payload representation,
all unchanged prefix/footer rows, the same warning text and absolute warning
column, and the exact known shortcut-to-warning transition. Arbitrary added
standalone rows are not discarded. Readiness additionally recognizes exactly
one model row followed by one supported standalone warning row. Active turns,
unknown dialogs, changed captures and target identities remain blocked.

208 distinct focused cases passed across `test_literal_session_input.py`,
`test_visible_readiness.py` and `test_session_return.py`. Two new integration
fixtures initially used an incomplete ready pattern; after fixing only those
fixtures, those two cases passed. Existing negative cases were not changed.
Ruff, formatting and diff whitespace checks passed on the changed files.

An independent replay against the original hash-matched captures passed both
literal verifications and cursor-draft readiness with an explicit idle protocol;
the working protocol remained blocked. No historical task was resubmitted.
This replay is not a fresh native input or an agent acknowledgement.

Wrapped multiline drafts with standalone warning rows remain outside the new
positive contract. Thread changes within an unchanged OS process, historical
binding refresh failures and `session_window_unconfirmed` require their own
concrete observations; this patch claims no general repair for them.

## Delivery

The operator subsequently expanded the request to the entire slow/blocking
input chain and reliable window/tab control after restart or a new chat.

The latest concrete Notes series used seventeen separate keyboard.control
requests: 57.598 seconds overall, 7.086 seconds summed within tasks, 50.512
seconds between tasks (87.697%). This does not isolate model, network and
transport components from one another. The Apps tool view lacks the dedicated
keyboard_sequence export and carries older descriptions, although the backend
and direct connector provide it. The existing generic action_request route is
now explicitly documented and tested as the compatible batching path.

Sequence application catalogues fall from N to one; fresh native inspections
and key mutations remain N. PID/start, immutable app identity, active focus and
per-step authorization are checked; subsequent steps never refocus a different
application. An actual HTTP/MCP regression with a simulated legacy catalogue
posted eight simulated physical key pairs in one durable task, with eight fresh
inspections and one catalogue. Repeating the same request posted nothing.

Seven historical session.open tasks were unknown; five failed the exact
pre/post host-layout comparison. Their original geometry values were not
retained. A positive identity proof replaces that geometric equality: unchanged
AX anchor and ordered original radio partition, unique baseline host-CG
association, exact preservation of every unrelated CG ID/bounds and complete
current surface accounting. Current AX/CG geometry stays coherent and remains
the reference for unchanged guarded detach/postchecks. No guessed pixel
tolerance is used. Reflow/resize positives and substituted/extra/ambiguous
surface negatives passed; the cause of each historical geometry change is not
retroactively claimed. New bounded diagnostics preserve the next refusal's
classifier or geometry proof without screen text or window titles.

Final focused validation comprises 317 distinct cases: 208 literal/readiness/
Return cases, 56 keyboard/legacy-route cases, 29 window/diagnostic cases,
22 persisted-binding/tab/receipt cases, and two new captured-cursor Bridge-reopen
cases. Same-principal cursor reuse with unchanged freshly checked process
identities returns once; changed agent identity posts nothing. These persistence
tests simulate OS observations and do not constitute a full native new-chat
matrix. No full suite, cloud CI or Windows build was run.

Package, publication and actual installation results are recorded after those
steps, independently of the parser results. The regular installer must retain
its visibility, idle, backup, integrity and rollback gates. Other worktrees and
existing agent sessions are preserved. No Windows or cloud CI build is needed
for this focused Intel update.

Private raw captures and operational evidence remain in
`/Users/landjunge/KiraBridge-footer-audit-20261104/`; they are not release assets.

## Published and installed outcome

RC34 is published at [v0.8.0rc34](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc34),
package source `1a57394e8250679f7b1af7598d5fae4c41c66152`. All ten uploaded
assets matched the final build and GitHub digests. The published Intel installer
and runtime archive were independently downloaded and SHA256-matched. The
earlier source-only RC34 draft was never published or installed.

The regular desktop installer ran once in a confirmed separate owned Terminal
window, 15:24:25–15:24:46 UTC, exit 0. Core 37967 is actually running RC34,
instance `93839d0cff304feead3d04f93b8159ff`; all 174 imported Python modules
match the published wheel. Native-app source pin, manifest bytes and strict
signature match. Four config/credential file hashes and all 11 protected
Terminal process identities were preserved. The ordinary rollback backup is
`~/.local/share/kirabridge/install/backups/20261104-162427-c2a15014`.

A fresh postrestart `terminal.visible` command in that same own pane completed
with exit 0 and output `KB_RC34_POST_RESTART_INPUT_OK`, with visible-window and
TTY confirmation. It took 15.342 seconds inside the persisted task, including
11.710 seconds from acceptance to running. This proves correct routing/input
after the service switch, not acceptable latency for every terminal operation.
The original unknown tasks remain unchanged. Only the owned idle install
window was closed; its absence and all 11 protected identities were checked
independently. No cloud CI or Windows build/installation was performed.

[Machine-readable delivery and preservation evidence](evidence/rc34-delivery-20261104.json).
