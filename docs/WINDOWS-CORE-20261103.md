# Windows core startup groundwork · 3 November 2026

This component is developed from main `21a6abd` in an isolated worktree. The
installed macOS RC30 service, its configuration, credentials and sessions were
not changed. This is source groundwork, **not Windows native acceptance**.

## Implemented

- Windows private state uses the current process token SID and native security
  descriptors. New files/directories receive a protected DACL granting the
  current user and LocalSystem access. Existing objects are never silently
  re-ACL'd: their owner must be the current user, and allow ACEs may name only
  that user, LocalSystem or the privileged Administrators group. Broader or
  unsupported ACLs fail closed.
- Native opened-handle checks reject reparse points, redirected final paths,
  wrong object kinds and hard-linked private files. Existing ancestor junctions,
  UNC/device paths, alternate data streams and parent traversal are refused.
  Non-inheritable handles are used. These are Windows state-file checks, not a
  replacement for the still-POSIX public file-root traversal adapter.
- The dispatcher and EventJournal initialization use an exclusive native file
  handle. Contention reports `already_running`; no PID census or process killing
  is involved. EventJournal initialization retains its bounded wait. The POSIX
  lock path is unchanged.
- Credentials, the task database and any existing SQLite WAL/SHM sidecars use
  native owner/DACL checks before access. New SQLite sidecars inherit from the
  private directory. Windows event imports no longer require `fcntl`.
- Process-output storage can be constructed during Windows keyboard/MCP startup
  without entering POSIX descriptor traversal. Every output capture/read remains
  explicitly unavailable on non-POSIX platforms. Secure Windows process spawning,
  job-object ownership and public file operations are **not implemented** here;
  no unprotected `subprocess` fallback was added. Keyboard profile storage is
  already lazy and remains unavailable pending its native adapter.

The Win32 file-security API contract is documented by
[Microsoft](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights).
Windows APIs are loaded lazily; importing these modules on macOS has no OS effect.

## Local checks and known baseline test correction

`tests/test_windows_core.py`: **30 passed** on the Intel Mac. They check fixed
Windows ABI widths, ACL/path policy, exact opened-handle metadata rejection,
exclusive lock ownership, secure routing and unavailable output behavior.
An additional focused regression passed for preserving CreateFileW error32
before security-descriptor cleanup can change the native last-error value.

A relevant run of Windows policy tests, event journal, process output and local
credential/stdio integration initially reported **98 passed, 4 native skips,
1 failed**. The failure was an old automatic-submit assertion requiring `queued`;
RC29/30 can legitimately return `completed` inline. The exact case also failed
on untouched main `21a6abd`. Only that assertion was updated to accept live or
completed automatic states, preserving manual `created` and eventual completion
checks. The affected manual/automatic cases then both passed (**2 passed**).
Already-passed regression tests were not repeated. Ruff check/format and diff
whitespace checks passed for changed files.

`tests/test_windows_core_native.py` contains **four real-Windows tests**, skipped
on macOS: private creation/read and hardlink rejection; second-process runtime
lock exclusion/release; refusal of an intentionally broadened fixture ACL; and
actual SQLite/EventJournal startup/restart. Run inside the owned Windows guest:

```powershell
$env:PYTHONPATH = 'src'
python -m pytest -q tests/test_windows_core.py tests/test_windows_core_native.py
```

The guest results, complete Windows Bridge/MCP startup and native keyboard
acceptance remain pending integration. Mocks or macOS skips must not be reported
as Windows success. Native process execution and filesystem tools remain explicit
unsupported capabilities until their own security adapters pass guest tests.
