# Whiteboard administration boundaries / Whiteboard-Grenzen

This is a KiraBridge-only repair on the development lineage after PR26. Production
RC14, ThreadDesk code, credentials, permissions and user Whiteboards are unchanged.
The native subagent did not make any live Whiteboard mutation.

## Belegter Befund

Read-only ThreadDesk source checked at
`64353be01082251b6af72d0096ce0a57d66c5501`:

- `services/mcp.py:_management_schema` declares 10,000 Unicode characters for
  title/description and 100,000 for `set_note.data.text`; the latter is **per
  request**, not an advertised total notes size. UTF-8 bytes are a different count.
- `services/thread_management.py:validate` enforces those sizes and action fields.
  `manage` persists operation-ID/request-hash receipts and resolves an exact prior
  operation before checking revision. A changed request under the same operation
  ID conflicts. `thread_operation_status` reads the saved receipt.
- `api/service.py:set_note` supports replacement and append; append applies
  `old_notes.rstrip() + "\n" + new_text`. It is not lossless concatenation of arbitrary
  existing text. `set_description` also strips outer whitespace on updates.
- `services/mcp.py:wrap_untrusted` changes literal `</untrusted>` to `</ untrusted>`
  in returned notes/description. The stored original cannot always be reconstructed
  exactly from this public representation. No paginated raw-text readback is exposed.
- `ui/mcp_stdio.py` returns JSON text (UTF-8, `ensure_ascii=False`), not structured
  content. `get_thread`, mutation receipts and operation status contain full growing
  notes. Their responses can exceed KiraBridge's configured result-byte budget.

These mechanisms reproduce size rejection and bounded-response uncertainty; the
historical failing request payloads were not supplied. They do **not** prove that
every historical `validation_error` or `tool_error` had the same cause. The root's
live milestone conflict (expected revision 6, actual 8) is a separate successful CAS
protection, not evidence of a length limit.

## KiraBridge repair

`threaddesk_contract.py` owns bounded field-contract inspection and content-free
validation errors; `ThreadDeskManager` remains the fixed operator-configured MCP
transport/receipt owner. There is no parallel queue, token store or ThreadDesk writer.

Before each administration mutation, the manager refreshes the actual peer's
`tools/list` schema within the existing configured timeout. Action field shape,
required fields, JSON types, enum values, actual character constraints and IDs are
checked before `running` or mutation. Missing legacy declarations use clearly labelled
KiraBridge compatibility limits, rather than pretending those limits were negotiated.
The error gives field, constraint, declared/compatibility source, actual characters,
UTF-8 bytes and `request_sent=false`. Input is neither truncated nor moved into
another field. A removed operation or catalog timeout cannot proceed to a mutation.

The schema is untrusted metadata: no JSONSchema resolver or peer regex is executed;
`$ref` is rejected anywhere, with fixed depth/node/variant/field/type/enum budgets.
Malformed schema or non-dict peer error details cannot cause an accidental write or
hide the original safe error code. Raw peer error text is not echoed because it can
contain secrets. Safe numeric constraints/revisions are retained.

The existing result-byte budget and mutation receipt correlation are unchanged.
An oversized, lost or disconnected mutation response remains **unknown**, never
successful or automatically retried. Task evidence records the configured response
budget, timeout and request byte count without contents. Reconcile using the original
operation ID; do not create a replacement Whiteboard because its reply was lost.

## Necessary targeted verification

Tests run on actual macOS 15.7.4 Intel x86_64, in private synthetic fixtures. The real
MCP tests use an independent disk-backed **contract fixture, not the ThreadDesk
product**. No native GUI or production-storage acceptance is inferred.

Only affected tests were run. The new contract file contains 39 distinct cases,
covered incrementally while fixing the affected cases; there was no complete project
suite or precautionary repeated file suite. The initial fixture could not initialize
because its return annotation used an unsupported MCP union; its four failed MCP
cases were rerun after correcting that fixture signature, and all passed.

Final directly affected checks:

- 18 schema/error-shape/constraint cases passed after parent security review.
- 3 catalog/preflight cases passed, including configured timeout before mutation.
- 2 schema-resource boundary cases passed.
- 6 actual MCP cases passed after the catalog change: short/long/100,000-character
  Unicode note, lost create receipt reconciliation, plus the two existing file-MCP
  adapter/restart regressions affected by changing the shared connection catalog.
- 1 additional actual MCP test passed for create/update/readback at the 10,000-
  character description boundary. Valid descriptions/notes were unchanged at disk
  and readback in the fixture. No truncation, duplicate create, or blind replay.
- Ruff for the four touched Python files and Git whitespace checks passed.

## Remaining compatible receiver requirements

KiraBridge does not implement a lossy chunk workaround over the existing append API.
For content beyond currently declared fields or byte-exact arbitrary Whiteboard
readback, ThreadDesk needs a versioned contract with immutable content/version hash,
character/byte/aggregate limits, offset-addressed **raw** text reads, idempotent exact
append/chunk acknowledgements, revision binding and a compact durable operation
receipt independent of the full growing thread. No such API is invented here.

Long valid inputs within the declared and configured bounds can use existing
create/update/set_note and explicit independent get-thread readback. General live
ThreadDesk long-text acceptance, beyond-limit storage and a lossless multi-step
receiver remain unverified. Ask neither the caller nor an installer to silently
increase budgets or change production permissions to bypass these limits.

## Subsequent real pinned ThreadDesk compatibility acceptance

One targeted acceptance run used the **actual unmodified** ThreadDesk source commit
`64353be01082251b6af72d0096ce0a57d66c5501`, downloaded only under KiraBridge `dist`.
No package/dependency was installed. A fixed guarded launcher called
`threaddesk.ui.mcp_stdio.serve(ThreadService(store=JsonStore(explicit_new_root)))`.
In that original executed run, `THREADDESK_HOME` and the store were explicitly isolated,
and the launcher also overrode its child process HOME. Default profiles were not used;
the source Python hash was identical before/after. A subsequent harness-only correction
removed HOME and XDG_CONFIG_HOME overrides because HOME must not be repurposed.
The fixed explicit `JsonStore` plus `THREADDESK_HOME` remains the isolation boundary.
The corrected harness has **not** been rerun; the evidence below describes the original
single run accurately, rather than claiming new acceptance.

Actual macOS 15.7.4 Intel x86_64 results through KiraBridge **Bridge/TaskManager**:

1. Create with a full 10,000-character description: completed, correlated receipt.
2. Replace notes with 100,000 Emoji (400,000 UTF-8 bytes): completed; existing
   524,288-byte response budget unchanged.
3. Independent `get_thread` and raw JsonStore JSON matched complete original notes
   and description. The controlled payload excludes the reserved wrapper delimiter;
   this does not establish lossless raw readback for every possible string.
4. A 10,001-character description was rejected before mutation using the actual
   peer's declared 10,000-character limit. The entire private store's JSON files
   remained unchanged.

The acceptance script is `scripts/accept_whiteboard_interop.py`; guarded reproduction
requires the pinned source/hash and a **new** test directory within this repository's
`dist`. Portable evidence: [real interop result](evidence/whiteboard-real-threaddesk-interop-20261024.json).
This fills the earlier fresh-store real-source compatibility gap. It is not a native
GUI/installed-app or productive-user-profile acceptance, and it does not attribute the
root agent's separate existing-profile `tool_error` to a length limit. No additional
project tests, live Whiteboard writes or repeated acceptance flow were performed.
