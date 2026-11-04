# Windows RC33 installer work journal — 2026-11-04

Final status: exact offline Setup.exe built and locally accepted on Windows 11 x64 through the composite evidence below. First install, reinstall, version guards, runtime/authentication, rollback, configuration UI and final uninstall/data retention are evidenced. The three old instances are unchanged. No main merge or release publication. See [native acceptance](reviews/windows-installer-native-20261104.md) and [structured evidence](evidence/windows-installer-native-20261104.json).

## Scope and isolation

User requests a complete friendly Windows Setup.exe/MSI, isolated branch/worktree,
existing macOS work/sessions/VM/installations/uncommitted changes preserved; tests
before commit/push; publication only after evidenced acceptance.

Own worktree: `KiraBridge-worktrees/windows-installer-rc33-20261104`, branch
`feat/windows-installer-rc33-20261104`, base GitHub main
`ad6b4585ef897548dd039b2fec23122b1a57d984` (fresh ls-remote).
RC33 tag remains `ce0687dd8831dae261bf285922a146bcf3aedc41`.
Published Windows kit SHA256:
`1002e68cbef96c7fd9a383d542beb5abc727f5843316352a65638fe4266a919a`.
Existing main checkout contains uncommitted work and was read only. No source,
installation or configuration changes in macOS worktrees are authorized here.

## Investigation / decisions

- Existing RC33 kit has 174 runtime modules and six native phase receipts, offline
  wheels and Python 3.14.10 installer. A dev kit is not an end-user installer.
- Existing preview has explicit state-dir/port, preserved credentials and private
  native Windows ACLs. No service/autostart or general file/process tools.
- Use Inno Setup, per-user x64 Setup.exe; offline private CPython embeddable runtime,
  no Python vendor installer registration, PATH or file-association modifications.
- Stage and validate immutable releases, switch a pointer atomically, retain previous
  releases for rollback. Busy owned runtime blocks upgrade/removal; do not kill
  existing processes. Data/configuration outside application survive removal.
- Existing Windows dev2/dev3/RC33 ports 8765–8767 must remain untouched. Tests use
  own application/data roots, registration identity and unused port.
- CI workflow triggers push/pull_request on all platforms; eventual commits use
  documented skip-ci marker. No CI or ARM build requested or started.

## Team and work in progress

Packaging/build specialist, VM access/test specialist and lifecycle/launcher reviewer
work independently; root implements transaction/runtime lifecycle. VM lane belongs
exclusively to VM specialist. No release approval inferred from prior RC33 acceptance.

ThreadDesk existing whiteboard `188ce4729a62` was read through authorized connector.
Tests, build artifact, native acceptance and independent review remain pending.

## Implementation checkpoint

Separate immutable runtime release plus tracked maintenance interpreter avoids
Windows DLL self-deletion during uninstall. Application-wide OS lock prevents
simultaneous run/install/remove; persistent transaction marker blocks a new
launch between installer stages. Uninstall removes only inventoried application
files, preserving unexpected user-added files and all external data.

