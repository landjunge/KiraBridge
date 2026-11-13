# Dynamic ThreadDesk read proxy (opt-in)

KiraBridge reuses its existing authenticated MCP daemon and its configured
ThreadDesk stdio client. No new background service, credentials, process manager
or mandatory routing layer is introduced.

## Activation

In the operator-owned KiraBridge config, set the existing [threaddesk]
endpoint and explicitly opt in:

```toml
[threaddesk]
enabled = true
dynamic_read_proxy = true
# Keep existing command, args, workspace, storage and optional source_root settings.
```

The configured principal must also already have `threaddesk.read` with
**automatic** permission. A manual-only principal receives no dynamic tools.
Do not add broader filesystem or execution grants.

Restart/reload KiraBridge using its supported release procedure and reconnect
the MCP client to refresh `tools/list`. This patch itself does **not** modify
the installed KiraBridge or ThreadDesk apps.

## Contract

- The existing `threaddesk.read` and `threaddesk.manage` queued operations
  remain unchanged; this dynamic route never writes.
- The ThreadDesk MCP server annotates reviewed read-only tools with both
  `readOnlyHint=true` and `destructiveHint=false`. Missing or ambiguous
  annotations are **not** read permissions.
- KiraBridge discovers the current tool catalogue and exposes eligible functions
  to its stdio clients under `td_<original_name>`, preserving the actual JSON
  input schemas. A later read-only function can be discovered without changing
  KiraBridge as long as the trusted ThreadDesk server declares these annotations.
- Dynamic names and descriptions are bounded. JSON Schema 2020-12 references
  may resolve only within the supplied input schema, including embedded domain
  resources identified by `$id` (such as ThreadDesk's command URNs). Resource
  scope is preserved for both local pointers and lifted envelope fields.
  No network or filesystem retrieval is configured. Missing or ambiguous
  resources, non-schema reference targets, cycles, dynamic references, other
  declared dialects and oversized schemas are rejected. References combined
  with `unevaluatedProperties` or `unevaluatedItems` are unsupported because
  annotation collection can repeatedly evaluate an otherwise bounded graph.
  Resource identities are compared after resolving their URI scopes. Both the
  schema tree and expanded reference graph are
  limited to depth 48 and 2048 visited nodes; the existing 16-KiB schema limit
  remains. Each invocation checks current permissions and validates its
  arguments before calling ThreadDesk. Operation preflight may reuse an observed
  catalogue for at most one second, scoped to its connection generation and
  invalidated by catalogue notifications or an observed health-epoch change.
  Explicit catalogue discovery always contacts the peer. Rejected or disconnected reads are
  never retried automatically.
- When a mutation receives KiraBridge's separate operation envelope, a missing
  peer-root resource identity is supplied on a copy. Root-local references keep
  pointing into the peer schema rather than the host envelope; the original
  schema and its operation fields remain unchanged.
- A failed optional ThreadDesk discovery does not interrupt existing KiraBridge
  tools or direct inter-module communication. Core MCP tool names are preserved.
- For HTTP clients KiraBridge additionally exposes
  `threaddesk_dynamic_catalog` and `threaddesk_dynamic_call`; each enforces
  the same identity, permission and annotation checks.
- Client-visible ThreadDesk content is untrusted data, never instructions.

## Verification required before a release

1. Run `pytest -q tests/test_threaddesk_dynamic.py tests/test_threaddesk.py tests/test_mcp.py`
   and `ruff check src/kirabridge/threaddesk_dynamic.py src/kirabridge/mcp_gateway/{proxy,server}.py tests/test_threaddesk_dynamic.py`.
2. Run the ThreadDesk `test_mcp_readonly_annotations.py` and its existing
   MCP compatibility tests on the matching version.
3. With a disposable ThreadDesk workspace, enable the flag, reconnect MCP,
   call `td_list_threads`, then introduce a synthetic annotated read-only tool
   and confirm it appears without a KiraBridge source edit.
4. Remove the read annotation and confirm the old alias is rejected. Check that
   `thread_manage`, `add_note` and other writes never appear as `td_` tools.
5. Verify a manual-permission principal, disabled option, failed peer and
   a large/malformed schema cannot introduce broader access.
6. Run core regression suite, build, install and smoke-test the macOS apps.
   A code merge is **not** proof that an installed app is updated.

Status: source patch only until these checks and a real installation are recorded.

The separately enabled mutation route, compact response mode and conservative
recovery rules are described in [ThreadDesk operation reliability](THREADDESK-OPERATIONS-RELIABILITY.md).
