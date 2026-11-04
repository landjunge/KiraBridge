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
login. Primary repair agentPID52888 and all nine pre-existing logical tabs were
preserved. Production remained RC38 during candidate source probes.

Observed directly on Codex0.166.0:

- `/status`: one command paste and one Return; fresh real status output recognized,
  then empty composer, work-state unknown without a separate protocol binding.
- `/model`: actual `Select Model and Effort` menu recognized; no Enter selection;
  one bound Escape observed the empty composer again.
- Normal text after menu exit: one new harmless local test message transferred
  and submitted once; exactly one separate answer line `M1_NATIVE_5BC2` read back.
  The task's literal result correctly did not claim an agent answer on its own.

Native copy/transcript recovery, actual tab regrouping, minimized/mixed windows,
Grok UI and a fresh real browserchat client remain untested in this M1 record
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
