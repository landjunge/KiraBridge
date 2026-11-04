# Windows development preview on the Intel Mac

Status on 4 November: native keyboard and guest-local HTTP MCP acceptance passed
for dev2, and the private GitHub release was downloaded and hash-verified. The
final retained installed-instance check is tracked separately below.

The operator explicitly requested a Windows version with genuine keyboard tests
inside a separate VM. This is a Windows development task, overriding the usual
Kira rule against preparing unused Windows packages. The working macOS RC30
installation and other sessions remain in place. No hosted CI/Actions or ARM
build is used. Starting point: main `21a6abd`.

## Implemented scope

The preview version is `0.8.0rc31.dev2`. It shares the existing MCP, authorization,
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
four real guest core tests now pass, including native private-state checks. Use a
local protected user directory, not UNC, OneDrive junctions, hostile writable
parents or DOS8.3/SUBST aliases.
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
8283936768 bytes. The completed download matched before creating the dedicated VM.
The corrected `Fix1` VM booted and ran the native acceptance below; it is retained
for the operator. The first failed installation remains separately preserved.
The i5-6500 host is outside the regular Windows 11 supported CPU generations:
a development VM is not certification of supported Windows 11 hardware.

Python 3.14.10 AMD64 installer comes from python.org, SHA256
`92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965`.
Its dependencies were resolved for Windows CPython 3.14, then downloaded as
37 binary wheels and checked for target-specific dependency closure. This avoids
host-marker errors (notably pywin32/colorama and old asyncio backports).
The guest installs into its own user profile, without changing the host or PATH.

The seed starts a visible interactive local test account after setup. A host
server binds only loopback, serves a fixed hash-checked file manifest through
the VM's user-network alias, and accepts bounded reports under an unlogged random
capability path. No host credentials or project folders are shared. Each native
test has an exclusive durable pre-attempt receipt; old reports must match the
exact manifest and phase. An uncertain or failed test blocks subsequent input.

## Local verification

- 45 injected Win32 keyboard contract/ABI tests passed; these are not native tests.
- Windows state/ACL routing and relevant POSIX regressions passed. One old
  automatic-submit assertion also failed on untouched main: RC29 can immediately
  return completed. The narrow assertion was corrected and both cases passed.
- 13 VM-provisioning tests and 7 real local HTTP staging-boundary tests passed.
- 72 relevant MCP/RC29/task/manager integration tests passed.
- Root manager tests cover exact identities, authorization before persistence,
  completed/unknown task reuse, stale target and both native deadline edges.
  The final manager round passed 19 cases; the added Windows status case passed.
- Real local HTTP/MCP with an injected receiver passed 11 toolcalls, unchanged
  completed-task replay and no-input rejection controls. This is protocol-only.
- Later targeted local rounds passed 84 relevant tests, 3 preview-harness
  regressions and 18 builder/provenance guards. These are separate rounds with
  possible overlap, not a full-suite claim or a substitute for native acceptance.

## Native Windows 11 acceptance, 4 November 2026

The dedicated x64 Windows 11 guest ran Python 3.14.10 and package
`0.8.0rc31.dev2`. The [sanitized native evidence](evidence/windows-native-acceptance-20261104.json)
records actual Win32 events and real guest-local HTTP MCP, without clipboard or
host-Mac input. Native calls are synthetic Windows keyboard events, not physical
hardware. The fixture independently observes application processing; the backend
itself promises only SendInput insertion.

| Phase | Actual result | Measured time and scope |
| --- | --- | --- |
| Core V8 | 4 passed; 0 failed/skipped | 6.57 s, real Windows state/locking/SQLite checks |
| Keyboard V8 | All 9 cases passed; 20 native API calls, 48 received key events | `Stern am`: 8 keys, 18 events, 387.824151 ms; this is the direct native case |
| HTTP MCP V8 | 11 toolcalls; HTTP GET 1/POST 14 including protocol setup | 2988.829027 ms total MCP phase; connect/initialize/catalog 257.131842 ms |
| Preview V9 | Real owned child version dev2, PID 12880; 401 without authentication; health/catalog passed; 0 tasks | 5447.975091 ms, read-only startup/stop smoke with no keyboard request |

