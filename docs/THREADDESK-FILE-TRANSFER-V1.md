# KiraBridge → ThreadDesk file-byte import contract v1

**Status: proposed interoperable contract; ThreadDesk implementation/acceptance is
not yet verified.** This document belongs to KiraBridge. No ThreadDesk code or
workspace is changed. Read-only baseline inspected:
`landjunge/threaddesk@7c45d1447a7c11966e22419e2b451c5d54d8df45`.
Its existing migration imports are not this file-byte protocol. Grok can implement
this contract in ThreadDesk, or supply an existing versioned contract for the sink
to target. Tool availability is verified before any transfer mutation.

## Transport and authority

Use the existing operator-configured authenticated ThreadDesk MCP connection:
fixed executable, fixed arguments, fixed independent workspace, existing SDK owner.
No arbitrary receiver URL, filesystem write into ThreadDesk storage, browser
cookies, copied ThreadDesk implementation or implicitly granted Drive access.
The receiving process owns authorization of its project IDs and workspace storage.
All six tools below must be present, and every response must include
`protocol: "kirabridge.threaddesk.files.v1"`.

KiraBridge derives `operation_id = "kb_file_" + SHA256(canonical([principal, manifest]))`.
Canonical JSON: UTF-8, sorted object keys, separators `,` and `:`, unescaped Unicode,
no NaN. IDs and idempotency must be bound to the authenticated sending context.
`manifest_sha256` is SHA-256 of the canonical manifest, not a reference substituted
for file content. ThreadDesk receives actual `data_base64` chunks as well.

## Manifest

Required fields: `protocol`, `name`, `mime_type`, `size`, `sha256`, `project_id`,
`folder`, `library_path`, `source_kind`, `source_ref`, `source_version`,
`destination_ref`. Size is a nonnegative integer, SHA-256 lowercase 64 hex.
`library_path` and `source_version` may be null when unknown. Preserve that
uncertainty; do not invent account-wide paths or versions. `source_kind` is
`chatgpt_file_param` or `authorized_export`; `source_ref` is an opaque digest.
`destination_ref` binds the sender's prepared operation to its fixed configured
receiver, preventing silent retargeting after configuration changes.

Name must be a safe basename; destination folder is a relative POSIX path. Reject
traversal, NUL/control characters, drive prefixes and symlinks. Do not URL-decode
names into different paths. The bytes are immutable: no document conversion,
newline normalization, archive extraction or re-encoding during transmission.
ThreadDesk owns storage, project attachment, indexing and viewing.

## Tools

1. `file_import_capabilities({})` → `protocol`, `resumable: true`,
   `durable_receipts: true`, `max_chunk_bytes` (integer 16 KiB–1 MiB).
2. `file_import_begin({operation_id, manifest})` → checkpoint. Identical requests
   are idempotent; the same operation with a different manifest is a conflict.
3. `file_import_status({operation_id})` → checkpoint, or structured `not_found`.
   Missing state is different from an unreachable receiver. KiraBridge never
   interprets network failure as permission to start a replacement operation.
4. `file_import_chunk({operation_id, offset, data_base64, sha256})` → checkpoint
   plus `chunk_sha256`. Bytes must begin at the acknowledged offset. Repeated chunks
   must be accepted only when offset/length/content match prior receipt; mismatches
   or gaps are conflicts. Never append a duplicate after an uncertain response.
5. `file_import_commit({operation_id})` requests final validation and durable
   storage/project attachment. Its reply alone is **not** successful import.
6. `file_import_receipt({operation_id})` independently reads the persisted result
   and returns the durable receipt described below.

Checkpoint fields: `protocol`, `operation_id`, `manifest_sha256`, `next_offset`,
`prefix_sha256`. The offset is an integer in `[0,size]`; prefix SHA-256 describes
exactly those original bytes. Empty prefix is SHA-256 of empty bytes. KiraBridge
verifies the prefix before resuming. Each chunk acknowledgement must advance by
exactly the sent length and confirm its SHA-256. Receiver checkpoints must survive
process restarts. Sender restarts retain the immutable staged snapshot and stored
operation ID, never the temporary source URL.

## Durable storage receipt

Required: `protocol`, `operation_id`, `manifest_sha256`, `sha256`, `size`,
`project_id`, `folder`, `name`, `artifact_id` (nonempty string),
`storage_revision` (nonempty string), `state: "stored"`, `durable: true` (boolean).
All manifest, size, hash and project/folder/name bindings must match exactly.
ThreadDesk must compute/verify the hash from its actual stored file and commit its
project attachment and metadata durably before returning this receipt. It must
remain retrievable after a receiver restart. Names or URLs alone never qualify.

Content-addressed duplicate storage is allowed within the authorized destination;
retain each requested name, folder, provenance and project relationship. Cross-
project or cross-user deduplication must not reveal another identity's files.

## Limits, secrets, errors and interruption

Default sender limits: 2 GiB/file, 8 GiB total staged copies, 256 KiB chunks
(negotiated down to receiver limits), 10,000 ZIP entries, 8 GiB expanded ZIP bytes,
compression ratio 200. These are configurable upper bounds, not a claim that a
2 GiB acceptance run occurred. Streaming is bounded; source files remain intact.
Archives are checked without extraction; obvious credentials/private keys and
recognized secret patterns are rejected before receiver bytes are sent. Secret
scanning is defensive, not proof that every possible secret format is detectable.

The sender persists authorized/running/transferred/stored/failed/paused separately.
`transferred` means acknowledged bytes, not durable import. An interrupted or
uncertain mutation pauses for explicit reconciliation; resume uses a new KiraBridge
task ID/key for the same transfer. Read receiver status first. Never reset a
receiver prefix, overwrite mismatched data, blindly repeat a commit, delete source
Library files, or claim that a queue receipt is file storage.

Audit/status expose safe operation IDs, counters, hashes and error codes. They
exclude signed download URLs, bearer tokens, source contents and raw transport
exceptions. Binary test fixtures with filesystem-backed receipt verification are
contract tests, not proof of a live ChatGPT selection or production ThreadDesk import.
