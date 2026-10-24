# RC16 acceptance / Prüfstand

Candidate only; not published or accepted for production.
Final evidence is attached to the RC16 review draft as JSON and SHA-256 manifests.
The evidence records the source commit and actual executed macOS checks.
A contract fixture is not the ThreadDesk product. Actual ThreadDesk interoperability,
live host-selected ChatGPT file access, required GitHub CI/review and Apple Silicon
acceptance remain separate gates. No production installation/configuration was changed.

## Executed source checks / ausgeführte Quelltests

Actual macOS 15.7.4 Intel x86_64: full regression run **1053 passed** in 180.70 s.
After replacing header-only media fixtures with complete synthetic PDF/PNG/WAV/MP4
files and adding a custom trusted client-role case: **63 component tests passed**.
Ruff lint, formatting and git whitespace checks pass. No privileged live command
was executed and no operating-system permission was changed.

Coverage includes unchanged bytes/SHA-256/folders/provenance, principal isolation,
malicious paths/archives/secrets, size quotas, lost acknowledgements, pause/resume,
sender and MCP receiver restarts, prefix mismatch and false durable receipts.
The real-MCP receiver is a disk-backed contract fixture, not ThreadDesk itself.
A previous source-run native visible-terminal acceptance succeeded; the RC16 draft's
attached built-package evidence is authoritative for the actual packaged runtime.

The final candidate is built twice from a clean exact commit. `release.json` records
that source commit; `SHA256SUMS` covers bundle/wheel/bootstrap. Package acceptance
runs with a uniquely named isolated launchd service, config, credentials, database,
workspace and launcher. Evidence attachments, not unexecuted plans, determine whether
remote download, installation/upgrade, restart/status, crash recovery and rollback
passed. The native terminal acceptance records the installed package path and only
operates on windows it created itself.

## Gates / Hürden

GitHub run [40092920003](https://github.com/landjunge/KiraBridge/actions/runs/40092920003)
has no executed steps: account payments/spending limit prevents jobs starting.
Required CI/review, actual ThreadDesk v1 receiver storage acceptance, live ChatGPT
file selection and Apple Silicon acceptance remain open. Runtime integration base
is `33126b7`; `main` is a separate lineage and is not overwritten. No new version is
published or claimed merged while required gates are unsatisfied.

## Candidate package checks before final documentation pin

Two builds of `7bda028844af7b13e28a16637d8ea9721e48dad2` were byte-identical.
The built wheel passed 63 component tests. Native Terminal.app checks from the
installed wheel passed: new visible window/exact TTY, idle reuse, busy-window
preservation/new window, fresh discovery revision, stale PID rejection. Installed
site-packages path is recorded in `visible-terminal-evidence.json`.

The first isolated launchd baseline run hit the existing 30-second RC14 readiness
limit and rolled back. A second fresh isolated run passed all nine package checks:
RC14 start, RC16 upgrade, config/credentials/database/user-file preservation,
service survival after command exit, idempotence/same PID, actual restart, KeepAlive
crash recovery, rollback to RC14, fresh RC16 install. This initial timeout is retained
as a limitation, not erased by the passing run. Final remote-download evidence is
attached to the review draft after the final documentation/source pin.

Subsequent MIME-metadata leak rejection was checked with **65 passing component tests**.
The final source full-suite log, reproducibility manifest, installed-wheel transfer
proof (including 16 MiB multi-chunk data and lost-commit reconciliation), visible
terminal proof and authenticated draft-download acceptance are attached separately
with their own SHA-256 manifest. Draft links in README use the stable release list:
GitHub changes temporary `untagged-*` URLs when a draft target is edited.

Final upstream recheck: ThreadDesk PR #86 is merged and supplies local persistent
file import, but main `55e90dd2d1d59961a832a6bc7c2a64fe733886db` exposes no compatible
MCP byte-stream/receipt interface. It therefore does not remove the interoperability
acceptance gate. KiraBridge PR #25 checks on the final candidate also failed before
steps because of the same GitHub billing/spending-limit annotation.
