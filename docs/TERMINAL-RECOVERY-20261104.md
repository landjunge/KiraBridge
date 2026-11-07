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

## Installed RC37 acceptance

Source `59fd9d05b9a5ba831da05bb8b14769d1517bc85a`; regular local Intel build,
archiveSHA256 `7167d78ae83230c3b4a08debbcc243f7e4c9c41305fe54710bc6f5162db20710`.
All619 bundle manifest entries and strict native signature verified. The regular
isolated package smoke verified authenticated dispatcher/source identity,
corrupt-package rejection and configuration preservation. The visible production
installer ran once, including desktop upgrade, and exited0. Its rollback snapshot
is `install/backups/20261104-194846-41ed7a41`.

Actual final production: **0.8.0rc37, PID56071**, instance
`56d0c4bdfde743bebd71ad13a8e91770`, source package under
`install/releases/0.8.0rc37-59fd9d05b9a5/source/.venv/lib/python3.11/site-packages/kirabridge`.
Startup package fingerprint:
`24e7edc963212929b3c63cb7f7ca1f8d2f6bfd9b4a0f5cb789f03466a57dd8ba`.
All186 wheel package files match the installed bytes; desktop and installed native
binary are identical and source-pinned. The service accepts new work.

| Native macOS case on installed RC37 | Result |
| --- | --- |
| Fresh MCP stdio connection, two own merged tabs, resize/reflow, switch4962→4914 | Completed/attempt1/exit0; test process confirms TTY011, native foreground and CG4914 |
| Switch back4914→4962 | Completed/attempt1/exit0; correct TTY012 and CG4962 |
| Own two-tab window minimized among other existing visible windows | Exact requested target restored before execution; completed/attempt1/exit0, TTY011 and visible CG4914 |
| Separate visible own single-tab window after closing test tab4962 | Completed/attempt1/exit0; correct TTY011 and visible CG4914 |
| Actually occupied own tab (bounded20s sleep) | session_busy, started=null, terminal_input_attempted=false |
| Own handle with another own tab's actual PID | session_selection_changed, started=null, terminal_input_attempted=false |

Each successful helper creates its execution record exclusively, records its real
TTY and observes native CG visibility during execution. Matching returned output,
exit0, attempt1 and durable completion/acknowledgement are retained. Independent
final history read counted the initial harmless printf output exactly once and
found neither rejected negative marker. No UNKNOWN request was repeated. One RC37
test-harness run accidentally reused an old idempotency key; the explicit
not_submitted/accepted=false/started=false conflict was preserved, corrected in a
separate fresh-client run with a new key, and never counted as a product pass.

Both own tabs4914/4962 were closed only after idle-shell/process checks. Independent
catalogue and CG reads confirm absence and preservation of the original nine
logical IDs/TTYs, original Terminal/Codex process births and all four protected
configuration/credential hashes. Final visible CG IDs are the original4542/4740.
No foreign sessions were ended. No cloud build or new API billing was used.

Native untested scope remains explicit: entire desktop with all foreign windows
minimized, other Spaces/fullscreen routing, a new browser/voice ChatGPT conversation,
and live Codex/Grok prompt handoff/Return. The fresh-client test is a real MCP
connection, not a simulated chat.123 source regression cases are simulations, not
native GUI acceptance. Existing historical focus-only/nonce startup observations,
the catalogue's estimated geometry-group count and exhausted diagnostic metadata
capacity are not claimed fixed by this focused change.

Readme DE/EN download links remain on the existing published RC36; RC37 is a local
candidate, with no new public release or website deployment. Installer entry and
permissions are unchanged. This report and the linked machine-readable
[evidence](evidence/terminal-recovery-rc37-20261104.json) document the tested local
installation independently of later documentation-only commits.
