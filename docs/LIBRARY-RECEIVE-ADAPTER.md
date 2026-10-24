# Library bytes: KiraBridge to ThreadDesk

The receiver adapter discovers and prefers the existing ThreadDesk
`library_receive` / `library_receive_status` contract. It maps begin, append,
status, commit and abort without changing ThreadDesk or inventing a second
receiver. Legacy `file_import_*` fixtures remain supported. CI pins actual
ThreadDesk main `770bbc9f0c0a02699cc93cad47d2e2c3782f7080` (PR88/89/90).

The effective destination includes command, arguments, workspace, storage and
source root. Preparation records preserve name, MIME, original Library path,
source reference/version, project/thread, size and SHA-256 in the existing
principal-scoped durable repository. Native ThreadDesk stores verified bytes
and its thread-bound receipt. The bridge retains that receipt and provenance;
it does not claim ThreadDesk's basename-only receiver stores all source metadata.
Never infer a source version or source hash from a filename or Library reference.

Native checkpoints bind transfer ID, exact manifest, state and offset. This
contract does not supply prefix hashes or chunk hashes: the adapter does not
fabricate them. Final size/SHA verification is performed by ThreadDesk before
commit. Independently read committed status must contain the correct receipt
format, ID, record ID, size, SHA, thread and download route before success.
An index result is separate from stored-byte confirmation; binary documents
are searchable by metadata, not extracted PDF/Office/media content.

After a timeout, read status once. A valid committed receipt can settle the
outcome; otherwise retain unknown/paused and require an explicit new resume
request with the **same transfer ID**. No write is automatically replayed.
Resume reads the checkpoint first, skips already acknowledged bytes and uses
the preallocated receiver record. Abort is principal/destination/project scoped,
independently confirms its terminal status, and never deletes committed files.
The new MCP tools are `file_transfer_receiver_probe` and `file_transfer_abort`.
Probe performs discovery and one read-only status request, creating no upload.

## Scoped import runner

`scripts/import_library_exports.py` uses the actual Bridge task owner, source
authorization, secret/archive validation, durable checkpoints and receiver.
It creates a dedicated local principal/state; only the specified export root
and the inventory's explicit existing thread IDs are granted. Transfers are
enabled for this process alone. No daemon configuration, unrelated queue,
credential, terminal or existing session is changed.

Supply an owner-private inventory with `files` entries, for example:

```json
{"files":[{"source_ref":"opaque-original-file-id","original_path":"/Project/note.md","export_relative":"Project/note.md","project":"Project","thread_id":"EXISTING_THREAD_ID","mime_type":"text/markdown","size":123,"source_version":null,"sha256":null}]}
```

The export basename must match the original. A missing version/hash remains
unknown; actual bytes are hashed during preparation, expected source hashes are
checked when supplied. Entries with `blocked_reason` are inventory-only and
never opened. Entries without `export_relative` are reported source-blocked.
Sensitive keys, tokens, configurations and personal documents must remain
blocked entries, without their contents. Secret-pattern scanning is bounded
defense, not comprehensive automatic personal-data classification.

```sh
python scripts/import_library_exports.py \
  --inventory /private/import/inventory.json --exports /private/import/exports \
  --state /private/import/checkpoints --workspace /actual/threaddesk-workspace \
  --receiver-python /pinned/runtime/bin/python --receiver-source /pinned/threaddesk/src
```

Reports in `STATE/reconciliation.json` preserve each error, manifest/receipt,
readback/search evidence and counts (expected, transferred, durably confirmed,
readback, indexed, blocked, failed, unknown, unprocessed). Stored bytes with
failed verification stay explicitly distinguishable. Unknown stops the batch;
`--resume` explicitly authorizes status-based continuation of existing IDs.
Repeated completed imports reuse receipts instead of creating duplicate records.
Original files are read only. No live profile restore or source deletion occurs.

## Actual source boundary on 24 October 2026

Thread `fdc7959f7dec` contains 275 inventory positions in 23 reported folders,
including two already-redacted confidential positions. Thread `f014aeed7384`
was empty of files. The current chat has no selected-file download capabilities
for these historical Library references. KiraBridge source adapters accept
host-selected `openai/fileParams` with real temporary URLs, or explicitly scoped
local exports. A `file_...` ID is neither a URL nor a filesystem path.
The available Pages reference reader requires an existing accessible Page and
exact observed reference; it is not a Library enumeration/export facility.
No browser cookies, guessed URLs or extracted document text substitute for
original file bytes.

Actual receiver tests use a text file and PNG plus real lost-response cases,
restart, readback, search, abort and receipt mismatch rejection. They prove
the transport/storage boundary, not receipt of the historical Library files.
Private per-file inventories/reports belong outside Git. The smallest source
handoff is to provide the non-sensitive original files as authorized selected
files or local exports under the dedicated import root, preserving paths.
Final local activation and counts must be recorded in the existing two
Whiteboards after exact-head CI/merge, with test files counted separately.
