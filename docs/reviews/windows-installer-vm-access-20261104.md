# Windows installer: VM access and isolation audit

Observed 4 November 2026, from the isolated installer worktree. Read-only audit;
no guest input, VM state/configuration change, installation, process stop or
compiler invocation occurred.

## Available VM and access

Fresh `/Users/landjunge/Applications/UTM.app/Contents/MacOS/utmctl list`:

| UUID | Name | State |
| --- | --- | --- |
| `2B6EE828-02F0-42AE-B4FE-BE57C448F65E` | KiraBridge Windows Dev Fix1 | started |
| `5F4A0DE9-40F6-42F4-9225-2B8FB530DF2B` | KiraBridge Windows Dev | stopped |

The running QEMU command confirms x86_64, HVF, 2 CPUs, 8192 MiB and user-mode
NAT, without host port forwarding. Its existing disk, ISO attachments, TPM and
firmware are in use and must remain untouched. Do not clone/copy the active
QCOW2 as though it were a consistent backup.

Previous native acceptance reports document `utmctl exec` failing before guest
execution with OSStatus `-2700`: the guest agent was absent. This audit did not
repeat that probe. No persistent SSH/WinRM channel or active task-owned staging
server was discovered. The pre-existing host HTTP server on port 8000 belongs
to other work and must not be reused or stopped.

The previous task's guest-only bootstrap dispatcher is available at:

```
~/.local/share/kirabridge/backups/windows-vm-20261103/utm_owned_input
~/.local/share/kirabridge/backups/windows-vm-20261103/utm_owned_input.m
```

Its reviewed source checks the exact started VM UUID and name, validates bounded
scan codes or an in-display mouse coordinate, and writes an exclusive durable
`O_EXCL|O_NOFOLLOW` attempt receipt before dispatch. It uses UTM ScriptingBridge
guest events, without host key injection or clipboard. Its existence alone is
not evidence that the guest foreground is safe: root must inspect the current
guest display and use a newly owned setup window before sending a command.
Historical job JSON/attempt receipts must never be replayed.

The old `raise_read_vm.swift` helpers activate UTM and raise the host window;
do not run them during parallel macOS work merely to obtain a screenshot.
Any helper adopted for this task must use fresh output paths and avoid host
focus changes. Do not reuse the original guest setup tab or an application
console as a command window.

## Protected installed instances

These are historical identities from the completed RC33 independent readback,
not freshly verified live-process claims:

| Instance | Port | PID | Process creation FILETIME |
| --- | --- | --- | --- |
| dev2 | 8765 | 11720 | `134382301975786026` |
| dev3 | 8766 | 7516 | `134382470213253467` |
| RC33 | 8767 | 5956 | `134382553866962927` |

RC33 runtime is `%LOCALAPPDATA%\KiraBridgeRC33\Runtime`, state is
`%LOCALAPPDATA%\KiraBridgePreviewRC33`. The previous snapshots also protect
dev2/dev3 module bytes, credential bytes, desktop launchers, executable paths,
process generations and sole-loopback listener ownership. All three need fresh
before/after observation for the installer acceptance; the old `Protected-All`
function covers only dev2 and dev3 and needs an additional RC33 entry.

Primary prior artifacts remain under:

```
~/.local/share/kirabridge/backups/windows-rc33-finish-20261104/
```

Useful read-only references there: `cache-stage-rc33.ps1` (snapshot functions),
`prepare_readback.py`, `readback-rc33.ps1`, `verify_installed_windows_rc33.py`,
and `WINDOWS-RC33-FINAL.json`. The public sanitized summary is
`/Users/landjunge/KiraBridge-integration-audit-20261104/evidence/windows-rc33-installed-final.json`.
Do not execute the historical install/observer scripts: they use fixed paths,
ports, process pins and attempt names from the previous task.

## Concrete next test/build procedure

1. Prepare a new private host staging/report directory and an unused loopback
   port with a newly generated capability token. Existing
   `scripts/windows_guest_host.py` can serve only pinned filenames. A compiler
   or installer bundle can travel as `source.zip`; this avoids broadening its
   fixed-file boundary. Put the fresh wrapper at `guest_runner.ps1`, with the
   exact SHA256 in a small new bootstrap command. Existing Python installer
   bytes can be copied from the verified kit without invoking that installer.
2. Use one new owned guest setup window; inspect its prompt/layout and the full
   typed command before one Return. Use fresh durable attempts for typing and
   submission. Reconcile reports/guest files after uncertainty; never submit an
   unconfirmed command again. This step needs exclusive coordination of the
   VM's guest input lane; it does not need host focus or clipboard.
3. Fresh guest wrapper records protected baselines for all three installations,
   then inventories candidate ISCC executables read-only. Inno Setup compiler
   availability has **not been proven** by this audit. If absent, prefer a
   pinned portable compiler in the task's new directory; installing a compiler
   globally would exceed the intended test isolation.
4. Build only x64, in task-owned guest directories. Transfer exact Setup bytes
   and build logs back through the existing bounded report protocol (or a new
   bounded artifact endpoint if the executable exceeds report size); verify
   artifact size/SHA256 independently on the host. Report transport must never
   encode credentials or expose unrelated guest paths.
5. Test with a separate installer AppId/uninstall-registry key, start-menu
   group, app directory and data root; these must be controlled before Setup
   or uninstaller execution. Use a free loopback port outside 8765–8767.
   A different `/DIR` alone does not isolate an Inno Setup upgrade/uninstall
   because AppId controls product identity.
6. Exercise fresh install, actual launch/authenticated health, repeated install,
   upgrade, rejected/damaged payload, rollback, uninstall and retained-data
   reinstall. Keep configuration/credentials/database sentinels and compare
   exact bytes where appropriate. Positive native keyboard tests from RC33
   need not be repeated for packaging changes.
7. Stop only owned test processes after checking process generation/image;
   uninstall only the isolated product identity, preserve its retained data
   for inspection, compare all three protected snapshots, then close the one
   owned setup window after confirming an idle prompt. Keep VM running and
   original setup tab intact. Confirm own helper absence independently.

Installer lifecycle acceptance, compiler execution, signed artifact behavior,
interactive wizard usability and rollback results remain untested by this
read-only access audit. No installer acceptance or release is implied.