Upstream references checked during implementation:
[Inno installation order](https://jrsoftware.org/ishelp/topic_installorder.htm)
confirms fallible work in `[Run]` is too late for built-in rollback; commit is
therefore attached before Inno finalizes the uninstall log, with explicit pointer
rollback on failed setup. [CPython embeddable package](https://docs.python.org/3.14/using/windows.html#the-embeddable-package)
provides an isolated private distribution; all dependencies are vendored from
the fixed RC33 wheelhouse, without running pip or a global Python installer.

Whiteboard progress entry `4813e6d2fd2b` / ordinal 146 was independently read back.
An earlier append using unsupported actor_type `agent` was rejected with
`invalid_arguments: Whiteboard actor type is invalid`; corrected to `codex`,
with the same stable external key. No uncertain write was replayed.

## Host validation

- 70 focused builder + existing Dev-Kit guard cases passed (2.94s).
- 34 separate lifecycle tests passed; first-install/reinstall, upgrade/rollback,
  interrupted copying and committed recovery, busy locks, malformed config,
  downgrade and malicious path rejection, preserved user data/untracked files.
  These use injected runtime smoke where Windows execution is unavailable;
  they are not native Windows acceptance.
- Ruff/check and format, PowerShell AST and git diff whitespace checks passed.
- Real stage assembled from exact fixed kit/Python inputs: 38 original offline
  wheels, 2,280 runtime files; release `a0b8eaa2127c48a2a70d90e59064a5f4`.
  Lifecycle source SHA256
  `11c8109173d89a360c316638960e299b74cf9f1b6faf3269ffcdfe7e22767eb3`.
- New private guest observer confirmed all three existing live process generations,
  listener ports and module counts (dev2 171, dev3 173, RC33 174). No compiler was
  installed. A pinned portable Inno compiler is staged only for this task.

Native Setup compilation and end-to-end installation tests are still pending.
No commit/push/release yet. Existing corrupted same-release runtime files are
refused safely rather than automatically repaired; untracked application files
are intentionally retained and can prevent same-path reinstallation until moved.

Root independent lifecycle rerun initially used a shared interpreter without this
worktree's source on its import path: 14 failed/20 passed (`ModuleNotFoundError`).
This was a test invocation error, not native evidence; corrected command is
`PYTHONPATH=src <test-python> -m pytest tests/test_windows_installer_lifecycle.py -q`.
Corrected independent lifecycle invocation passed all 34 tests in 1.41s. A final
shared Setup/Uninstall mutex guard adds one focused passing contract case
(19 new builder guards total; 105 distinct local cases including Dev-Kit guards).
The named mutex covers this user's Windows session. Concurrent maintenance of
the same per-user installation from separate Windows logon sessions is outside
this acceptance scope.

## Frozen native candidate

Final stage03 ZIP: `4809a086e2842d6e00f999b60d47fdf215d353adf4eb22ae4bf92683f0f0fe12`,
30,505,979 bytes; final setup script:
`7f2669a0eabf714833b9541e3b17bec59fba6a9e64b6659533cca5b56ab156f9`.
Includes one shared Setup/Uninstall mutex and exact generated lockfile removal;
no recursive/wildcard deletion of application data. Runtime bytes unchanged.

Native plan now tests the actual production AppId and exact intended Setup.exe
bytes, only after asserting that registration is absent. Explicit new app/data
roots and Start-menu group isolate the test from all three existing Dev Kits;
the test restores the new product registration to absent. A synthetic prior
version pointer tests version gating; it is not a claim of real Windows RC32
binaries or migration from a previously released Windows Setup.

## Reproducing the build

On macOS/Windows with Python 3.11+, stage the fixed downloaded inputs:

```sh
python scripts/build_windows_installer.py --kit /path/to/KiraBridge-0.8.0rc33-Windows-Dev-Kit.zip --python-embed /path/to/python-3.14.10-embeddable-amd64.zip --out-dir /new/stage-directory
```

The builder performs no downloads and refuses an existing output directory.
Compile the staged `setup.iss` with Inno Setup 6.4+ on Windows (the native lane
uses pinned portable 6.7.4). `output/KiraBridge-0.8.0rc33-Windows-x64-Setup.exe`
is the single offline installer. Builder `--iscc` combines staging and native
compilation when running on Windows; host staging alone is never acceptance.

Normal setup uses its stable per-user product identity. `/DataDir=` is optional
and intended for an explicit initial location; an upgrade preserves its existing
data path. For an isolated acceptance run, inspect registry/Start-menu identity
before execution as done by `scripts/accept_windows_installer.py`; `/DIR=` by
itself is not isolation from an already registered installer product.

## Native build / artifact transfer

Official portable Inno Setup 6.7.4 bootstrap verified Authenticode and fixed
vendor digest; its registry footprint remained unchanged. Native ISCC compile
passed (exit 0, approximately 36s). Exact production Setup returned in 24 bounded
immutable chunks and was independently reassembled/hashed on the Mac:

- `KiraBridge-0.8.0rc33-Windows-x64-Setup.exe`, **25,018,593 bytes**.
- SHA256 `41203ce70d31795d7dc1ace80a40a462f5f834c7fea02165544cc3c7f7e83d91`.
- Local artifact directory: `~/KiraBridge-windows-installer-audit-20261104/`.
- This is an unsigned application preview installer. Compiler authenticity does
  not imply a publisher signature on the generated Setup.

Native lifecycle tests are running against these exact production bytes.

## First native lifecycle result (partial, not acceptance)

Exact Setup fresh install exit0; registry/current/version/data and no pending
transaction verified. Native held-mutex fixture caused both competing Setup and
uninstall to refuse (exit1), pointer preserved. Actual same-version reinstall
exit0, pointer and configuration preserved. All three old installations freshly
unchanged after the run.

The harness then failed `JSONDecodeError` while parsing `inspect-start-menu`
(PowerShell itself returned exit0). Own product remains installed for diagnosis;
no test runtime child or desktop-input task was started. Raw native receipt
SHA256 `523ded8b56fad97f9008471cdd7d8c564ebd55a28badd9e30176b7a7d9445342`.
Remaining phases will resume after the precise log/output cause is established;
previous successful installation cases will not be rerun.

Review also found a test-harness timeout hazard on Windows when using PIPE for
GUI Setup descendants. Remaining command logs will go directly to files with a
bounded wait, keeping unknown child states explicit. No product changes are
justified by this harness failure; installer candidate stays unchanged.

Technology choice also considered [WiX MSI/Burn](https://docs.firegiant.com/wix/tools/burn/)
and [NSIS](https://nsis.sourceforge.io/Docs/Chapter1.html). Inno was selected for
the requested single per-user offline executable, language UI and explicit
lifecycle hooks; no separate prerequisite installer chain or enterprise MSI
management requirement is introduced.

The shortcut diagnosis is consistent with official Inno documentation:
[`/GROUP` is ignored when the group page is hidden](https://jrsoftware.org/ishelp/topic_setupcmdline.htm).
This script hides it, so the harness's requested custom group was not effective.
The native continuation must inspect the actual default `KiraBridge` group and
prove its ownership/creation before cleanup. This corrects the test plan's group
isolation assumption; product AppId and program/data path isolation remain valid.

Compiled/partial-native milestone saved as canonical Whiteboard entry
`7ededca11ce6` / ordinal147 and independently read back. No release acceptance
was asserted. A blocked read-only guest diagnostic is being reconciled using
narrow native process/log reads; no global WMI service, VM resources or unrelated
processes are changed to resolve it.

## Shortcut diagnosis resolved

Narrow native diagnostic confirms default `KiraBridge` Start-menu folder created
13:18:05Z inside our fresh-install interval, exactly three new links and all
three targets in the owned acceptance application directory. The failed query
log names the nonexistent requested custom group. This proves both the harness
cause and ownership of the actual group before its later uninstall cleanup.
No installer rebuild or repeated fresh/reinstall/mutex test is needed.

The broad read-only observer was identified by its own PID/creation FILETIME,
separate from the original historical PowerShell. Only this owned diagnostic
may be stopped after fresh process-handle identity validation. No WMI service
or existing Bridge process is targeted. The continuation preserves the original
failed receipt and logs and links its SHA256; it starts at shortcut inspection.

## Native continuation: runtime checks passed

Live continuation progress confirms the correct three Start-menu targets,
shipped PowerShell launcher Status, unused isolated port configuration, real
private runtime startup and HTTP401 without credentials. Authenticated health
reports exactly eight capabilities/five Windows operations and zero tasks.
Busy upgrade and busy uninstall refuse while the exact owned runtime stays
alive with its original credentials/pointer. Owned runtime was then stopped
and independently absent. No desktop-input task was submitted.

Malformed-config refusal, version fixtures, transaction recovery and full
uninstall/reinstall preservation are still running. Candidate source/bytes
remain unchanged; native full acceptance is not yet asserted.

## Post-uninstall discrepancy: direct root reconciliation

Root took over the VM input lane after the diagnostic stalled. All guest events
remained exact-UUID guarded, guest-only, no host focus/clipboard. A fresh display
showed the owned second tab idle; original first tab untouched. Three short
read-only commands were visually checked before one Return each.

Fresh observed state: current.json, launch.cmd, unins000.exe and actual Start-menu
group all absent. Configuration, credential and user-file hashes equal the
saved baseline. SQLite base-file hash differs. Read-only native SQLite queries
then confirmed `quick_check=ok`, the exact original `RC33 data sentinel` row,
and zero tasks. Screenshots remain private under the installer audit directory.

The harness used `with sqlite3.connect(...) as db`, which commits/rolls back but
does not close the connection. Its WAL-dependent base-file hash was not a stable
closed-database baseline. Root independently reproduced the same hash change
on connection close with the row preserved. The test must close its connections
before snapshots. This does not establish which short-circuited predicate first
failed in the old aggregate assertion; that historic failure remains retained.
The new continuation verifies actual absence plus logical database integrity,
records the old baseline limitation and captures a new closed-file baseline.
No installer/runtime code or candidate bytes are changed by these test fixes.

## Final acceptance and cleanup

Final independent read-only receipt SHA256 `fe42a6b1fb77e7397b6be55503d3172b1c7072861400e44684a514b327a6af90`: passed=true. Root final uninstaller exit0 after separate log; four retained-file hashes equal the closed baseline, SQLite integrity/sentinel/zero tasks correct, both registry views and Start-menu/program references absent, three prior instances unchanged. A harmless empty test app directory and the intentionally retained test data remain.

Settings form displayed correct endpoint/port/data folder and cancelled normally. Earlier failed receipts remain failed; native acceptance is composite. Test infrastructure corrections include the ignored group override, SQLite connection/WAL baseline and stdout/Inno log collision; product bytes remained unchanged.

Own guest test tab closed from its confirmed idle prompt, independently observed absent with original tab preserved. All eight own host helpers stopped and independently absent. VM remains running; no productive deployment, macOS modification, hosted CI or ARM build.