Keyboard cases cover eight physical character keys, US/German `y`/`z`, German
umlaut and AltGr, explicit Unicode packets, Return, Backspace, right arrow and F2.
Unicode remains explicitly nonphysical. The right-arrow receiver saw VK 39,
scan 77 and `extended:true` for both down and up after the E0 correction.

The MCP sequence was one task containing 8 real key calls and 18 receiver events,
with exact `Stern am` text and down/up order. Its `task_request` round trip was
185.894018 ms (one sample); no physical-sequence P50/P95 is claimed. Five read-only
health calls measured P50 **23.630937 ms**, P95 **106.133042 ms**, with no warmup
discarded. P95 uses nearest rank: with n=5 it is the observed maximum, not a tail
forecast. Reusing the completed task ID added **0 events and 0 task transitions**;
stale-target and revoked-permission controls each added **0 input events**.

These are guest-local measurements. No external ChatGPT/Voice, connector proxy
or cloud round trip was measured. They cannot establish an improvement over the
earlier 42.504-second Voice test or provide cloud latency percentiles. Inspection,
task submission/readback and health were exercised; general file/process/terminal
performance was not.

V9 reuses the successful V8 core, keyboard and MCP receipts explicitly. The
builder verified byte identity of all 171 runtime Python modules, the original
three harnesses, bootstrap runner, Python installer, requirements and offline
wheelhouse. Only the preview harness was corrected and freshly rerun. Its old V8
failure is excluded from accepted phases. The evidence pins both source/manifest
identities; no input was repeated merely to produce new percentiles or compensate
for a documentation/harness change.

The preview smoke deliberately stopped its own child with CTRL_BREAK; exit 3 and
independent absence of that original process were recorded. PID 12880 therefore
does **not** identify a retained running service. State was preserved, and no
production credentials were used.

The preview also has a persistent user-run entrypoint documented in
[WINDOWS-PREVIEW.md](WINDOWS-PREVIEW.md). After all guest checks succeed, setup
places `KiraBridge Windows Test.cmd` on the owned guest desktop. It starts the
loopback authenticated MCP in an ordinary visible console, using the exact
prepared Python installation; no Windows service or host process is installed.
An existing modified desktop launcher is preserved.

## Published package and remaining installation check

[Windows preview dev2](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev2)
is published in the private GitHub repository, at source/tag commit
`975c6953522cafc2770e4171245bc7f68255117c`. Download requires an authorized GitHub
login; an unauthenticated request returning 404 is expected for this private repo.
A fresh authenticated `gh release download` verified the complete asset and the
included wheel against the prepared guest package:

- `KiraBridge-0.8.0rc31.dev2-Windows-Dev-Kit.zip`: 52598243 bytes;
  SHA256 `28eac747e35f3cd33d5eb05918740a5e1fb234a68e8e9017a43ce10a6878999d`.
- `kirabridge-0.8.0rc31.dev2-py3-none-any.whl`:
  SHA256 `babbde17fc8e23a9fc165fc211fbefbf168b61cfe09ef04ce14713bf223f8479`.

The release bundles the verified Python/dependency payload, not a Windows ISO.
The running macOS RC30 installation is unchanged. The complete Windows desktop
GUI, general file/process/terminal operations, Windows service installation,
Windows 10 and external ChatGPT/Voice integration remain unsupported or untested.
HTTP was exercised natively; stdio is implemented but has no native acceptance
claim here.

**Still open at this documentation snapshot:** start the installed package in its
user-owned console after the release download and independently read back its
version, PID/generation, authorization/capabilities and zero-task state while it
remains running. The stopped preview smoke above does not satisfy that final
installed-running check. The retained VM and durable receipts allow this read-only
verification without replaying keyboard tasks.

## Primary references

