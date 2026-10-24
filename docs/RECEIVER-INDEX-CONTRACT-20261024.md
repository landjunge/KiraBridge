# Receiver and content-index compatibility · read-only team audit

Status: **proposed requirements, not implemented ThreadDesk MCP tools**. Native
subagent `/root/receiver_contract_audit` inspected source only. No tests, imports,
index rebuilds or productive mutations were performed by that agent.

## Verified source and boundaries

ThreadDesk main advanced to [64353be01082251b6af72d0096ce0a57d66c5501](https://github.com/landjunge/threaddesk/commit/64353be01082251b6af72d0096ce0a57d66c5501)
through [PR87](https://github.com/landjunge/threaddesk/pull/87). Its local
`services/library_bridge.py`, `library_commands.py`, `library_index.py` extend the
local import from PR86. This is source availability, not a release/deployment claim.

`services/mcp.py` and `ui/mcp_stdio.py` expose none of the six tools required by
[KiraBridge's existing byte-transfer contract](THREADDESK-FILE-TRANSFER-V1.md):
`file_import_capabilities`, `file_import_begin`, `file_import_status`,
`file_import_chunk`, `file_import_commit`, `file_import_receipt`.
They expose no Library index/status/search/rebuild MCP tools either. The current
KiraBridge adapter must report `transfer_protocol_unavailable`, not silently fall
back to `thread_manage.add_file`. That method only adds a path reference
([service.py](https://github.com/landjunge/threaddesk/blob/64353be01082251b6af72d0096ce0a57d66c5501/src/threaddesk/api/service.py#L363)).

The local `LibraryImporter` copies and hashes real bytes, records versions and can
resume from original exports. It does not implement byte-offset/prefix negotiation,
persisted KiraBridge operation/manifest bindings or the independently retrievable
v1 durable receipt. Its own publication methods use file replacement without an
explicit fsync in those methods; source inspection does not establish the strict
storage-durability acceptance required by the sender contract.

Local limits: 256 MiB/file, 2 GiB/batch, 2000 files; ZIP 500 entries and 256 MiB
expanded. KiraBridge defaults are not evidence that a receiver accepts larger files.
The receiver must advertise its actual limits before sending; use the stricter
intersection. Local folder/title matching or “Nicht zugeordnet” does not attest an
explicit authorized project/thread target.

## Index coverage is not full content extraction

`library_index.py` writes a local `library-files/index.json`. Known text formats
contribute at most 32 KiB excerpt; PDF, Office, image, audio and video entries are
metadata-only. There is no demonstrated OCR, transcription or document-content
extractor. The excerpt implementation reads the blob before slicing, so 32 KiB is
an excerpt limit, **not** proof of a bounded source-read allocation. Nontext branches
do not independently check blob existence. Do not infer complete corpus integrity
from index availability.

Local `/library/command` supports commands and can rebuild a missing/broken index;
local UI import routes have their own LocalHTTPAccess/CSRF controls. Neither is an
implicitly authorized MCP replacement. `ui/search_cli.py` is separate and indexes
thread title/description/notes, not all imported blob contents. Do not copy cookies,
invent grants or run a different configured process to bypass these boundaries.

## Minimal interoperable extension

Keep the existing KiraBridge source/authorization/integrity/checkpoint/sink modules.
ThreadDesk owns storage, project/thread attachment, retrieval and indexing.

1. Expose a thin authenticated MCP receiver around ThreadDesk's storage owner,
   implementing the six existing byte-transfer/checkpoint/receipt tools. Verify
   each chunk and final stored blob, persist operation/manifest binding across
   restart, and fetch the durable receipt independently after commit.
2. Bind an exact authorized project/thread scope. KiraBridge v1 currently carries
   `project_id` and `folder`, not a separate `thread_id`. A title/folder heuristic
   cannot substitute for an explicit mapping. Negotiate a precise scope mapping
   or a versioned target extension before claiming thread assignment. Do not add
   default serialized fields that silently change hashes of old v1 manifests or
   replay existing checkpoints under a new destination.
3. Provide a separately authorized content-index port: index status/generation,
   rebuild with stable operation identity, scoped cursor-based search, and bounded
   content/excerpt retrieval. Returned evidence must bind artifact ID, original
   source SHA-256, thread/project, extractor/version and coverage/truncation.
   These are requirements, not names of currently available tools.
4. Report absent/corrupt blobs, stale index generations, unsupported extraction and
   partial failures explicitly. Rebuild from stored originals; preserve provenance
   and versions. Metadata hits are not evidence of full-text indexing.

Acceptance, once these ports and expressly selected/exported files exist: byte/SHA
identity, source preservation, duplicate/version policy, exact target, lost replies,
sender/receiver restart, pause/resume, limits, durable receipt after restart, corrupt
blob/index and actual rebuild/readback. Content summaries must cite stored original
IDs/hashes, retain “Brainstorming” for undecided ideas and distinguish unsupported
extraction from a negative search result. No account-wide Library or Drive authority
was established by this audit.

## Related Whiteboard constraints

At the same ThreadDesk pin, `set_note.data.text` permits 100000 characters/request;
append is cumulative but applies `existing.notes.rstrip() + "\n" + text`.
`get_thread`, mutation receipts and operation status return the whole thread without
range reads. Small writes therefore do not bound response size. Public rendering
replaces `</untrusted>` with `</ untrusted>`; it is not an invertible raw-text view.
An arbitrary lossless chunk protocol needs receiver-side raw hash/range semantics;
KiraBridge must not assert exact raw integrity from that rendered view alone.
