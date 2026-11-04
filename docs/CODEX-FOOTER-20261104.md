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

Package, publication and actual installation results are recorded after those
steps, independently of the parser results. The regular installer must retain
its visibility, idle, backup, integrity and rollback gates. Other worktrees and
existing agent sessions are preserved. No Windows or cloud CI build is needed
for this focused Intel update.

Private raw captures and operational evidence remain in
`/Users/landjunge/KiraBridge-footer-audit-20261104/`; they are not release assets.
