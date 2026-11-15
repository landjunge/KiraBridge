# ACP-PAP host integration contract

Development source, 15 November 2026. This is an explicitly embedded KiraBridge
adapter for synthetic integration and independent review. It is not registered
by default, installed in the running bridge, or accepted against a real model.
The independent private ACP-PAP library remains usable without KiraBridge.

## Ownership and dependencies

`agent_manager/acp_pap_host.py` implements the existing version-1 `AgentAdapter`
contract. An owning host must explicitly register `ACPHostAdapter` under
`acp_pap_host` and configure an agent with that kind and an absolute executable.
`ACPHostProfile.argv` is trusted host configuration, never peer-discovered or
task-supplied shell input. No discovery, import, or inventory read starts an
agent; only execution of an existing authorized Core task reaches `pap.connect`.

The embedder supplies `connection_for(owner)`, returning its existing authenticated
`DaemonConnection` for that exact principal. Peer messages do not carry bridge
credentials and cannot choose another principal, executable, launch profile,
account, or connection. The host must provision this mapping correctly; it is
not an authentication service or a second bridge.

The optional dependencies are installed outside the normal dependency graph:

- ACP-PAP source commit `2bb65784bc9d6df64d0b1fe057fe8736843cd10a`.
- Reviewed wheel SHA-256
  `95ad56ee9255fbff0bb50f55b7fe58c26ce47d56a4c9afb3eb2f18ba98c7fe74`.
- Python `agent-client-protocol==1.0.0`, negotiating ACP protocol version 1.

`_pinned_sdk` checks the SDK distribution version and the three installed library
module hashes before opening the ACP process. A mismatch fails as
`acp_dependency_unavailable`. These checks detect a different reviewed dependency
in the trusted Python environment; they are not a sandbox or protection against
a hostile interpreter/import path. The wheel hash records provenance; installed
module hashes are the runtime check. No source, wheel, key, account, or dependency
is downloaded by the adapter or CI. The existing lock file is unchanged. Without
the private local wheel the opt-in test module skips explicitly.

## Discovery, connection, session, task

These are separate states. Discovery can describe an executable without granting
execution. `pap.connect` starts the host-selected stdio process and negotiates
capabilities. A new ACP session then receives an absolute host-selected working
directory and a grant reference derived from the existing Core request and task
restriction. Only after this binding is available does the adapter submit one
prompt under the original Core task ID.

The host checks the stored operation, principal, arguments and original request
hash. Every callback revalidates the existing Core execution lease, current
`agent.execute` capability, current allowed-agent assignment, active task state
and arguments. Existing `TeamManager.authorize_execution` rechecks the sealed
Team/Core request where the task belongs to a team. An ACP callback must carry
the exact library-owned connection/session/cwd/grant binding; peer metadata cannot
replace it. An unowned session is rejected by the library before the host handler.

One fresh process/session belongs to one Core task. Resumption and direct local
tools are rejected. Model selection, authentication, session persistence and
coding profiles are outside this first host seam. In particular the adapter
does not select or switch a provider account. Qwen's existing adapter and sessions
are separate and unchanged.

With the production visible-handoff policy enabled, a sealed Team worker must
explicitly select `separate_managed_session` to reach this embedded adapter.
Direct Core work retains the required visible route. Registration alone does
not reroute that work to ACP.

## Capability advertisement and authority

ACP `ClientCapabilities` describes what the client can implement. It grants
nothing. The host advertises `fs.readTextFile` only when the original Core task
contains `file.read`. A peer that calls the method without that task grant is
rejected even when it has an owned session and the principal has a general read
capability.

Every read passes through the existing `AgentTaskPolicy.authorize` and existing
`DaemonConnection.read_query` facade. The intersection includes the original
task's operation, call budget, timeout and cwd; additional task read roots must
also be inside the host profile's read roots and the principal's existing roots.
The daemon still checks current principal permissions, excluded bridge state,
and descriptor-relative no-symlink file traversal. The adapter returns only a
complete, bounded, lossless UTF-8 result, then applies optional line slicing.

