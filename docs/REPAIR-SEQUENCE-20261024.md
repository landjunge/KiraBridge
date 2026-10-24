# Ordered repair status · 2026-10-24

User-mandated order: queue → current terminal binding/input → Whiteboard validation
→ Library import/knowledge organization. No duplicate execution of the queued request.

## Phase 1: queue

Live read-only RC14 diagnosis confirms a queued new message without terminal input,
blocked by an old uncertain handoff. Its original failure/receipt history is preserved.
No production queue, installation, configuration or permissions were modified.

Implementation is separate modules: `queue_management/schema.py` (additive holds),
`views.py` (owner scope, pagination, revisions/content), `control.py` (CAS/withdrawal/
restore/retirement), `models.py` (strict contract), `mcp_gateway/queue_tools.py`
(MCP registration), `event_queue.py` (independent webhook outbox). Existing task,
approval, stop, receiver and audit owners are reused. No new scheduler or token store.

Executed on actual Intel macOS 15.7.4: 1069 full regression tests passed before final
hardening. Subsequent focused checks cover sender-only restoration, late receipts,
lossless Unicode content and the installer downgrade guard. A final full-suite run
and its exact evidence are recorded with the PR after source pinning.
Real isolated HTTP MCP proves discovery, authenticated queue inspection, cancellation,
restoration, snapshot clear and actual owned-process stop with exit code. Unit/contract
cases exercise unknown handoff readiness refusal/retirement, no duplicate dispatch,
restart persistence, capacity recovery, foreign scope, manual exact approval and races.
Readiness success for an uncertain handoff in these unit cases is simulated; it is not
a live production Codex receipt. Production RC14 exposes no `queue.control` operation.

**Deployment/production gate remains open:** new tools are not installed into RC14.
Its old unknown and queued Library message are not claimed removed, delivered or run.
A safe older-runtime refusal is distinct from a successful rollback. Required GitHub
checks/review and explicit installation acceptance/authorization remain necessary.

Phases 2–4 must not be represented as completed while this production gate remains.
The existing Whiteboard `f014aeed7384` is not duplicated. No Library files were
transferred or interpreted by this queue-repair work. OpenAI/ThreadDesk access and
actual source data must be verified only after the ordered prerequisite is satisfied.

## Reproduce (isolated development)

`uv sync --locked --dev`, then `uv run pytest -q`.
Focused: `uv run pytest -q tests/test_queue_management.py tests/test_event_push.py tests/test_installer.py`.
The real HTTP fixture uses random local ports, synthetic credentials, private temp
stores and one owned short-lived sleeper. It never types into a user's Terminal.
No source body or secret is included in the tracked live diagnostic evidence.

## Verification timing failure

One full run reported 1071 passed and one failure in the existing child-cleanup test:
its 300-ms execution budget elapsed before any child PID was captured. The unchanged
focused test immediately passed. The test fixture now allows 3 seconds for interpreter/
child startup; timeout and observed child disappearance assertions are retained. No
production timeout, cleanup code or security check was relaxed. The final suite must
pass with that unchanged cleanup assertion; the failed run is retained as evidence.

## Final scoped checks and user testing constraint

The final message-job/content revision correction passed **66 directly related tests**
(queue management, event push, installer). Earlier the broad suite passed **1074 tests**;
that broad success precedes the last revision-binding correction. A later broad retry
was interrupted on the user's explicit instruction to avoid additional whole-suite
repetitions; it is **not** counted as passing. No further broad tests were launched.
The final targeted selection is necessary for the changed queue state/rights/readback,
webhook cancellation/authorization race and downgrade protection. Logs and source-tree
fingerprint: [test evidence](evidence/queue-phase1-tests-20261024.json).

The actual isolated RC14 wheel was also probed: a held-delivery downgrade is refused
without switching/stopping a service or modifying the store. The compatible comparison
uses the editable development runtime, not an installer/package acceptance claim.

No new release or production installation is approved. The queued Library request
has not been resent, acknowledged as executed or run in parallel. No Whiteboard write
has been attempted while the ordered Phase 1 production gate remains open.
