# KiraBridge

Private, modular local desktop and multi-agent bridge. This document is the original architectural baseline. Implementation and team assignment have since been carried out; current evidence and limits are recorded in [STATUS.md](STATUS.md), [team operation](TEAM-ORCHESTRATION.md) and the versioned release notes.

## Goal

Provide secure local file, terminal and process capabilities to multiple authorized agent systems through interchangeable adapters and multiple MCP connections, without relying on Desktop Commander quotas. The ChatGPT connector requires separate supported integration and cannot be assumed operational.

## Architecture

- **Core:** Python asyncio orchestration; versioned interfaces and structured errors.
- **Task Manager:** SQLite WAL, durable jobs, idempotency keys, leases, acknowledgements, status reconciliation and crash recovery. Unknown is never silently treated as completed or retried.
- **Agent adapters:** Codex and Grok first; extensible to other agent CLIs and A2A peers. Distinguish daemon presence, agent session, actual task and verified result.
- **Protocol adapters:** MCP stdio and Streamable HTTP; separate transport from authorization and execution. SSH is an optional transport for remote hosts, not a blanket command authorization.
- **System tools:** scoped file reads/writes, process inspection, bounded terminal execution; explicit permissions for mutating or destructive actions.
- **Security:** local-only by default, authenticated remote access, least privilege, capability-scoped approvals, replay protection, redacted logs and auditable task receipts. No credentials in logs.
- **Integrations:** ThreadDesk for coordination, Agent Authority for evidence/authority, Tollgate for budgets, each optional and independent.

## Delivery sequence

1. **Foundation:** package structure, configuration, typed API, SQLite schema/migrations, crash-safe durable task records.
2. **Reliable dispatch:** receipt IDs, idempotency, state machine (`created`, `queued`, `accepted`, `running`, `completed`, `failed`, `blocked`, `unknown`), reconciliation after interruption; never blindly re-run a possibly executed command.
3. **Agent adapters:** Codex/Grok integration and evidence-based state detection; distinguish tool/session completion from whole project completion.
4. **Desktop tools:** path-scoped file operations, safe subprocess execution, bounded output, cancellation, timeouts, process inspection.
5. **MCP connectivity:** local MCP server/client support and multiple concurrent connections; authenticate and scope every tool call. Add remote HTTPS transport only after threat review.
6. **Cross-platform and integrations:** macOS first (older iMac resource budget), then Linux and Windows; optional A2A, SSH, ThreadDesk/Agent Authority/Tollgate.

## Acceptance criteria

- A task is durably stored before dispatch, received by the intended adapter and acknowledged with traceable evidence.
- Disconnects and restarts preserve state without accidental duplicate execution.
- Status distinguishes `unknown` from `running` and `completed` with evidence and timestamps.
- Unauthenticated and unauthorized tool calls fail closed; destructive actions require specific approval.
- Multiple independent MCP clients and agent adapters cannot cross task or authorization boundaries.
- Targeted tests cover failure recovery, idempotency, authorization and protocol interoperability.

## Initial work division

**Codex:** implement foundation, task lifecycle, adapters, desktop tools and MCP interfaces in isolated increments; document actual test results and remaining blockers.

**Grok:** independently review architecture, threat model, crash/idempotency cases, multi-protocol interoperability and Codex evidence; report actionable findings without rewriting historical results.

## Operating constraints

Keep the repository private. Do not alter existing Agent Authority, ThreadDesk, Tollgate or Help Center projects, publish a service, deploy to production, stop existing agents or grant external access without explicit authorization. Minimize tests but never omit necessary safety checks. Keep source and review evidence versioned.


## Current evidence delta · KB-INTEL-20261029

Intel rc18 packaging, integration tests and isolated lifecycle acceptance are complete;
merge/publication and productive activation remain separately approval-gated.
ARM/paid hostedMac remain explicitly deferred/external.
[Exact source, test counts, immutable artifact SHA256, backup/rollback and pending decisions](INTEL-RELEASE-20261029.md).
The existing architecture and modules above are not replanned.