- [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [Microsoft KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)
- [Windows 11 VM requirements](https://learn.microsoft.com/en-us/windows/whats-new/windows-11-requirements)
- [Microsoft evaluation download](https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise)
- [Microsoft ISO verification](https://support.microsoft.com/en-us/servicing/os/windows/docs/2026/09/verify-the-authenticity-of-a-windows-11-enterprise-evaluation-iso-file)
- [UTM5.0.8 release](https://github.com/utmapp/UTM/releases/tag/v5.0.8)
- [UTM scripting](https://docs.getutm.app/scripting/cheat-sheet/)
- [Python 3.14.10](https://www.python.org/downloads/release/python-31410/)
- [Core details](WINDOWS-CORE-20261103.md) and [bootstrap review](WINDOWS-BOOTSTRAP-REVIEW-20261103.md)


## First real Windows installation: failure and correction

The first guest installed Windows but failed in `oobeSystem` before any KiraBridge
acceptance or first logon. Read-only Panther logs prove error `0x80220005` at
`Microsoft-Windows-Shell-Setup/FirstLogonCommands/SynchronousCommand/CommandLine`.
The original automated launcher was 1454 characters; Microsoft limits this field
to 1024. This was our provisioning error, not evidence against the Windows keyboard
backend. The failed VM, disk clone and original logs were preserved; diagnosis
mounted only an own converted disk image read-only. UTM HVF cannot save a RAM
snapshot here; temporary CPU pause succeeded and the failed VM was later stopped.

The fix moves the full detached launcher into UTF8-BOM `first-logon.ps1` on the
installation seed. The short entry is 426 characters and a hard guard rejects
future oversize values before creating a VM. The moved script still returns
without waiting; Explorer polling runs only in the detached bootstrap. Fifteen
focused seeder tests passed. Independent PowerShell execution of the actual
helpers confirmed one detached child, correct copy into a path with spaces and
exit 0. New VMs may use distinct bounded names, preserving the failed attempt.
No uncertain Windows keyboard task was repeated: none had started.

[Actual first-install failure proof](evidence/windows-first-install-failure-20261103.json)
· [Microsoft CommandLine limit](https://learn.microsoft.com/en-us/windows-hardware/customize/desktop/unattend/microsoft-windows-shell-setup-firstlogoncommands-synchronouscommand-commandline).

## Further proven corrections during native bring-up

PowerShell 5.1 exposed two bootstrap defects. A redirected `Start-Process
-PassThru` child could lose its native handle before waiting and expose a null
`ExitCode`; the runner now retains the handle and verifies a real Int32 exit code
instead of converting missing evidence into success (`2600f0d`). Quoting every
argument also quoted `cmd.exe` switch tokens. The argument serializer now leaves
simple tokens intact and correctly quotes whitespace, empty arguments and trailing
backslashes (`8544bed`). Separate command/Python exit witnesses were preserved
(`58cb660`); all four real PowerShell 5.1 exit-code witnesses passed before native
acceptance continued.

The V7 named-right-arrow failure was a known input attempt: 19 native API calls
and 46 receiver events had already occurred across that keyboard phase. It was
not a no-input run and was not blindly replayed. A later read-only query of the
installed dev1 mapper returned `0x4d` for VK 39, mapping type 4 and layout 67568647,
without the E0 prefix. This query sent no input. The old planner trusted that
missing prefix. The correction preserves dedicated extended-key identity even
when the mapper omits it (`799f9d1`, versioned by `78a4239`): right arrow uses
SCANCODE|EXTENDED flags 9 on down and 11 on up. The successful V8 receiver proof
above confirms both extended events; it does not conflate raw scan codes,
Unicode, numpad or Pause semantics.

Earlier desktop/focus failures that sent no input were archived separately.
Owned VM focus/setup clicks were operator-side preparation, separate from the
tagged Win32 keyboard events counted by the receiver. Failed/uncertain attempts
remain in their original receipts and are never reported as successful or
automatically replayed.

Finally, the V8 preview smoke failed before child creation because Python 3.14's
Windows `tempfile.mkdtemp()` created an existing directory whose DACL did not meet
the production current-user/SYSTEM policy. The harness now chooses an uncreated
random child path and lets the native private-directory helper create its ACL.
It records pre-start stages/errors and uncertain child creation explicitly. The
fresh V9 preview passed; production ACL requirements and all 171 runtime modules
were unchanged. This was a harness correction, not an ACL relaxation.
