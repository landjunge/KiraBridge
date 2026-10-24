# RC17 package acceptance / Paketabnahme

**Review draft, not published. No production deployment approved.**
[Actual draft / Tatsächlicher Entwurf](https://github.com/landjunge/KiraBridge/releases/tag/untagged-8c7f469dd5b21fb1b123) ·
[PR28](https://github.com/landjunge/KiraBridge/pull/28).

Built source `5089fca8f72bc0088a967eb057d85b0e461f0b55` is the two-parent
consolidation of main and RC15/RC16 plus queue/terminal/Whiteboard repairs.
Two clean builds produced byte-identical four-artifact SHA256SUMS. All126 wheel
source members match the committed source byte-for-byte. Later documentation
commits do not change this immutable tested package source pin.

Actual macOS15.7.4 Intel x86_64/Python3.11.15/uv0.11.6: one authenticated draft
download acceptance passed. Actual RC14 wheel SHA256 was independently checked
against `c5d33839b70badf36371d1fef03ea3a4370e00165db4699647ccacfa3700fadd`.
Unique private config/runtime/launcher/workspace/port and owned launchd label only.
No user profile, productive daemon, credentials or OS permissions changed.

Verified: RC14-wheel baseline start; upgrade from built package; authenticated
version/status/start; config/credential-hash/database-row/user-file preservation;
service survival after installer command exit; idempotent update/same PID;
actual kickstart restart; KeepAlive crash recovery; rollback to real RC14 wheel
with data preserved; fresh built-wheel install. Test service was booted out in
the fixture cleanup. Background service behavior is unchanged.

The exact tested invocation, including every isolated path/test-label argument,
is in [package evidence](evidence/package-rc17-20261024.json). The command template
below is identical; `"$@"` forwarded those explicit isolation arguments during the
test. Default productive destinations were NOT exercised. Requires authenticated
GitHub CLI/draft access, Python3.11, uv0.11.6 and network dependency downloads.

```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh "$@")
```

No Apple signing/notarization. Apple Silicon, macOS26, older macOS and the Linux
source installer are not accepted by this Intel-macOS test. Source regression:
1271 collected cases now have passing evidence,43 skipped optional integrations/
tmux are not passes. Initial failures and narrow reruns are retained in
[consolidation report](CONSOLIDATION-20261024.md).

Still required: successful GitHub CI (billing/spending currently prevents jobs
from starting), independent review, positive native Codex/Grok input acceptance,
and protected-main integration followed by final release-source validation.
ThreadDesk receiver/index contracts and selected authorized file bytes remain
prerequisites for real Library imports. No duplicate queued work was run.

## SHA-256

```text
f7a14a970e2604728ab269214041836a1935fe15a7e9c1d2041d28c3091d5b8e  KiraBridge-macos.tar.gz
b6d3720b98a275d79b2e3964331e0337fe28e197020e34b2df79965151e3a904  kirabridge-0.8.0rc17-py3-none-any.whl
e76fee4b1d3b7c07d183ae5f22a3c49991ac95aeba29cb1cea0a5ecde379bee8  install-macos.sh
eae00e3593bf5ab6b39175ea8d4cc2f4153f0e9541ade6e6c994a7aaf22739bc  KiraBridge-0.8.0rc17-Linux-x86_64.tar.gz
```

Prüfergebnis: Paketweg auf echtem Intel-macOS isoliert bestanden; kein allgemeiner
Produktabschluss. Die finale Agenteneingabe war zuvor durch die Fokusprüfung
abgewiesen worden und wird hier nicht als erfolgreich umgedeutet.
