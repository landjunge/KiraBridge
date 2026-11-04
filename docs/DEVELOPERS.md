[Deutsch](DEVELOPERS.de.md) · [README](../README.md)

Current status: [RC30, published and installed](RC30-HOTPATHS-20261103.md),
source pin `2d540ee05f945efdd2330b46a1a65a4b94bcb482`. Dated release claims
in the retained guide below describe RC20.

# KiraBridge: development and operations

## Source and release

The newest published download is the Intel preview
[0.8.0rc20, dated October 30, 2026](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20),
source pin `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4`. The READMEs describe that published download. A working branch and the installed
service can have different source versions. This documentation update does not
integrate unpublished application changes.
[Verification report and claim evidence](README-REVIEW-20261031.md).

RC18 remains an older published preview. RC17, RC16 and RC15 are drafts, with
historical evidence retained. Check the GitHub release, artifact source pin and
responding installed service independently.

## Architecture and interfaces

MCP and CLI share the Bridge core. The task manager persists tasks and outcomes
in SQLite. Separate managers own files, processes, agents, visible sessions and
permissions.

- [Architecture](ARCHITECTURE.md) and [development plan](DEVELOPMENT_PLAN.md)
- [Complete file/log reads](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/READ-FULL-FILES.md) and [file transfer](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/FILE-TRANSFER.md)
- [Queue contract](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-MANAGEMENT.md) and [direct admission](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-DIRECT-ADMISSION-20261029.md)
- [Optional ThreadDesk integration](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/DYNAMIC-THREADDESK-PROXY.md)
- [Bounded Whiteboard continuation](plans/BIGPLAN-AUTONEXT-20261104.md): operator-pinned READY tasks, acceptance receipts and activation gates; disabled by default.
- [RC20 changes at the published source pin](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc20/docs/RELEASE-0.8.0rc20.md)

These detailed documents contain dated operational observations. Their old version
statements do not replace current release or service evidence.

## Configuration

Configuration and separate credentials normally live in `~/.config/kirabridge/`.
Policy controls principals, operations, file roots, agent adapters, visible target
bindings and optional integrations. The actual operation catalog and the concrete
permission decision determine availability. A module name alone proves neither
an installed adapter nor permission. [ChatGPT connection](CHATGPT.md).

Do not overwrite unrelated profiles or shell paths. Existing KiraBridge secrets
remain in place until a separately authorized, verified migration is available.

## Task safety

Authorization, admission, attempted input, confirmed delivery and results are
separate states. `unknown` is not safe to resubmit; `blocked` is not permission to
bypass a guard. Do not blindly resend historical messages, clear queues or kill
agents to force installation.

Terminal guards check current identity and readiness. Busy targets, changed
selection and uncertain input produce concrete failures. Saved results do not
automatically wake an inactive chat. Keep private tokens out of commands, logs
and Git. Installation does not grant additional OS permissions.

## Troubleshooting

| Observation | Next step |
| --- | --- |
| Release or download unavailable | Check authentication, repository access and published/draft status. |
| Checksum mismatch | Stop and check the original artifact before execution. |
| `visible_target_busy` | Inspect the protected handoff reservation and its actual outcome. |
| `session_busy` | Inspect current work; do not interrupt a running agent. |
| `session_selection_changed` | Read fresh window/tab/TTY/PID identities; do not replay the old request. |
| `unknown` or lost response | Reconcile existing receipt, start, acknowledgement and late-reply evidence. |
| Installer reports `BUSY` | Let actual work finish; do not bypass guards. |
| Start or rollback times out | Read logs, health and the responding version before claiming success. |

[Repair evidence](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-DIRECT-ADMISSION-20261029.md) · [Intel report](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INTEL-RELEASE-20261029.md)

## Tests and builds

Use isolated worktrees and local backups for risky changes. Use relevant synthetic
stores, fake terminal I/O and actual local MCP roundtrips. Keep review, merge,
publication and productive installation as separate decisions.

The deterministic `scripts/build_release.py` requires a clean, exact Git commit;
two builds must produce identical SHA256SUMS. `scripts/accept_macos_release.py`
performs real installation, upgrade, start, idempotency, restart, KeepAlive,
rollback and fresh-install checks under a separate test label. It is not a dry run:
never give it production paths, and independently confirm cleanup afterwards.

Source checks follow `pyproject.toml`, `uv.lock` and [the CI workflow](../.github/workflows/ci.yml):

```sh
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -W error::pytest.PytestUnraisableExceptionWarning
uv build
```

Run only tests needed for the change. Integration cases need the workflow's pinned
external sources through `KIRABRIDGE_TEST_THREADDESK_SOURCE` and
`KIRABRIDGE_TEST_TOLLGATE_SOURCE`. Missing optional sources do not establish an
integration pass. Documentation validation needs no productive service.

## Operation, updates and recovery

The [installation guide](INSTALL-EN.md) and [macOS contract](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INSTALL-MACOS.md)
contain status, log and rollback commands. The launchd user service survives closing
the app, Terminal or browser. Default data, runtimes, backups and logs live under
`~/.local/share/kirabridge/`, with the versioned installation under `install/`.
The actual configured paths remain authoritative.

The updater checks ownership, idle state, integrity and the responding new service.
It preserves configuration, credentials, permissions, database and user files.
Rollback must use its matching transaction and be confirmed by the responding old
version; never overwrite newer results with an old database. Checksums from the
same release detect corruption but do not replace an independent publisher signature.

Historical evidence: [RC18 publication and installation](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC18-PUBLISH-INSTALL-20261029.md),
[Intel report](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INTEL-RELEASE-20261029.md), [RC14 rollback](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC14-ROLLBACK-20261026.md).
RC20 publication does not establish ARM, macOS 26, hosted macOS CI or every
ChatGPT Live/Voice workflow.