The host rechecks delivery authority after the awaited MCP read returns: current
Core task/binding/agent/lease, current `file.read`, principal and task path scopes,
excluded bridge state, resolved path and host-approved additional read roots.
This synchronous check performs no second file read or call-budget claim. A read
already performed under the original grant remains a completed access; revocation
blocks its still-outstanding reply from reaching ACP and cannot undo that access.
A file-right or path-scope denial can legitimately finish as a successful agent
turn containing `read-rejected`, without the protected content.

File writes, terminal RPCs, arbitrary MCP grants and operations other than
`file.read` are unsupported. They are not advertised and no handler is installed.
No second task queue, Core store, receipt ledger, daemon or bridge is introduced.

ACP permission requests use an explicitly supplied host `permission_decider`.
Without one, the host selects `reject_once` when offered, otherwise returns the
SDK's cancelled outcome. A decision does not add MCP operations or path roots.
After an awaited decision the host revalidates current task ownership and rights,
including agent-assignment removal and lease expiry. Cancellation resolves a
pending permission as cancelled; a late approval cannot restore it.

## Results and interruption

The original Core/Team path records running evidence, result, completion notice
and consumer ACK. Result provenance includes the Core request hash, connection,
session, grant reference and library commit. An ACP terminal `end_turn` confirms
that turn; it does not establish project acceptance. Typed session updates remain
available through the library event callback while bounded message text is
captured for the existing Core result.

A terminal RPC error is recorded as a failed request. A confirmed ACP cancelled
response produces the existing cancelled completion outcome. The adapter's
explicit `cancel(task_id)` addresses its owned active ACP session. It is an
embedding API, not a newly published cancellation tool; the generic Core
`task.cancel` remains limited to pending/queued tasks.

EOF, transport failure and the existing AgentManager local timeout retain an
UNKNOWN execution outcome. Submitting the same Core request observes that
original result and does not start a second process or prompt. Event-delivery
failures remain separately visible beside a received terminal response. A host
notification-handler failure can therefore leave incomplete captured output;
callers must inspect `delivery_failures`, not infer complete delivery from
`success` alone.

After asynchronous connection/process cleanup, the adapter revalidates the
current Core task authority before returning its final result. A received
terminal response with revoked task/agent/lease authority is recorded with
`success=false`, `host_authority_valid=false` and a bounded error code; captured
text is suppressed. Its actual ACP stop reason remains evidence. A rejected
notification alone cannot establish this final authority check or turn a revoked
task into completed success. Existing Core lease ownership still controls who
may persist a terminal outcome; a stolen lease is not reclaimed by this adapter.

## Trust and platform limits

This adapter limits host RPC authority; it does not isolate the child process's
native OS access, network, subprocesses or same-user credentials. An arbitrary
executable may ignore ACP permissions entirely. Use only an already authorized
peer and a suitable existing execution environment. No OS sandbox is claimed.

`PathScope.directory` checks cwd with the existing POSIX no-symlink traversal,
but the upstream process launcher consumes a pathname, not that open descriptor.
An external rename/symlink race between validation and spawn is not prevented.
Windows filesystem execution is rejected by the current secure filesystem seam;
there is no Windows host-adapter acceptance. The tests use a native Intel Mac
Python process and a synthetic ACP peer, with no UI/Voice/server deployment claim.

## Focused validation

Run in an isolated environment containing the reviewed local wheel and SDK:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q tests/test_acp_pap_host.py
.venv/bin/ruff check src/kirabridge/agent_manager/acp_pap_host.py tests/test_acp_pap_host.py tests/fixtures/acp_pap_host_peer.py
.venv/bin/ruff format --check src/kirabridge/agent_manager/acp_pap_host.py tests/test_acp_pap_host.py tests/fixtures/acp_pap_host_peer.py
```

The tests exercise actual Core and Team dispatch, original request sealing,
read-through MCP, receipts/consumer ACK, outside/symlink/unowned-session rejection,
unsupported terminal calls, event delivery failure, pending-permission
cancellation, default permission denial, capability/agent/lease revocation,
deferred-read delivery revocation and unchanged-right positive controls, final
authority loss during asynchronous cleanup, missing task read grant,
EOF/local-timeout UNKNOWN without replay, and a wrong
library pin before process start. The synthetic peer imports the actual ACP SDK;
it starts no external model, login or account operation. Independent review,
real-provider parity and any runtime activation remain separate acceptance steps.
