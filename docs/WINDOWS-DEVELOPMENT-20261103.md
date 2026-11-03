# Windows development preview on the Intel Mac

The operator explicitly requested a Windows version with genuine keyboard tests
inside a separate VM. This is a Windows development task, overriding the usual
Kira rule against preparing unused Windows packages. The working macOS RC30
installation and other sessions remain in place. No hosted CI/Actions or ARM
build is used. Starting point: main `21a6abd`.

## Implemented scope

The preview version is `0.8.0rc31.dev1`. It shares the existing MCP, authorization,
SQLite task state and idempotency core. Windows operation names are explicit:

- `windows.keyboard.inspect`: observe the current interactive foreground target.
- `windows.keyboard.sequence`: send up to 32 genuine key representations to that
  exact target under one durable task. Every repeat checks the target and policy.

The target includes HWND, PID, process creation FILETIME, UI thread and keyboard
layout. Opaque 64-bit values cross JSON as canonical decimal strings to preserve
identity through JavaScript clients. macOS key codes and target tokens are never
reinterpreted as Windows data. Missing inspection permission prevents submission.

Sequences support named Windows keys, physical scan codes and layout-specific
character labels with explicit modifiers. Unicode packets are a separate option
and are explicitly marked nonphysical. No clipboard or host-input substitute.
The backend never activates another window or guesses which modifier to release.
Foreground/input-desktop and held-key guards run before each native call.
Successful SendInput insertion is not an application acknowledgement; independent
receiver events are required for acceptance. A focus race remains because Windows
does not offer atomic HWND-bound SendInput.

A monotonic deadline is checked before input, at every pair and after native
return. Synchronous OS calls cannot be preempted; a late return cannot claim
success, and no subsequent key is posted after observed expiry. An attempt with
an uncertain effect retains its original task ID and is never automatically
replayed. A known stale foreground is rejected before marking execution running.

Windows state uses protected current-user/SYSTEM ACLs and native exclusive file
handles for runtime/journal locks. Existing private files are verified instead of
silently changing their ACL. SQLite WAL/SHM files are checked when already present;
the actual guest must validate inheritance. Use a local protected user directory,
not UNC, OneDrive junctions, hostile writable parents or DOS8.3/SUBST aliases.
Path-based SQLite reopen is not claimed to resist a hostile parent path swap.

This is **not yet a full Windows desktop/terminal port**. Public file-root tools,
managed process execution, terminal agents and macOS profiles/system keys remain
unsupported. They do not acquire fake success through POSIX fallbacks.
`platform.status` identifies the Windows preview and its actual operation subset.

## Environment and provisioning

Host observed: Intel iMac17,1, i5-6500, four cores, 32 GiB RAM, macOS15.7.4,
hardware virtualization available. Fusion13.0 was already installed; the official
current updater requires Broadcom portal access. It remains untouched.

UTM5.0.8 was obtained from its official GitHub release, SHA256
`7b2d7b2e2a02b3de1757ef19a8f36573e6d9cceae8c8cca0abcbcaa4a852019a`,
304304581 bytes. Deep signature verification and notarization assessment passed
for Developer ID Turing Software, LLC (`WDNLXAD4W8`). Installed in the user's
Applications directory, without root, a host daemon or permission changes.

The dedicated VM plan uses two CPUs, 8 GiB RAM, a new sparse 80-GiB QCOW2 disk,
UEFI, virtual TPM and prepared Secure Boot variables. Guest disk0 is the new VM
disk only. Clipboard, USB forwarding and host shared directories are disabled.
Only new owned target paths are accepted. No existing VM/disk is overwritten.
The real bundled signed qemu-img checked an own new test image with zero errors;
this is not Windows boot acceptance.

The Microsoft German x64 Enterprise evaluation has a 90-day term. Published ISO
SHA256: `d67c5606ab6ab3f2c7a7d3eb7c66387d03714427236fd5930e3734d50716d9df`,
8283936768 bytes. The download must finish and match before VM creation/boot.
The i5-6500 host is outside the regular Windows11 supported CPU generations:
a development VM is not certification of supported Windows11 hardware.

Python3.14.10 AMD64 installer comes from python.org, SHA256
`92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965`.
Its dependencies were resolved for Windows CPython3.14, then downloaded as
37 binary wheels and checked for target-specific dependency closure. This avoids
host-marker errors (notably pywin32/colorama and old asyncio backports).
The guest installs into its own user profile, without changing the host or PATH.

