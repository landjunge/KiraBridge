# KiraBridge security modes — architecture decision (2026-10-22)

Status: accepted product decision; implementation pending.

One KiraBridge core with interchangeable security providers:
- `standalone` (default): local platform-protected keys, macOS Keychain first, Linux systemd credentials with dedicated service user; no 4AllPass dependency.
- `4allpass` (optional): delegate authorized signing/verification to 4AllPass when its authenticated API and security contract are verified; never export long-lived signing keys into agents.

Installer asks for the mode, defaults to standalone and must not imply that 4AllPass is installed or ready. Switching later through a proposed `kirabridge config` command requires explicit confirmation, compatibility checks, protected migration, verification, and rollback; never silently downgrade from 4AllPass to standalone. Diagnostics remain usable if 4AllPass is unavailable, while operations requiring it fail closed.

Implementation gates:
1. Define provider protocol (sign/verify, key identifier, version, capability checks) and test fake provider.
2. Implement macOS Keychain provider, isolated tests and error handling. Keep current local HMAC receipts as experimental only, not production approved.
3. Implement Linux systemd-credential provider behind same protocol; test under actual Linux/systemd.
4. Inspect 4AllPass API before building its adapter; no assumptions about its current capabilities.
5. Add installer choice, status and mode switching with safe migration.
6. End-to-end tests and explicit release review; protect existing RC13 and uncommitted files.

No mode selection or provider migration has been deployed yet. No commit or push implied.
