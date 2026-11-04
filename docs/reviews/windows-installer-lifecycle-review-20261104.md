# RC33 Windows installer lifecycle review

Reviewed on 4 November 2026 in the isolated installer worktree, based on
`ad6b4585ef897548dd039b2fec23122b1a57d984`. The existing worktrees, Windows VM,
running processes and installations were only described from source/evidence;
this review did not modify them. Existing ThreadDesk Whiteboard
`188ce4729a62` was read successfully without switching the active thread.

## Existing runtime contracts

- `kirabridge.windows_preview` accepts `--transport http|stdio`, `--state-dir`
  and `--port` (1024–65535). It has no configuration-file argument or public
  shutdown endpoint. HTTP binds only `127.0.0.1`; startup does not send input.
- Startup creates or reuses `preview-credentials.json` and persistent state.
  Malformed credentials are refused and preserved, never silently rotated.
  Unknown tasks must remain available for reconciliation; no automatic replay.
- Private state uses owner/DACL/reparse/hardlink checks. New directories receive
  protected current-user/SYSTEM access; existing unsafe ACLs are refused rather
  than repaired. An installer must not precreate state with ordinary inherited
  permissions and then expect the runtime to repair it.
- The runtime holds its state lock and releases resources through async cleanup.
  A visible console supports deliberate user shutdown. Upgrade/uninstall should
  refuse a busy managed runtime instead of terminating unrelated Python or
  KiraBridge processes.
- Published RC33 is already separately installed on port 8767, with
  `KiraBridgePreviewRC33` state. The normal installer needs distinct initial
  state, port and install paths; test fixtures require another explicit namespace.
  Earlier dev2/dev3/RC33 installs remain independent rollback resources.

## Installer recommendations and boundaries

Use an immutable offline runtime per release, with a small current-release
pointer and persistent data outside the program directory. Validate payload
hashes/imports before changing the pointer; hold a lifecycle lock, preserve the
previous pointer and fail closed on incomplete transactions. Keep configuration,
credentials and SQLite files during upgrade and ordinary uninstall. Do not
restore a database backup automatically after a later runtime has used it.
Version comparisons must explicitly prevent downgrade; display `AppVersion`
alone is insufficient. Program uninstall should remove only files it owns.

Avoid invoking the normal Python installer on the user's existing Python
installation. Disabling PATH/launcher/associations does not by itself make MSI
registration independent. A copied, self-contained build runtime avoids that
runtime installation dependency, provided offline dependency and native import
checks pass on Windows.

Inno Setup is suitable for a per-user wizard, Start menu and uninstall entry.
Stable `AppId` and `UsePreviousAppDir` identify an existing installation.
[Official installation order](https://jrsoftware.org/ishelp/topic_installorder.htm)
places `[Run]` after finalization of the uninstaller: errors then do not roll
back earlier installation changes. A fail-prone bootstrap in `[Run]` therefore
needs its own transaction; do not claim automatic rollback for it.
[Event documentation](https://jrsoftware.org/ishelp/topic_scriptevents.htm)
defines `PrepareToInstall` as the preinstallation prerequisite/error boundary.

## Launcher and configuration implementation

As requested by root after the review, this agent implemented only:

- `installer/windows/launch.cmd`
- `installer/windows/configure.cmd`
- `installer/windows/windows_launcher.ps1`

The command wrappers use the explicit Windows system PowerShell executable,
disable profiles/delayed expansion, set a deterministic working directory and
preserve the child exit code. The helper validates the local non-reparse
installation path and bounded `current.json`; release IDs contain only hex.
It executes the fixed release's `Runtime/python.exe` and `windows_lifecycle.py`
with argument arrays and isolated Python flags. It evaluates no generated code.

The visible runner invokes `run --install-dir`. The WinForms configuration
dialog reads public `status` JSON (`port`, `data_dir`), accepts only a port in
the supported range, and calls `configure --install-dir --port`. Cancellation
does not save. A failed save leaves the dialog open with a bilingual message.
Neither helper starts a service, edits credentials or selects existing VM
instances. Root owns the lifecycle implementation and actual native acceptance.

Validation performed here: PowerShell AST parsing using the existing local
`pwsh` succeeded, and `git diff --check` passed. Native Windows PowerShell 5.1,
WinForms interaction, Start menu invocation and actual lifecycle command
execution still require the Windows fixture. This is not native acceptance.

## Follow-up lifecycle implementation review and fixes

Reviewed root's new `windows_lifecycle.py` and added
`tests/test_windows_installer_lifecycle.py`. The review found that an interrupted
`copytree` could leave no readable destination manifest, preventing rollback.
The implementation now writes the complete owned-file inventory to the durable
transaction journal before creating a release, then copies only the verified
payload entries. Recovery can remove a partial release even if its local
manifest was never written. Cleanup removes only inventoried paths and their
empty parent directories; unrelated files remain.

Other corrections validate metadata types/version/path aliases, reject hidden
directory links before copying, validate journal contents before restoring a
pointer, and validate private configuration before preparing a release. New
data configuration contains only a schema and port: prepare creates neither
preview credentials nor a task database. Unsafe directory ACLs and malformed
settings are preserved and refused. Safe structured bridge error codes remain
visible in the bilingual error output.

The focused suite passed **34 tests** on macOS in 1.40 seconds, using real
temporary-file/lock/private-configuration operations and a deliberately
substituted native runtime smoke. Cases cover fresh install, repeated install,
upgrade, explicit rollback and recovery after commit, missing-manifest partial
copy cleanup, smoke failure, busy-lock refusal, transaction mismatch, downgrade,
corrupt packages/settings/journals, Windows path aliases, directory links,
application/data overlap, port persistence, uninstall/cancel and retention of
data and untracked application files. These tests do not prove Windows DACL,
native imports, Setup.exe execution or GUI behavior. Native acceptance remains
root's separate gate.

Repair boundary: a damaged existing runtime for the same immutable release is
refused rather than repaired in place. Untracked files inside a removed release
remain preserved and can require selecting another installation location when
reinstalling that release. No repair acceptance is claimed.