The seed starts a visible interactive local test account after setup. A host
server binds only loopback, serves a fixed hash-checked file manifest through
the VM's user-network alias, and accepts bounded reports under an unlogged random
capability path. No host credentials or project folders are shared. Each native
test has an exclusive durable pre-attempt receipt; old reports must match the
exact manifest and phase. An uncertain or failed test blocks subsequent input.

## Verification so far

- 45 injected Win32 keyboard contract/ABI tests passed; these are not native tests.
- Windows state/ACL routing and relevant POSIX regressions passed. One old
  automatic-submit assertion also failed on untouched main: RC29 can immediately
  return completed. The narrow assertion was corrected and both cases passed.
- 13 VM-provisioning tests and 7 real local HTTP staging-boundary tests passed.
- 72 relevant MCP/RC29/task/manager integration tests passed.
- Root manager tests cover exact identities, authorization before persistence,
  completed/unknown task reuse, stale target and both native deadline edges.
  The final manager round passed19 cases; the added Windows status case passed.
- Real local HTTP/MCP with an injected receiver passed 11 toolcalls, unchanged
  completed-task replay and no-input rejection controls. This is protocol-only.
- Native guest acceptance is **pending**. Its scripts reserve evidence before any
  effect and must run in the actual interactive guest:
  `tests/test_windows_core_native.py`, `scripts/accept_windows_keyboard.py` and
  `scripts/accept_windows_mcp.py` and `scripts/accept_windows_preview.py`.

The preview also has a persistent user-run entrypoint documented in
[WINDOWS-PREVIEW.md](WINDOWS-PREVIEW.md). After all guest checks succeed, setup
places `KiraBridge Windows Test.cmd` on the owned guest desktop. It starts the
loopback authenticated MCP in an ordinary visible console, using the exact
prepared Python installation; no Windows service or host process is installed.
An existing modified desktop launcher is preserved.

No Windows boot, native keyboard pass, downloadable Windows release or complete
Windows port is claimed by these preparatory results. The running Mac remains
the previously verified RC30 release. Native results and installation identity
will be appended after the actual guest run.

## Primary references

- [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [Microsoft KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)
- [Windows11 VM requirements](https://learn.microsoft.com/en-us/windows/whats-new/windows-11-requirements)
- [Microsoft evaluation download](https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise)
- [Microsoft ISO verification](https://support.microsoft.com/en-us/servicing/os/windows/docs/2026/09/verify-the-authenticity-of-a-windows-11-enterprise-evaluation-iso-file)
- [UTM5.0.8 release](https://github.com/utmapp/UTM/releases/tag/v5.0.8)
- [UTM scripting](https://docs.getutm.app/scripting/cheat-sheet/)
- [Python3.14.10](https://www.python.org/downloads/release/python-31410/)
- [Core details](WINDOWS-CORE-20261103.md) and [bootstrap review](WINDOWS-BOOTSTRAP-REVIEW-20261103.md)


## First real Windows installation: failure and correction

The first guest installed Windows but failed in `oobeSystem` before any KiraBridge
acceptance or first logon. Read-only Panther logs prove error `0x80220005` at
`Microsoft-Windows-Shell-Setup/FirstLogonCommands/SynchronousCommand/CommandLine`.
The original automated launcher was1454 characters; Microsoft limits this field
to1024. This was our provisioning error, not evidence against the Windows keyboard
backend. The failed VM, disk clone and original logs were preserved; diagnosis
mounted only an own converted disk image read-only. UTM HVF cannot save a RAM
snapshot here; temporary CPU pause succeeded and the failed VM was later stopped.

The fix moves the full detached launcher into UTF8-BOM `first-logon.ps1` on the
installation seed. The short entry is426 characters and a hard guard rejects
future oversize values before creating a VM. The moved script still returns
without waiting; Explorer polling runs only in the detached bootstrap. Fifteen
focused seeder tests passed. Independent PowerShell execution of the actual
helpers confirmed one detached child, correct copy into a path with spaces and
exit0. New VMs may use distinct bounded names, preserving the failed attempt.
No uncertain Windows keyboard task was repeated: none had started.

[Actual first-install failure proof](evidence/windows-first-install-failure-20261103.json)
· [Microsoft CommandLine limit](https://learn.microsoft.com/en-us/windows-hardware/customize/desktop/unattend/microsoft-windows-shell-setup-firstlogoncommands-synchronouscommand-commandline).
