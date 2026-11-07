[Deutsch](DEVELOPERS.de.md) · [README](../README.md)

# KiraBridge: development and operations

## Source and release

Reviewed November 7, 2026: the repository baseline `d12838ae97c7efcc053c45c3bc9fba5e78f5fe5d`
declares `0.8.0rc40` in `pyproject.toml`, `uv.lock` and the Python package.
The installed Intel runtime reports that source pin. The newest published Intel
download is still [RC36](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36),
source `d4aebdd89a206045731f2692a3f363fddaa15ee0`. Its authenticated installer
download matches both GitHub's digest and `SHA256SUMS`.
[Verification, sources and remaining limits](evidence/readme-current-20261107.json).

The separate [Windows setup preview](WINDOWS-SETUP-20261104.md) is `0.8.0rc37.dev1`;
it does not establish feature parity or a Windows service installer. Current
Windows/installer and Linux/Debian server work remains separate from those downloads.
RC17, RC16 and RC15 remain drafts. Check release state, artifact source and the
responding service independently; a version string alone does not identify a build.

## Developer quickstart

Use Git, Python **3.11 or later** (`requires-python`), and uv; CI pins uv **0.11.6**.
Cloning this private repository requires GitHub access. In a separate checkout:

```sh
git clone https://github.com/landjunge/KiraBridge.git
cd KiraBridge
uv sync --locked --dev
uv run --locked kirabridge --version
uv run --locked kirabridge --help
```

The last two commands print version/help without configuring or starting a service.
`uv sync` creates this checkout's `.venv`; it does not update an installed KiraBridge.
Runtime dependencies are MCP, HTTPX and Uvicorn, plus Cryptography on Intel macOS.
The dev group adds pytest, pytest-asyncio and Ruff. Exact resolutions are in `uv.lock`.

| Directory | Purpose |
| --- | --- |
| `src/kirabridge/` | Python core, CLI, MCP gateway, managers and platform adapters |
| `tests/` | Unit, contract and integration checks |
| `installer/` | Versioned installation, update and rollback |
| `scripts/` | Packaging, native acceptance and CI helpers |
| `docs/`, `examples/`, `integrations/` | Contracts, examples and optional integrations |

## Architecture and interfaces

MCP and CLI share the Bridge core. The task manager persists tasks and outcomes
in SQLite. Separate managers own files, processes, agents, visible sessions and
permissions.

- [Architecture](ARCHITECTURE.md) and [development plan](DEVELOPMENT_PLAN.md)
- [Complete file/log reads](READ-FULL-FILES.md) and [file transfer](FILE-TRANSFER.md)
- [Queue contract](QUEUE-MANAGEMENT.md) and [direct admission](QUEUE-DIRECT-ADMISSION-20261029.md)
- [Optional ThreadDesk integration](DYNAMIC-THREADDESK-PROXY.md)
- [Bounded Whiteboard continuation](plans/BIGPLAN-AUTONEXT-20261104.md): operator-pinned READY tasks, acceptance receipts and activation gates; disabled by default.
- [Published RC36 changes](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc36/docs/RELEASE-0.8.0rc36.md)

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

[Repair evidence](QUEUE-DIRECT-ADMISSION-20261029.md) · [Intel report](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INTEL-RELEASE-20261029.md)

## Tests and builds

Use isolated worktrees and local backups for risky changes. Use relevant synthetic
stores, fake terminal I/O and actual local MCP roundtrips. Keep review, merge,
publication and productive installation as separate decisions.

The deterministic `scripts/build_release.py` requires a clean, exact Git commit;
two builds must produce identical SHA256SUMS. `scripts/accept_macos_release.py`
performs real installation, upgrade, start, idempotency, restart, KeepAlive,
rollback and fresh-install checks under a separate test label. It is not a dry run:
never give it production paths, and independently confirm cleanup afterwards.

For a code change, synchronize the locked dev environment, then run Ruff and
only the relevant existing test files (replace the path with the affected test):

```sh
uv sync --locked --dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q tests/test_cli_support.py -W error::pytest.PytestUnraisableExceptionWarning
```

Documentation-only changes need scoped link, Markdown, translation and example
checks; they do not require a product build or a local whole-suite run.
The [Verify workflow](../.github/workflows/ci.yml) still performs its required
lint, tests and `uv build` on push/PR. Automatic jobs use the existing self-hosted
Linux runners for Python 3.11/3.13; hosted macOS and package workflows require manual
selection. [CI selection, costs and platform limits](CI-COST-GATES-20261106.md).


The initial November 7 [PR71 verification](https://github.com/landjunge/KiraBridge/actions/runs/42365946670)
failed on expired routing-test fixtures, with additional Python 3.13 errors.
The existing, independently reviewed fixed test clock from the server branch is
now reused; production freshness checks and real process timeouts are unchanged.
[Current PR checks](https://github.com/landjunge/KiraBridge/pull/71/checks) remain
the integration gate. [Original failures, focused checks and source pins](evidence/readme-current-20261107.json).

Full integration reproduction needs `uv sync --locked --dev --group remote-ci`
and the exact external checkouts below. CI uses `scripts/ci_remote_tests.py`
in separate fresh legacy and remote processes, binding imports, pins and results:

| Lane | Sources and environment |
| --- | --- |
| Legacy | ThreadDesk `770bbc9f0c0a02699cc93cad47d2e2c3782f7080`, `KIRABRIDGE_TEST_THREADDESK_SOURCE=<checkout>/src`; TollGate `53fc57cc2e082d022e65e5929cb2a1e186fba852`, `KIRABRIDGE_TEST_TOLLGATE_SOURCE=<checkout>` |
| Remote R2/R3 | ThreadDesk M4 `a0dd4c39478b031e0e31d335c2a15435dfbc52eb`; both `KIRABRIDGE_TEST_THREADDESK_SOURCE` and `KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE` point to its `src/`; no legacy TD/TollGate imports |

See the workflow's exact `PYTHONPATH`, temporary/report directories and helper
arguments, plus the [remote CI pin gate](REMOTE-CI-PIN-GATE-20261106.md).
Missing optional sources or skipped checks do not establish integration acceptance.
Documentation validation needs no productive service.

## Operation, updates and recovery

The [installation guide](INSTALL-EN.md) and [macOS contract](INSTALL-MACOS.md)
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
RC36 publication does not establish ARM, macOS 26, hosted macOS CI or every
ChatGPT Live/Voice workflow.
