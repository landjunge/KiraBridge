# ChatGPT boot recovery and native installer — 2026-11-02

## Observed incident

After a computer restart, the local KiraBridge app/core ran while the real ChatGPT
connector returned `McpServerError: Session terminated`. The existing tunnel log
records a failed DNS lookup for api.openai.com at 17:10:24 Europe/Berlin, then an
MCP child exit 1 and orderly tunnel shutdown at 17:11:34. launchd recorded tunnel
exit 0; its old `KeepAlive: {SuccessfulExit: false}` policy left it stopped. The
precise cause of the child exit is not established. Restarting only the tunnel
restored real authenticated connector calls without changing account keys.

## Permanent change

A shared, strictly owned ChatGPT service definition restarts after both orderly
and error exits with launchd throttling at 30 seconds. Known older definitions
can be migrated atomically; custom/symlinked/unrelated services are preserved and
rejected. Loaded job identity is checked before reload. Replacing a running
service uses bounded handling of launchd's known transient bootstrap EIO.
Live status can use the verified current launchd process when tunnel-client's
historical alias metadata points at an old PID; live health/readiness remains
required.

The new native installer embeds the exact runtime, verifies its complete file
inventory, source/version/CPU identity and signature before launch, and invokes
the existing foreground installer in a visible Terminal. Its optional desktop
transaction also updates the matching console, companion app and linked tunnel.
Backup/recovery preserves configuration and credentials and does not restore an
old database over newer work. A missing account link is left missing.

## Verification

A separate real launchd fixture used the new KeepAlive/throttle policy and four
unique process generations: exit 0, exit 1, unavailable local readiness, then
stable readiness. Automatic restarts occurred at approximately 30.25 seconds.
Its exact label was removed and job/PID absence independently checked. An initial
result assertion incorrectly compared process-local monotonic clocks; the
original failed result is retained. A separate read-only verifier uses the
already-recorded epoch timestamps; it did not restart or repeat the fixture.

Targeted installer tests found one outdated package fixture lacking the newly
manifested desktop helper. The fixture inventory was updated and only that
failed case rerun. Installer package-integrity tests and native Swift compilation
are separate from actual deployment verification.

Exact test totals, package identity/checksums, Git destination, live deployment,
rollback and any remaining limitations follow after the final release gate.
No complete machine reboot is claimed by the isolated recovery fixture.

The parent automatic-keyboard branch had three Python files outside the format
contract. Their formatting is normalized without behavioral changes so the
repository-wide required formatter check can pass.

Pre-build review gate: independent review of the boot/status changes and desktop
transaction completed. The targeted package/app/setup/service group passed 54
cases. Desktop/core transaction coverage comprises 32 cases, including recovery
continuation after the core is already restored. Visibility/release-builder
checks also passed. Repository-wide Ruff lint and formatting passed. The native
installer source compiled on Intel. Existing keyboard behavior was retained;
its complete previous native matrix was not repeated for this boot-policy change.

During the build gate the operator updated the Kira skill to require local Intel
builds/tests only. The automatic workflow triggered by the first push was
cancelled; it is not counted as successful validation. Subsequent commits skip
CI. The existing builder also emitted a Linux archive on a Mac; the final builder
now emits only its host platform. The earlier candidate is preserved privately
and is not the released installer.

## Final release and actual installation

Build/tag: `7d862e5f63694e92a89afa68f0bed3671d791033`, version **0.8.0rc25**.
Branch: `fix/chatgpt-boot-recovery-20261102`; remote source identity verified.
[Published Intel installer](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc25).
The final build emitted only the Intel macOS package. Both host-selection cases
passed after the builder change. Native installer self-verification checked484
files. The independent runtime check validated482 manifested files,157 Python
files byte-for-byte against Git, native metadata/architecture and code signature.
Official smoke and complete isolated macOS launchd acceptance passed: RC24→RC25,
configuration/credential/database/userfile retention, idempotent reinstallation,
restart, crash recovery, rollback to RC24, and fresh RC25 installation. Exact
isolated labels and processes were independently confirmed absent afterwards.

The real native `.app --install` opened its own visible window241/ttys003 and
completed the desktop transaction successfully. Running core6797, console6817
and GUI6839 were checked against the new package. The new loaded ChatGPT job
has `KeepAlive=true`, minimum runtime30seconds. Its actual tunnel6825 received
one identity-checked SIGTERM, then launchd automatically started7114 without
kickstart. A real authenticated ChatGPT Apps connector call succeeded both after
installation and after that automatic recovery. CLI status now correctly reports
connected/healthy/ready from launchd despite historical runtime alias metadata.
No second complete computer reboot or separate ChatGPT web/mobile/voice UI test
is claimed.

Six protected configuration/key/profile-related file hashes match their baseline.
Interactive Codex1722 and its servers1728/1749 retained their original process
identities. A first overbroad reader assertion also counted the old tunnel's own
Codex app-server2613 under parent2610; that child is expected to be replaced during
tunnel upgrade. The diagnostic was corrected using recorded ownership; no product
operation was repeated. The owned finished installation window was closed and a
fresh inventory confirms its absence and the three original terminal windows.

- Installer ZIP SHA256: `c354a6f9968892a26423b2784433c3f7434c80316dd7aa23b167ee4fb761f92c`
- Runtime archive SHA256: `e4782c70c00c952d6a51f6d54ca41b2e8cffa31f7e5dedbf8835509489ed5282`
- Native binary SHA256: `8366f05228a1cb7c394f539a4f01e8bdb0bba2eb3e4d30eda7d223d9169b63c4`
- Actual running Python source hash: `9937d9f6ec7147527e915f6e8f3eb3d0dbf61eae40582576fccf320e9b35a1ed`
- Downloaded GitHub release ZIP was independently compared to the local ZIP and matches.
- Local delivery: `~/Downloads/KiraBridge-RC25-Intel-7d862e5/`.
- Upgrade rollback: `~/.local/share/kirabridge/install/backups/20261102-180129-46ec8ee0/`.
- Private evidence/checkpoint/log root: `~/.local/share/kirabridge/backups/boot-recovery-release-20261102T164424Z/`.

Existing backups and the RC24 installer remain available. The final documentation
commit does not change product code or the immutable release build. The installer
is ad-hoc signed; Apple notarization and Developer ID signing are not claimed.

Independent final read-only verification confirms the exact running package,
authenticated console and all four served assets, loaded tunnel policy, current
process identities and another actual authenticated ChatGPT Apps connector call.
Public summary: `docs/evidence/rc25-final-acceptance-20261102.json`.
