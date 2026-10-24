# Modularity review before file-transfer implementation · 2026-10-24

Scope: KiraBridge only. Starting runtime lineage: `33126b7` (merged RC15 work);
latest published release RC14; RC15 is a draft. Discovery/visible-terminal repairs
were in progress when the file-transfer assignment arrived and remain in scope.
No production configuration or data was used for this review.

## Evidence and assessment

| Existing component | Concrete files | Assessment / boundary |
| --- | --- | --- |
| Composition / dispatch | `src/kirabridge/bridge_core/bridge.py`, `task_manager/manager.py` | Central `Bridge` constructs managers and dispatches typed operations. Task acceptance, exact approval, idempotency, audit and leases are reusable; the composition root has many dependencies and is not itself an independent business module. |
| Filesystem authority | `filesystem_manager/__init__.py:PathScope` | Descriptor-relative, no-follow traversal is reusable. Existing text read/write APIs cap payloads and are not a binary streaming transfer implementation. Preserve them unchanged. |
| Authorization | `security_manager/__init__.py`, `permissions.py`, `session_input_policy.py` | Effective capability/approval decisions are shared. Window grants previously contradicted advertised automatic permissions; that is handled by the preceding repair. Deferred `permissions` ↔ `session_input_policy` imports are a potential cycle, not proof of import-time failure. |
| Outbound transports | `mcp_gateway/client.py` | One async owner per MCP connection; no blind mutation replay. Reuse this connection owner rather than introducing another ThreadDesk client or token store. |
| ThreadDesk adapter | `threaddesk_manager.py`, `threaddesk_dynamic.py` | Fixed operator-controlled executable/workspace, narrow read/write tools and correlated receipts. No existing general file-byte import protocol. File transfer needs its own typed sink boundary, reusing this adapter's connection authority. |
| Sessions/platform | `session_ports.py`, `session_manager.py`, `platform_adapters/terminal_app.py` | Explicit ports are present. The new visible-command helper initially took the full Bridge and shared prompt logic through a reverse import; narrow its constructor and move the pure prompt predicate below both components. |
| Status and audit | `diagnostics.py`, `task_manager/store.py`, `audit_manager/__init__.py`, `output_history.py` | Reuse the task store and audit chain. Signed URLs, credentials and file content must not be copied into task arguments or audit events. Large binary files do not belong in bounded tool-result captures. |
| Local UI / activation | `operator_application.py`, `operator_control.py`, `operations_service.py` | Several boundaries already use named partners; activation still coordinates the whole core. Preserve its drain/rollback checks. Do not add transfer ownership to the browser or an unrelated platform adapter. |

Static AST inventory before transfer work: **93 Python modules, 343 internal
import edges**. The scanner includes imports inside functions and therefore finds
potential cycles, including a large deferred composition component; these are
not all eager-import/runtime cycles. Other components include
`message_manager` ↔ `voice_message_policy` and `approval_console` ↔ `control_center`.
Do not claim that the whole existing project is strictly acyclic or fully decoupled.
The raw pre-refactor AST inventory is retained as `docs/evidence/modularity-before.json`.

Read-only ThreadDesk source inspection: main commit
`7c45d1447a7c11966e22419e2b451c5d54d8df45`. Its migration/import models and
storage protocols are distinct from a resumable file-byte import contract. No
ThreadDesk code, workspace, credentials or production process is modified.

## Required targeted design

Create `file_transfer` as an independently testable package with these owners:

- `models`: versioned source, manifest, progress and durable receipt shapes.
- `ports`: source reader, receiver and journal/authorization/audit protocols.
- `sources`: explicitly supplied ChatGPT file parameters or authorized local exports;
  no account-wide Library crawler, browser cookies or automatic Drive access.
- `inventory` / `repository`: principal-scoped registered source metadata and durable
  transfer checkpoints in additive tables of the existing task database.
- `authorization`: existing capability/exact-task decisions, explicit source scope,
  secret rejection and opt-in destination configuration; no grants minted by models.
- `integrity`: bounded incremental hashes, snapshot identity, path/archive validation
  and content-based duplicate detection within the same destination/project scope.
- `protocol` / `service`: bounded byte streaming, acknowledged offsets, restart and
  cancellation handling; unknown remote writes reconcile through status first.
- `threaddesk`: a narrow versioned sink using the existing authenticated MCP owner;
  transfer completion and independently fetched durable storage receipt are separate.
- `diagnostics`: safe progress and error codes, byte counters/hashes, no signed URLs,
  tokens, file contents or unredacted transport exceptions in audit output.

Only the composition root and MCP registration know the complete application.
The transfer package must not import `Bridge`, UI, terminal or provider-agent
implementations. Tests enforce the dependency direction. Avoid a parallel queue,
credential store, audit chain, filesystem-permission implementation or production
ThreadDesk importer. Existing task/schema behavior remains compatible; transfer
checkpoints use additive, namespaced tables and do not restore old task databases.

## Supported OpenAI boundary

Verified 2026-10-24: https://developers.openai.com/plugins/reference documents the
optional host file picker and file-parameter metadata. A selected file can provide
a temporary download capability; availability depends on the host/account. No
verified account-wide enumeration, folder inventory or arbitrary historical-file
access is inferred. Library paths/versions are preserved when explicitly supplied;
unknown provenance fields remain unknown. Manual authorized exports remain usable
without the optional picker. Historical 275-file / 23-folder counts are not treated
as a current readable inventory. Enterprise compliance export requires separate
Compliance API permissions and is not silently enabled.

## Implemented boundaries

`src/kirabridge/file_transfer/{models,ports,sources,authorization,integrity,repository,
protocol,service,threaddesk,diagnostics}.py` implement the owners above. Source inventory
belongs to `SourceRegistry` in `sources.py`, durable transfer inventory to `repository.py`;
there is no redundant index. `mcp_gateway/file_tools.py` registers tools using narrow
injected partners rather than the Bridge. `Bridge` only wires/dispatches the service.

`private_files.py` extracts existing private-JSON helpers (re-exported by local_runtime)
and `platform_adapters/shell_prompt.py` owns the pure prompt predicate. The visible
terminal constructor takes config/security/sessions/environment, removing its whole-
Bridge dependency and reverse session import. Existing task queue/audit/MCP owner and
PathScope are reused. File-transfer dependency tests reject imports of Bridge, UI,
terminal or provider-agent implementations. Remaining legacy potential cycles are
explicitly retained rather than claimed fixed by a whole-project rewrite.
