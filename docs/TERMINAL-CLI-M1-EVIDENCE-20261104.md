# M1 local evidence · 4 November 2026

Task **KB-MODULAR-CLI-20261104-M1**. This file records local evidence, not Kira's
real browserchat acceptance. See [architecture and API](plans/TERMINAL-CLI-MODULES-20261104.md).

## Reproductions and automated checks

Before implementation, focused cases reproduced RC38's unknown copy footer and
refused transcript-view Return. Current tests require distinct states and bounded
navigation. Original test output is preserved in the private M1 evidence folder.
The independent read-only review compared the retained grammar bodies against
`ef65f65`: 7 readiness, 17 rendering, 1 Return and 3 menu functions are preserved.
Its safety findings were corrected before final source approval.

Focused tests exercise short/wrapped input, warning groups, queued/active agents,
unknown dialogs, foreign/changed drafts, PID/TTY/birth and cursor changes, exact
input-buffer dispatch, task replay, lost Escape result → UNKNOWN, no duplicate
paste/Return, model exit and resumed text. The fixture adapter and import tests
check extension seams. Grok fixtures/connectors and existing isolated CLI provider
paths are tested separately from native terminal behavior.

The first broad relevant run: **523 passed, 1 failed**. The unchanged old
`test_sessions.py::test_native_open_checks_authority_and_quotes_command` fixture
provides no native window observer and assumes the former one-call create path.
It fails identically with the installed RC38 source (`base-native-open-fixture.log`).
This known baseline test-harness failure is not represented as a pass or bypassed
in product code. Current product creation/proof paths have their separate focused
tests, and the own native resource was actually created with the normal proof.
Final targeted checks: **33 passed** for new adapter/navigation and uncertainty
regressions (`review-fixes-final.log`); **237 passed** for input/Return/buffer,
geometry, window proof, tab and queue/transcript paths (`core-regression-final.log`).
These overlap the broader run and must not be summed as distinct test cases.
Whole-repository Ruff lint/format and `git diff --check` passed. The final review
pins all 24 relevant source/test files; a formatter-only change was independently
confirmed AST-identical and the pin updated. Package/install evidence follows.

## Actual Intel macOS checks

One owned separate visible window5030, TTYttys012, shellPID71567, test CodexPID71915.
It ran only a read-only test CLI in the private native workspace, using the existing
login. Nine pre-existing logical tabs were recorded at entry. During the run,
several old idle shells and later own5030 disappeared from both Terminal inventory
and process observation; their cause was not established. No script terminated
those foreign shells. Primary repair agentPID52888 retained its process identity.
Production remained RC38 during candidate source probes.

Observed directly on Codex0.166.0:

- `/status`: one command paste and one Return; fresh real status output recognized,
  then empty composer, work-state unknown without a separate protocol binding.
- `/model`: actual `Select Model and Effort` menu recognized; no Enter selection;
  one bound Escape observed the empty composer again.
- Normal text after menu exit: one new harmless local test message transferred
  and submitted once; exactly one separate answer line `M1_NATIVE_5BC2` read back.
  The task's literal result correctly did not claim an agent answer on its own.

Own5030 was also explicitly minimized, then an ordinary `/status` task restored
that exact visible target and succeeded among the existing windows. The later
read observed it unminimized/frontmost with its exact TTY selected. This is one
minimized-target case, not the entire minimized/mixed matrix.

Native copy/transcript recovery, the requested Codex focus/tab acceptance matrix,
other minimized/mixed combinations, Grok UI and a fresh real browserchat client
remain untested in this M1 record
unless a later appended observation explicitly covers them. Their parser/transport
simulations do not turn them into native passes. Old chat tests were manually
submitted, and historical UNKNOWN keyboard/Return outcomes are retained.

## Local before/after measurements

Same permissible `/status` flow, once on RC38 and once on candidate source in the
same own CLI. This counts local JXA calls and encoded JavaScript/JSON bytes only;
it is not an MCP/cloud/chat roundtrip or network measurement. The candidate also
checks semantic acceptance; the old task only claimed transport completion.
Different accumulated scrollback affects byte volume. One sample gives no speed
guarantee, and these data do not show an improvement.

| `/status` | local JXA calls | source UTF-8 bytes | response UTF-8 bytes | dispatch through final read |
| --- | ---: | ---: | ---: | ---: |
| installed RC38 | 18 | 20289 | 29308 | 12.207s |
| candidate M1 | 24 | 24842 | 47673 | 15.744s |

