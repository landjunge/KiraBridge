# RC15 macOS acceptance / Abnahme · 24.10.2026

**Published release: v0.8.0rc14. RC15 remains a draft; merge and publication are blocked.**

Tested package source: `efb805ab0d651ad5975d8c9e151edb4058f7e1c6`.
Actual host: **macOS 15.7.4, Intel x86_64, Python 3.11.15, uv 0.11.6**.
[Runtime/install PR #21](https://github.com/landjunge/KiraBridge/pull/21) targets
`integration/local-rc13-20261022`, following hotfix PRs #19 and #20. The separate
`main` lineage is preserved; a documentation-only PR updates its release guidance.

## Actual results / Tatsächliche Ergebnisse

- Final full regression suite: **960 passed in 183.63 s**. Ruff lint and format pass.
- Locked dependency sync succeeds; project, runtime and lock report 0.8.0rc15.
- Two clean builds of the exact source produce identical wheel, bundle and
  bootstrap SHA-256 values. Tar metadata and wheel build epoch are normalized.
- Authenticated GitHub download of the actual draft assets, both checksum
  verification stages and execution of the bundled installer pass.
- Fresh wheel installation and upgrade from the actual published RC14 wheel pass.
  RC14 fixture SHA-256:
  `c5d33839b70badf36371d1fef03ea3a4370e00165db4699647ccacfa3700fadd`.
  The previous wheel is run with the compatible RC15-locked dependency environment;
  this does not claim to reproduce every historical RC14 dependency installation.
- Real isolated launchd service: authenticated status/version, idempotent repeat
  installation with unchanged PID, `kickstart` restart and automatic recovery after
  SIGKILL pass. The service survives completion of its installer shell process.
  No physical Terminal or browser window was closed as part of this test.
- Configuration/credential hashes, a real database probe row and a user file
  survive upgrade. Actual rollback restarts the old RC14 wheel and retains secrets.
- Fresh scoped setup uses manual approvals and a project folder. Existing full
  access/voice-policy preservation, foreign launcher/service refusal, symlinks,
  unsafe permissions, busy queues and failed activation recovery have unit coverage.
- All four isolated launchd labels were confirmed absent after cleanup. Test paths,
  ports, configuration, credentials, caches, logs and databases were separate from
  the production KiraBridge installation. No paid provider calls were made.

An initial draft-download run exposed a rollback/bootstrap failure while the
installer held a SQLite write reservation. The final source releases that guard
before bootstrapping launchd. A deterministic two-connection SQLite regression
covers activation and rollback; the complete final download/install/rollback run
then passed. The earlier failure is not counted as a passing run.

## Exact tested one-line command / Genau getesteter Einzeiler

Only authorized draft reviewers can currently access RC15. Python 3.11,
uv 0.11.6 and authenticated GitHub CLI with repository access are prerequisites.

```sh
d=$(mktemp -d) && gh release download v0.8.0rc15 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh "$@")
```

For the actual test, this exact shell body was passed to `sh -c` with all
installation destinations and the unique `com.kirabridge.test.accept-rc15-final`
launchd label supplied through `"$@"`. `TMPDIR` was also inside the isolated test
root. The complete invocation and working directory are in the
[machine-readable evidence](evidence/macos-rc15-20261024.json). Production defaults
were never used for acceptance. This is a tested draft download, not a published
end-user release. No curl|sh or guessed release asset URL is used.

## Final deterministic artifact hashes

```text
6a3d9abdd68068ca567485f3a4ff5129844ec19c880386e73fb45a3590e57f48  KiraBridge-macos.tar.gz
9ced17a803a29dcbfd0db97ca3e5b6e5c402cdddd8516ee1402bd422b13b9458  kirabridge-0.8.0rc15-py3-none-any.whl
569955e447dbf7539dbd0d5c1cc50b19d4f7cdd0313b5ed7ff5b66f9b9e9f278  install-macos.sh

```

The final report/evidence were recorded after the build and are attached as
separate checksummed draft assets; they do not change these reproducible binaries.

## Remaining gates / Verbleibende Hürden

[GitHub CI package run](https://github.com/landjunge/KiraBridge/actions/runs/40087117293)
and [regression run](https://github.com/landjunge/KiraBridge/actions/runs/40087117287)
did not execute any test steps. GitHub's annotation states:

> The job was not started because recent account payments have failed or your spending limit needs to be increased.

Account billing/spending limits must be resolved by the account owner. Then rerun
both workflows and complete PR review before merge/tag/publication. No review
approval has been received, no release tag v0.8.0rc15 was created, and the release
remains a draft. The latest published release is v0.8.0rc14.

Apple Silicon, macOS 26, older macOS on a 2015 iMac, native app/signing, and physical
mobile/Live/ChatGPT end-to-end acceptance are **not passed**. Intel was tested on
macOS 15.7.4; the hardware model alone does not establish compatibility. See the
[bilingual prerequisites and installation guide](INSTALL-MACOS.md).
