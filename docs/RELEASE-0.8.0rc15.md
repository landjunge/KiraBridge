# 0.8.0rc15 — unpublished candidate / unveröffentlichter Kandidat

Based on RC14 plus the merged PNG metadata and launchd retry fixes on
`integration/local-rc13-20261022` (2f5d2fa). The default `main` branch is a
separate lineage; replacing it wholesale would remove features. This change
uses the same PR target as hotfix PRs #19 and #20, preserving both lineages.
The public-facing README text incorporates the newer bilingual explanations
from main. No default branch or production installation is changed.

Changes: deterministic macOS bundle with actual wheel, exact Git identity,
hash-locked dependencies, checksum sidecars, installation/update entrypoint,
scoped fresh setup, foreign-launcher protection, team busy guard and rollback.
Fixes package/runtime/lock version disagreement. Includes the existing post-RC14
PNG and launchd fixes. Intel cryptography stays below 49 for compatible wheels.

Rebuild from a clean commit with uv 0.11.6 and Python 3.11:
`uv sync --locked --dev`, then
`uv run python scripts/build_release.py --out dist/candidate`.
Build a second time into a different empty directory and compare SHA256SUMS.
The source commit, normalized tar metadata and wheel SOURCE_DATE_EPOCH make the
bundle repeatable; Python, uv and network dependency wheels are prerequisites.
No Apple signing/notarization. See [installation](INSTALL-MACOS.md).

Release gate: GitHub Actions currently refuses to start jobs because account
payments failed or the spending limit needs increasing. This is an external
billing gate, not a passing test. PR review and a successful required CI run
must precede merge/tag/publication. No new release or download URL is claimed.
The latest published version remains v0.8.0rc14.

The candidate's authenticated one-line release download can only be tested
after approved assets exist. Do not substitute guessed URLs or execute curl|sh.
Local package acceptance is recorded separately in
[the acceptance report](ACCEPTANCE-MACOS-RC15.md). Mobile/Live/ChatGPT and physical
Apple Silicon acceptance remain distinct from local Intel macOS tests.
