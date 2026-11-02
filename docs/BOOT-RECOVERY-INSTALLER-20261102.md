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
