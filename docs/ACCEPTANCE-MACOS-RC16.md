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
