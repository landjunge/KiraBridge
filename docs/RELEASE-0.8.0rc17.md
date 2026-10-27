# 0.8.0rc17 · Intel macOS

[Actual release status / tatsächlicher Release-Status](https://github.com/landjunge/KiraBridge/releases).
A GitHub draft remains unpublished. Final assets, source commit, SHA-256 and installed
service acceptance are recorded separately in the release and associated PRs, never inferred from a tag.

## Änderungen / Changes

- Retains integrated RC15/RC16/main functionality, native provider adapters,
  guided setup, durable tasks, queue recovery, workflow stop, knowledge and
  optional ThreadDesk integrations. No production policy replacement.
- Preserves explicit visible-input/window/TTY/PID/focus safety, paste-only
  submit=false, current tool discovery and long Whiteboard contracts.
- Repairs native textual team-result queue catalog parsing and coalesces
  repetitive health diagnostics while retaining core audit and limits.
- Adds explicit unknown withdrawal separate from execution reservation, plus
  retirement only for proven vanished original targets. History stays; no fake
  stop/completion, blind repeat or interruption of current agent sessions.
- Reuses PR34's complete Braille KiraBridge wordmark/perspective bridge with
  exact#F06DB0 palette, lighter pink and white highlights. Bounded optional
  point/pulse animation, static reduced-motion and color/encoding/text fallbacks.
- Packages one stdlib renderer and hashed presenter into the actual versioned
  installer. Human output stays on stderr; MCP, statusJSON and daemon remain clean.
- Optional explicit visible installation guard checks current front window,
  selected tab, TTY and process identities. One owned work window is reused.
  Automatic recovery retains old-definition/ownership/idle guards even if
  visibility is lost after a failed switch. launchd remains window-independent.

## Terminalreparatur / Terminal repair · 27 October

The targeted repair adds guarded single-line paste without Return to confirmed empty
Terminal.app shells. Existing CLI-agent widget routes remain separate. UID, PID,
process start, parent/image, full TTY process set, busy state, focus, screen and
clipboard guards remain active. CR/LF/CRLF process output is normalized for matching;
only the effective text after the existing release policy is checked for controls.

Input intent is journaled after Python preflight at the transport boundary.
A confirmed earlier refusal becomes `failed`; possible transport remains `unknown`,
without automatic replay. Exact owned released buffers are reserved once in an
accepted/running task; no authorization or production-policy change.

47 targeted adapter/session cases,21 dispatch/buffer cases and3 combined integration
cases passed. Actual isolated Intel native paste-only/readback, no-Enter output check,
stale-PID rejection and a separate21-byte execution receipt are recorded in
[Terminal repair evidence](TERMINAL-CONTROL-20261027.md). Original setup/receipt timing
failures remain visible. These tests do not establish actual voice-Host or live
Codex/Grok input acceptance, final deployment or release publication.

## Native cleanup follow-up · 27 October

A separate bounded PID-only cleanup path drains stdout/stderr even when a worker's
exit code is already set. Desktop, Terminal.app/native process probes and tmux clients
use only their own created process handle; the existing process-group mode is unchanged.
Cancellation and read-versus-uncertain-write semantics are preserved. Fourteen targeted
Intel cases passed, including one real paused-pipe child and no group signal.

[Detailed history and final outcome](TERMINAL-CLEANUP-20261027.md): the original
RC17/1cc probe remained accepted until an explicitly authorized service-only recovery;
its historical state is now `unknown`/dispatcher_restart and it was never replayed.
The initial readiness deadline failed; later independent reconciliation confirmed recovery.

PR46 is normally merged as main `fde9d87a36ed6c0bdab4456c3c8812d0378d7fcd`.
Two final builds reproduce the same hashes,375 manifest entries verified; actual isolated
1cc→fde→1cc upgrade/rollback preserved data. The final authenticated copy command passed
in isolation, then fde was visibly installed in the same own window69741/ttys003.
Responding daemon PID28646, configuration/credentials retained, rollback backup recorded.
Actual deployed operator-MCP task `kb-terminal-installed-fde9d87-paste-20261027-01`
completed once with submit=false, return_sent=false and execution_confirmed=false.
Independent current-line readback matched exactly once, with no receipt before Return;
a separate explicit Return produced16 exact bytes, SHA256
`bc5e5a02a36ccb902bfd4c5f914689332de26f0d13ee2948a9ece79a3b6e3a48`.
Whole-screen and early-file-existence harness failures remain recorded; reconciliation
was read-only, without another paste or Return.

**Window closure remains blocked:** unrelated unsent `printf KIRABRIDGE_TEST_OK`
appeared after the receipt. `visible_input_not_empty` correctly preserves it pending
operator choice. No closure or daemon-after-this-window-close success is claimed.
[Sanitized final installation/input evidence](evidence/native-cleanup-installed-fde9d87-20261027.json).
Debian PR/main CI each report1683passed/16skipped on both Python axes. Hosted Mac jobs
never started because of billing; ARM and actual voice-ChatGPT Host remain untested.
RC17 remains a draft. These results do not prove input into existing Codex/Grok sessions.

## Nachweise und Abnahme / Evidence and acceptance

Historical full Intel baseline: macOS15.7.4 / Python3.11.15, program source20a30e8:
**1609 passed,1 skipped**, Ruff/format, wheel and sdist passed. Actual built package:
**9/9 RC14 lifecycle checks passed**, including data retention, idempotency, installer-exit
independence, restart, KeepAlive, actual rollback and fresh launchd installation.
Native full Braille/pulse rendering and the authenticated isolated copy flow are proven.
Temporary test service was removed; production data/config/credentials were unchanged.

The operator explicitly approved local Intel acceptance for merge and visible installation.
Hosted Intel/ARM jobs did not start because of account billing/spending restrictions;
this approval does not claim green Actions or ARM acceptance. **Apple Silicon and macOS26
remain unverified.** The historical baseline and the new targeted terminal result remain separate;
the final merged source and new package hashes must be checked separately.

[Detailed evidence/approval](INTEL-ACCEPTANCE-20261026.md) ·
[Historical rollback failure and subsequent passes](RC14-ROLLBACK-20261026.md) ·
[Partial-write fix](BRAILLE-PARTIAL-OUTPUT-20261026.md).

## Installation / Update

Python3.11, uv0.11.6, authenticated private GitHub access and Internet required.
Actual tested OS is Intel macOS15.7.4; older macOS/iMac2015 and arm64 need their
own evidence. No Apple signing/notarization; no permission or billing changes.
Config, credentials, rights, Whiteboards, database and user files are preserved.

[Deutsch](INSTALL-DE.md) · [English](INSTALL-EN.md) · [Current status](../README.md).
Use the README authenticated checksum-verified RC17 command. The release identifies
the exact final source; historical source-pinned review assets remain historical evidence.
