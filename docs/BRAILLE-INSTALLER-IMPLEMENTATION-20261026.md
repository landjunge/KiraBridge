# Braille installer integration · 26 October 2026

This records implemented source, not a published release or accepted new package.
Published remains RC14; the operator's productive source remains RC17/14468ad.

## Reused modules and actual front door

- `src/kirabridge/terminal_design.py`: PR34 geometry, full Braille wordmark and
  perspective bridge, exact `#F06DB0`, bounded caller-polled point/pulse frames,
  conservative color/encoding/plain-text and static reduced-motion fallbacks.
- `src/kirabridge/install_ui.py`: human stderr presentation, a bounded owned
  frame area, prompt/error/resize priority. Decoration can use a separate owned
  nonblocking stream; human text never enters the machine protocol.
- `installer/presentation.py`: verifies all declared leaf assets before loading
  the same verified bytes. No runtime/Bridge/ThreadDesk import or initialization.
- `scripts/build_release.py`: includes renderer, presenter and visibility verifier
  in the actual versioned macOS package and its SHA-bound manifest. Linux guided
  setup remains separate and retains a safe optional static banner.
- `installer/install.py`: the real macOS front door. Both child output pipes are
  owned only with a separately opened nonblocking TTY FD. Real output completes
  and cancels our frame before forwarding; no new frame starts after a child
  prompt. Child writes retain the original overall deadline, group kill/reap and
  pipe cleanup. Without the proven writer the original pass-through/communicate
  route remains. No change to inherited terminal FD flags, timers or writer threads.
- `installer/visible_terminal.py`: optional `--require-visible-terminal` checks
  the actual frontmost visible non-minimized window, selected tab, TTY and own
  process identities before preparation and activation. The normal root-owned
  login ancestor is a boundary, not an input target or permission. Verified bytes
  are compiled without reopening after hash verification. Internal compensation
  restores the recorded old definitions even if UI focus is lost after a failed
  switch; owner/hash/idle/queue checks remain. Explicit rollback retains its check.

`--motion full` enables optional movement; `--motion reduced` stays static.
`--language` chooses the presentation language; backend diagnostics retain their
existing language. Animation runs only during actual quiet child wait time and
never delays a completed operation to finish a decorative sequence.

## Team and review

Native agents terminal_repair (renderer), whiteboard_repair (presenter/package)
and receiver_contract_audit (focused rollback plus independent security review)
worked in distinct worktrees. Root reviewed and integrated their commits, added
the actual front-door loop/visibility checks, updated DE/EN documentation and
recorded the standing team/commit/push/single-window policy in AGENTS.md.

The independent reviewer found and the implementation closed: wrong target
tab/window visibility, verified-file reopening, UI-gated emergency recovery,
stdout-based viewport measurement, blocking relay output, graphics after a
prompt and missing owned-FD cleanup. No remaining concrete blocker was found in
the read source; real package acceptance remains a separate requirement.

## Necessary scoped evidence

Root's combined changed-boundary batch: **54 passed in 3.19 seconds**, with
PytestUnraisableExceptionWarning treated as error. It covers visibility, real
owned child output/deadlines/reaping, presenter integration, package contract,
status JSON and directly affected installer/configuration safety. Ruff/format
passed. No precautionary local application-wide repeat.

Renderer phase: 32 distinct focused cases; presenter phase: incremental scoped
cases as documented by its commit. These phases overlap with integration cases
and are not summed. Early fixture failures and their directly affected retries
are retained in the working reports; they are not successful original runs.

Actual native visibility retry passed in the already existing confirmed owned
window **54294 / ttys008**, with no installation. The first probe rejected the
normal root-login ancestry; the narrow correction and its negative self-UID case
passed. All subsequent visible work reuses this window, with a fresh check before
each input. No Codex/Grok session or productive queue was used or modified.

[Native proof](evidence/visible-installer-window-20261026.json) ·
[Previous source144 local Verify](evidence/local-macos-acceptance-14468ad-20261026.json) ·
[Focused RC14 lifecycle rollback](RC14-ROLLBACK-20261026.md).

## Remaining package and release acceptance

Build twice from the clean final pinned source and compare all hashes; use the
actual artifact for the isolated package/launchd and visible-window acceptance.
Keep original failures, data-preservation checks and the recovery record. A local
Intel test never stands in for an unexecuted ARM/hosted Actions test. GitHub's
billing-blocked hosted macOS checks remain blockers; no billing or OS account
change, protective gate bypass, merge, publication or productive design install
is authorized by this evidence alone. The operator has requested those final
actions after required acceptance; this report does not claim they happened.
