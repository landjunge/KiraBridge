# Terminal recovery on Intel macOS · 4 November 2026

Scope: the operator's single Terminal repair request. Previous chain evidence:
[RC34–36 report](TERMINAL-KETTE-20261104.md).

Initial production was verified RC34/1a57394, PID37967. Terminal had restarted;
old task/window/process identities were not reused. Relevant four worktrees,
tracked and untracked changes, all Git refs and protected file/process identities
were preserved privately at
`~/.local/share/kirabridge/backups/terminal-recovery-20261104T183047Z`.

The existing published RC36/d4aebdd package was reused after fresh verification
of all615 manifest files, native signature and51 scoped tests. Direct authorized
CLI execution created exactly one own tab. Its logical window was initially
merged into a foreign physical container. After the own shell initialized,
its nonce was tagged and independently observed in CG; one exact own-tab
Window-menu detach created a separate CG/AX surface. No foreign terminal was
closed or used for input. The regular installer ran once with
`--require-visible-terminal --desktop`, passed its backups/idle/integrity gates
and exited0. Live RC36 PID53753, all186 installed wheel files, desktop source,
four protected config/credential hashes and Terminal/Codex identities verified.

Native RC36 acceptance passed a single-window printf with exactly one visible
marker, exit0 and durable completion. An explicitly selected minimized own target
was restored before execution: the test process itself confirmed its TTY,
frontmost/selected target and on-screen CG surface. This was a mixed scene with
other existing visible windows, not an all-windows-minimized native test.

A genuinely fresh MCP stdio client then switched between two own tabs in the
same physical window. Task `kb_accept_freshclient_tabswitch_20261104` stopped
UNKNOWN/visible_input_changed before the test's execution marker existed.
The new tab bar changed rows25→24; activation changed raw history padding.
The old task remains UNKNOWN and was not retried. RC36 was therefore insufficient.

RC37 corrects focus/screen ordering in the existing confirmed shell path. It
preserves initial nonempty-input refusal, exact UID/TTY/PID-birth checks, full
image/parent/CWD checks where required, the physical-ownership callback, and raw
screen equality. The authoritative baseline is captured after focus acquisition;
final dispatch only verifies focus and never reacquires it. Independent review
and final tests/package/native installed evidence are recorded below as completed.

Fresh native observations also show an unrelated logical group absent from CG/AX;
it is not proven minimized. The catalogue's geometry-group count is not proof of
physical visibility. That group was preserved and never selected for this work.
Historical focus-only and shell-startup nonce races remain bounded observations,
not additional changes or a claim of universal Terminal behavior.

Prepackage verification:123 focused tests passed on the changed source (new
persistent reflow scene, shell input, actual generated dispatch, creation,
minimized anchors, current buffer, visible selection and installer visibility).
Ruff lint/format and diff whitespace checks passed. Independent read-only review
found no blocker. A fresh native candidate dispatch switched from own4962 back
to own4914; the test process recorded the correct TTY, selected/frontmost target
and on-screen CG4914, exactly once. This candidate check is not an installed
RC37 claim. Source and installed acceptance are pinned separately below.
