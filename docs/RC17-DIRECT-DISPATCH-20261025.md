# RC17 direct dispatch repair · 2026-10-25

This repair replaces the core task and addressed-message execution queues with
bounded, immediate admission. Durable SQLite records remain execution journals,
idempotency receipts, review requests and inbox history. They are never polled for
new core execution. Optional team-domain work and webhook delivery are separate
features; their existing records are preserved.

## Contract

* `task_submit` requires a running dispatcher. It returns `accepted` immediately or
  `execution_busy` / `dispatcher_unavailable`; no task is saved for later execution.
  Manual review remains `created` until the operator approves the exact request.
* Local CLI and console approvals forward the original ID/hash to the authenticated
  running daemon. A different daemon without `dispatch_mode=direct` is refused.
  The historical CLI `enqueue` spelling now performs immediate execution.
* Addressed CLI-agent messages attempt delivery once. `message_send` and
  `message_release` observe that attempt for at most 30 seconds. Observation timeout
  is `delivery_observation.state=unconfirmed`, `automatic_retry=false`; read the same
  message ID. Failed or ambiguous input never causes a replacement message or task.
* Exact repeat requests read the original durable result. Different content with the
  same idempotency key is rejected. `unknown` is never automatically repeated.
* On startup, demonstrably unstarted legacy core backlog is archived as cancelled.
  A misleading `queued` label with claim, receipt, handoff or execution evidence
  becomes unknown. Interrupted
  admitted/running work becomes unknown. Content, old evidence and receipts remain.
  The old queue-control restore action refuses to recreate an execution queue.

## Safe session and window lifecycle

Messages may include an exact `session` reference from a fresh catalog. Without one,
a still-valid configured binding or exactly one current agent candidate is required.
Multiple candidates return `visible_target_ambiguous`. Existing unknown handoffs keep
their original immutable identity and evidence; a new exact request may use a fully
separate verified resource without rewriting or replaying the old handoff.

Window opening first reuses an exact free shell with empty input. An idle candidate
must contain exactly its expected shell process, no Codex, Git or other user process.
An in-memory lease prevents two operations selecting the same shell. New creation is
serialized and requires the existing one-shot window authorization. Uncertain prior
creation/closure blocks further creation rather than multiplying windows.

Only windows proved newly created by this bridge enter its ownership journal. Cleanup
survives restart, requires a finished owner, any exact private command receipt, matching
UID/TTY/process start time, idle shell and empty input, and preserves captured output.
It closes only a window containing its single owned tab, then independently observes
its absence. An uncertain native close is never automatically retried. Reused user
windows are never adopted or closed.

## Persistent file-transfer activation

The installed RC17 config had no `[file_transfer]` section, so the deliberate safe
default `false` applied. Activation is an explicit owner configuration, preserved in
the user's config across restarts/updates; the package default stays permission-safe.
`file_transfer.configuration.enabled_text` preserves other settings and source-host
grants. The live config permits only the existing Library export root and nine
selected ThreadDesk projects, with no blanket source-host grant.

Before mutation, private config and consistent SQLite snapshots were saved. Five
demonstrably unstarted legacy messages were withdrawn through existing CAS controls,
including `038cb63d-bceb-4f2e-865b-ec8a7fcf4aff`. No live agent process was stopped.

Two controlled restarts of the existing installed package confirmed persistent
`enabled=true` and successful authenticated inventory, each with zero registered
sources/transfers. This inventory is not a census of the 275 ChatGPT Library items.
The ThreadDesk receiver source is pinned to an immutable archive of main `770bbc9`.

## Native evidence and limits

Private evidence: `~/.local/share/kirabridge/repair-rc17-20261025/`.
No credentials or private config snapshots belong in this repository.

* One owned controlled test window persisted across a private-core restart. Its
  missing/unsafe receipt was initially refused. The same fixture was resumed; no
  replacement windows were created. Terminal's supported single-window close call
  then succeeded; fresh catalog confirmed absence and preservation of other panes.
* Two subsequent native printf tasks completed with exit 0 in the same existing
  free shell. `create_if_needed=false`; catalog confirmed no new windows and all
  original panes preserved. See `native-lifecycle/native-reuse-result.json` and
  `native-close-result.json`.
* Neither active Codex session received test input. The requested default selection
  between two sessions remains unanswered. Positive delivery to that selected Codex
  session and product-code deployment/restart acceptance remain open.
* The live config is activated, but installed package code still predates this
  direct-dispatch patch. Local code/tests are not a production-upgrade claim.
  Authenticated live tool discovery confirms it also lacks
  `file_transfer_receiver_probe`; the new `library_receive` adapter needs the gated
  package upgrade. Current inventory reachability alone does not prove that upgrade.
* Historical Library bytes remain unavailable: 267 source-byte blockers plus eight
  restricted sensitive positions. No bulk transfer or duplicate Library job started.

## Verification record

The one local integration sweep initially produced **1,094 passed, 173 failed,
54 skipped**. Most failures were old pre-start enqueue assumptions. Execution tests
now start the dispatcher before admission; historical read/migration tests explicitly
seed pre-upgrade journals. No compatibility execution queue was reintroduced.

Affected follow-ups were run only for changed/failing cases and direct regressions:
the first two groups had 163 and 189 passes before their remaining fixture/state
expectations were corrected. Later groups resolved those cases (21 then 41 passes).
These counts overlap and must not be summed into an invented full-suite result.
No second local whole-suite sweep was run.

Final scoped evidence includes:

* 117 visible handoff, direct receiver, pre-input and window/config cases passed.
* 46 task, message, fault-boundary and migration cases passed after the conservative
  queued-with-execution-evidence correction.
* 14 window ownership/lifecycle cases passed, including active reuse leases,
  background shells, conflicting identities and uncertain-close restart behavior.
* 30 CLI/window/session cases passed, including refusal before agent input when the
  authenticated daemon is absent.
* 11 real ThreadDesk adapter cases passed with main `770bbc9`, including text/PNG,
  hash/readback/search, resume and lost begin/append/commit/abort responses.
* The fixed TollGate `53fc57` / file-transfer group produced 76 passes and three
  historical-fixture failures; those three corrected cases then passed separately.
* Three configuration/authorization cases passed. Disabled transfer permits scoped
  inspection while writes remain denied; unauthorized readers remain denied.
* Ruff, format and whitespace checks passed; source distribution and wheel built.

Native strict-close guard probing initially exposed macOS `doShellScript` returning
CR-separated process rows. The parser now accepts CR/LF and requires the exact user
shell PID, preserving additional background shells. The corrected guards passed
read-only against the same existing proof shell: no close action, no new windows,
and an unchanged pane set. The earlier actual owned-window close remains separate
evidence; no second owned window was created for retesting.

Public summary and private-log hashes: [evidence](evidence/rc17-direct-repair-20261025.json).
PR CI and package acceptance remain mandatory. Failed, interrupted or not-started
checks must never be represented as passing or bypassed.
