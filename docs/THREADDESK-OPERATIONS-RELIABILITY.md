# ThreadDesk operations: liveness, discovery and receipts

Development-source contract, 13 November 2026. KiraBridge and ThreadDesk remain
separate products. These changes use the existing authenticated MCP connection,
task store and operation identifiers. They introduce no synchronization engine.

## Routine health

`bridge_health()` reports authenticated liveness without reading the task,
output-history, diagnostic or AutoNext databases. Its storage fields explicitly
say `not_probed`; `operations.accepting_new_work` is `null`. An alive dispatcher
does not prove readiness or admission. Request `include_diagnostics=true` for
the detailed synchronous report. Direct Python `Bridge.health()` retains its
existing detailed default. Both paths require the current health permission.

Passive discovery still depends on the running event loop and bounded native
filesystem checks. This is not an independent watchdog and cannot respond while
arbitrary synchronous work blocks that loop.

## Prerequisites are separate from executable transport

`bridge_readiness` includes the complete permission decision for each requested
operation: `authorized`, `automatic` and `approval_required`. Known capability,
platform or executable-policy blockers report `ok=false`; pending operator
approval reports `approval_required`, without changing queued-task policy.

Unprobed session, ThreadDesk or visible-terminal transport reports `ok=null`
and `transport_not_probed`. The aggregate is false if any known blocker exists,
otherwise null if a requested transport is unprobed. Other successful checks
retain true. Operation names for terminal execution describe their default
foreground route, including aliases routed to a visible terminal for ChatGPT;
internal execution routes remain independent of macOS Terminal.app.

The read uses routine health without database aggregation. Explicit workflow
audits remain opt-in. No command, terminal probe or connection attempt is
started, and a permission change is never inferred from readiness. An empty
executable allowlist remains an intentional restriction.

## Discovery during ongoing work

Explicit catalogue requests remain fresh. Operation preflight may reuse a
validated observation for at most one second, tied to the exact peer generation,
an observed health epoch and `tools/list_changed`. Cached schemas are isolated
from caller mutation. Authorization and argument validation still run on every
request; the peer also remains responsible for enforcing its own permissions.

A catalogue timeout retires the affected generation for new dispatches. Calls
already dispatched finish under their original deadlines before teardown. An
old completion cannot disconnect its replacement. No write is replayed by this
recovery. Genuine transport loss can still leave an operation UNKNOWN.

## Write responses and recovery

`threaddesk_dynamic_call(..., compact_response=true)` can project a verified
`thread_manage` receipt before task-result storage. The projection retains
operation ID, action, thread ID, revision and deletion/duplicate facts, plus a
readback hint. It omits the full thread body. Unsupported or unverified response
contracts remain full and report that compaction was not applied. The default
remains the full response. Changing this option changes the immutable request;
do not change it when repeating an existing operation ID.

Failure responses include the original task ID, state and attempt, enumerated
peer error codes and safe numeric details. Arbitrary peer exception prose is
not returned. Recovery names KiraBridge's outer operation ID separately from
the peer operation ID. Neither a response timeout nor a negative generic peer
response is evidence that no effect occurred.

Recovery performs only a currently authorized status read using a currently
validated status-tool contract. It can report a matching workspace and operation
receipt as evidence, but does not turn a failed call into success. Current
ThreadDesk status contracts do **not** return a canonical request hash: finding
their receipt preserves UNKNOWN and reports `request_hash_verified=false`.
The bridge does not implement speculative recovery against a future peer API.

An idempotency conflict preserves the original attempt. Inspect the original
task and peer operation before deciding on a distinct continuation; changing
the CAS revision or generating a new ID does not resolve an uncertain write.

## Validation and installation limits

Focused tests cover unavailable storage, authenticated HTTP health, revoked
grants, concurrent catalogue timeouts and writes, cache invalidation, lost or
malformed replies, mismatched receipts and compact persistence with independent
readback. Synthetic isolated workspaces contain no production data. Package,
release, native Linux execution and installed-runtime evidence are separate
checks; a local source test is not proof of server deployment or working
Mac/server synchronization.
