# Intel-Abnahme / Intel acceptance · 26 October2026

Program source: `20a30e8511c565d3c85776d58f3e50a7cf14ff93`, version0.8.0rc17.
[Integration PR43](https://github.com/landjunge/KiraBridge/pull/43).

## Tatsächlich durchgeführt / Actually executed

- Native Intel x86_64, macOS15.7.4, Python3.11.15: complete Verify workflow equivalent,
  strict `error::pytest.PytestUnraisableExceptionWarning`, **1609 passed,1 skipped in296.32s**.
  Ruff check/format, locked dev install, wheel and source distribution passed.
- Fixed isolated sources: ThreadDesk770bbc9f0c0a02699cc93cad47d2e2c3782f7080,
  TollGate53fc57cc2e082d022e65e5929cb2a1e186fba852. No productive peer changes.
- Actual package SHA256 `6b137feda52c3f86207c3a675d2f87ef82ce7448a68149dbd0bf2f24d14d9abd`:
  **9/9 RC14 installation/upgrade lifecycle checks**, real isolated launchd, data retention,
  idempotency, command-exit survival, restart, KeepAlive, rollback, fresh installation.
  Cleanup bootout0 and independent absence113. Productive config/credentials/install record unchanged.
- Existing current-source double-build reproducibility, Mac smoke, real native1343/1343Braille
  cells/multiple pulse positions/23resumed short writes, warm144 upgrade/rollback and authenticated
  isolated copy flow were reused, not rerun. No new windows during missing workflow tests.
- Team independent read-only review confirmed test isolation, exact source/package binding,
  archive contents and cleanup. Counts from overlapping phases are not added together.

Immutable `RC17-20a30e8-LOCAL-INTEL-*` evidence/log/checksum assets are attached to the
[RC17 release](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17), with independent
API SHA-256 comparison. Shared Whiteboard188ce4729a62 result independently confirmed at revision76.
Historical449/144 results are not relabeled as this source.

## Betreiberentscheidung / Operator decision

After the above concrete results, the operator explicitly answered **“ja mergen und installieren”**
to accepting this local Intel evidence for Intel delivery in place of the unavailable hosted matrix.
This changes acceptance scope, not the truth of checks: hosted jobs remain billing-blocked before
execution and native ARM is **not tested**. No billing/OS-rights/security changes are authorized.
No admin override of server-enforced branch rules is authorized. KiraBridge remains vendor-independent.

Final documentation changes are separate from tested program bytes. Merge must preserve those bytes;
final package source/hash/manifest must match the real integrated commit. Only then may the installer
run in one fresh, confirmed, visible owned Terminal. Back up old definitions/config/credentials and
preserve DB/user files; retain a safe rollback and read back the responding version/source/service.
Release publication and productive activation must each be reported as actually observed, not assumed.