Counters include the initial read; timing starts after that read. This is elapsed
time through the final observation, not a precise CLI acceptance timestamp.
Production client/browser latency and data volume have not been measured here.

## Installation state

At initial documentation: production **0.8.0rc38 @ 5af2e788d48f56b39c45d4b763a76a16553df756**,
instance `8f7321700cc54e549574748bd70008d7`. Candidate not yet installed.
Only the regular local Intel package/install path may change that state after
integrity, idle, backup and preservation gates. No direct site-packages edit,
cloud build, cross-platform artifact or public release is part of this delivery.

### Completed local installation

Built **0.8.0rc39 @ d9b0c0a770ca08ec951af78b87e687bf43eeded0**, only
`Darwin-x86_64`. Archive SHA256
`49ca2ba212ee8050482982b2fc4380c68f8fc7f9b3079efc4b7ae6e30aa0a737`.
637 manifest entries verified; native app `codesign --verify --strict` passed,
ad-hoc signature, `lipo -archs` exactly `x86_64`. Regular isolated installer smoke
passed, including corrupt-package rejection and config/credential preservation.

The earlier own5030 was absent before any installer command was dispatched. One
replacement controlled shell was created. Normal open/isolate stopped before
detach at `Shared host native AX anchor changed`; that outcome remains UNKNOWN
in its private authorization store and was never replayed or rewritten. The
already-created own tab was freshly bound by its creation receipt/nonce, shell
PID/birth/TTY, empty controlled prompt and native CG/AX topology, focused, and
detached exactly once through the existing `move_created_tab`. Original current
logical/process identities were checked again. This recovered install setup;
it does **not** claim the automatic window-open isolation issue is fixed.

The regular installer then ran once in confirmed separate visible
**5118 / ttys000 / shell77256**, with `--require-visible-terminal --desktop`.
Exit0; under the install write lock: **0 active tasks, 0 receiver jobs**.
Configuration and all three protected credential/key files retained their hashes.
Rollback transaction exists at
`~/.local/share/kirabridge/install/backups/20261104-222929-f3586e24`, previous RC38.
No productive rollback was performed. Recovery uses this verified bundle's normal
`installer/install.py rollback --bundle <verified/KiraBridge> --require-visible-terminal --desktop`
in a freshly confirmed visible install terminal; never use old session IDs blindly.

Actually running daemon: **PID77711**, instance
`3f86c5948e5040fb8e8f894e3209beae`, version **0.8.0rc39**. Startup package:
`~/.local/share/kirabridge/install/releases/0.8.0rc39-d9b0c0a770ca/source/.venv/lib/python3.11/site-packages/kirabridge`.
All **185 Python files** match the built wheel byte-for-byte. Their manifest hash
equals the running daemon's startup `source_tree_sha256`:
`1cf72d9110592e317d4ffa9be1b8c26106d09e57cd1e06c5c48dfb730237f46a`.
The native provider also reports source `d9b0c0a770ca…`; this is more than a tag or
package-version assertion. Current operation discovery exposes the Escape schema.

After install, `terminal.visible` task
`kb_m1_rc39_runtime_shell_20261104_f03b` completed attempt1/exit0 in own5118.
Exactly one standalone output `M1_RUNTIME_OK_F03B` was read back. The separate
wrong-PID task `kb_m1_rc39_wrongpid_20261104_f03b` was rejected as
`session_selection_changed`, `started=null`, before input. Both completion notices
were processed and acknowledged. This is a local installed-service test, not Kira
browserchat acceptance. Original RC37/RC38 failed Returns and the keyboard UNKNOWN
remain in the productive task history unchanged.

Finally own5118 was closed only after empty-input/idle/process/native isolation
checks. Independent logical/CG absence and shell process exit were observed.
Current foreign tabs4543/ttys002 and4740/ttys008, including mainPID52888, retained
their identities across installation and own-window cleanup. No owned test CLI,
installer or test window remains running. Earlier disappearing shells were not
recreated. Raw account-bearing status captures remain private.

**Status: bereit zur Chat-Abnahme.** Kira must use fresh handles/cursors from the
actual browserchat for new unique-marker, Copy/Transcript, `/status`, `/model`
exit/resumed-text and appropriate focus/tab tests. The local source probes and
post-install shell test do not substitute for those acceptance steps. Native Grok
and the outstanding window-isolation/old fixture limits remain explicit.

Sanitized [machine-readable installed evidence](evidence/terminal-cli-m1-installed-20261104.json).
