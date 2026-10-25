# RC17: integrierter Quellstand und vServer-Prüfungen

## Tatsächlicher Ausgangspunkt

Beim erneuten Abgleich war PR33 bereits durch eine andere Sitzung nach main gemergt,
main `7e3b8a305aa97cc1a859552a38f77d2893cd6617`. Dies wird nicht als eigener Merge
ausgegeben. Die vorhandenen zwei Netcup-Runner waren bereits registriert und haben
Linux-CI ausgeführt. SSH als normaler Benutzer daniel bestätigte Debian13/x86_64,
acht CPUs,16GB RAM und vorhandenes uv0.11.6. Kein zusätzlicher Runner, root-Zugriff,
apt, Dienstwechsel oder Produktionsprofil wurde benötigt.

Linux3.11 auf main bestand. Linux3.13 im Run40190227810 hatte einen **echten**
Fehler: test_body_rewrite_during_scan_never_leaves_reusable_idle_cursor erwartete
unknown, erhieltidle (1328passed,1failed,5skipped). Das ist kein Billingfehler.
Gehostete macOS-Jobs sind weiterhin wegen Abrechnung nicht gestartet. Debian ist
kein Ubuntu-/macOS-Nachweis, kein fehlgeschlagener Check wird ersetzt oder gelöscht.

## Zusammenführung

Eigener Worktree/Branch `rc17-verified-20261025` / `integration/rc17-verified-20261025`:
main7e3b8a3 plus die abhängige Linie PR32→PR36 (`7204606`) über Merge9d04c3b,
anschließend PR35 (`c899056`) über Merge93852d9. Damit bleiben PR33 und alle Eltern
erhalten. DesignPR34 bleibt außen vor. Nur README hatte einen Textkonflikt;
Installationsnachweise, tatsächliche Laufzeit012b592, veröffentlichteRC14 und
unveröffentlichte neue Quelle wurden getrennt erhalten. discovery.py kombiniert
Rechtefrische/passiveHealth mit dem Receiverstatus. Self-hosted Linuxworkflow,
TD770bbc9f und TollGate53fc57cc bleiben exakt erhalten. Unabhängiger Teamreview
fand in diesen kombinierten Bereichen keinen konkreten neuen Defekt.

## Gezielte Reparaturen

A: `platform_adapters/codex_state.py` konnte gleich große Umschreibungen mit
unverändertem mtime_ns übersehen. Der lokal zunächst erfolgreiche Timingtest
wurde mit erhaltener mtime deterministisch verstärkt und reproduzierte den Fehler.
Verbrauchte Scanbytes und Header werden jetzt mit SHA-256 und ungepuffertem
`os.pread` nachgeprüft. Abweichung oder unvollständige Prüfung invalidiert den
Cursor dauerhaft. Zusätzlicher I/O bleibt höchstens ein Scanbudget, Pread-Blöcke
maximal1MiB. Keine Readinesslockerung oder behauptete kryptografische Agentidentität.
Grenze: kein vollständiges Neuhashen historischer Logs bei jedem gecachten Read.
Neun unterschiedliche direkt betroffene Fälle bestanden; APFS/Python3.11 ist
noch kein Linux3.13-Nachweis.

B: `build_release.py` und `release_smoke.py` widersprachen sich bei generischem
macOS-Archivnamen, LICENSE-Asset und Lizenzmanifest. Drei Reproduktionen scheiterten
vor dem Fix. Beide Manifeste binden nun Lizenz/Hash und Quellpin, LICENSE ist ein
zusätzliches Asset samt SHA. Smoke erkennt sichere aktuelle und ältere Layouts,
prüft Archiv/Pins/Lizenzkopien/Wheelmetadata und nutzt unter Darwin den vorhandenen
Installer mit ausschließlich isolierten Pfaden und service=none. Zwölf gezielte
Unitfälle bestanden; dabei wurden echte Build-/Installationsaktionen gemockt.
Keine echte Paketabnahme daraus ableiten.

C/Root: unabhängiger lesender Review ohne konkreten Blocker.19 kombinierte
Discovery-/Berechtigungs-/Legacy-/Installer-/Cleanupfälle und zwei echte isolierte
native ThreadDesk-Fälle (Text/Neustart/Readback sowie autorisierter Abort) bestanden.
Ruffcheck und Formatcheck des gesamten integrierten Baums bestanden (338Dateien).
Keine zusätzliche vorsorgliche Gesamttestsuite ausgeführt.
[Quellhashes/Logs/Ergebnisse](evidence/verified-integration-local-20261025.json).

## vServer und verbleibende Abnahme

Ein eigener privater Testordner unter daniels Benutzerkonto wurde angelegt. Keine
Arbeitsdatei laufender Runner wird benutzt oder verändert. Zuerst nur der konkrete
Rewritefall mit Python3.13 aus exakt gepinntem Snapshot; danach normale
verpflichtende Verify-Matrix3.11/3.13 auf den vorhandenen GitHub-Runnern.
Der Release-candidate-Workflow nutzt ebenfalls den vorhandenen Linuxrunner und
nennt dessen tatsächliches System Debian13; macOS bleibt unverändert enthalten.
UV_PYTHON=3.11 hält die bisherige Release-Runtime trotz Systempython3.13 fest.

Neue Pakete benötigen anschließend echte Build-/Reproduzierbarkeits-/Smoke- und
macOS-Paketabnahme. Weder alte012b592-Artefakte noch lokale Einzelfälle werden als
Abnahme der neuen Quelle umetikettiert. Solange Pflichtchecks fehlen, kein
Mainmerge und keine Veröffentlichung. Produktiv bleibt RC17/012b592, veröffentlicht
RC14, RC17 Entwurf. Receiverprofil, autorisierter Exportordner und reale Library-
Übertragung bleiben getrennte offene Voraussetzungen; keine doppelten Altaufträge.

## Tatsächlicher gezielter vServer-Nachweis

Snapshot `308ffbacb9c65e64124751b693b581e69aa93f29` wurde per Git-Bundle in
einen neuen privaten Ordner des normalen Serverbenutzers übertragen. Mit bestehendem
uv0.11.6 und eigenem Cache/Temp/Venv bestand der zuvor auf main fehlgeschlagene
Rewritefall unter **Debian13/Python3.13.5:1passed in0.32s**. Der Quellhash stimmt
mit dem lokalen Fix überein, Git-Arbeitsbaum blieb sauber, UID1000. Keine laufende
Runner-Arbeitskopie oder Dienste verändert, keine GitHub-Zugangsdaten kopiert.
[Quell-/Testbeleg](evidence/verified-linux313-targeted-20261025.json).
Dies ist bewusst ein einzelner Linuxregressionsnachweis, kein gesamter Actions-Pass.
Nachfolgende reine Nachweisdokumentation verändert den getesteten Code nicht.

Als Nächstes laufen am finalen Commit die normalen verpflichtenden Linuxchecks
auf den vorhandenen GitHub-Runnern und der echte Linux-Release-Smoke-Job.
Erfolgreiche endgültige CI-/Paketresultate werden separat in PR/Whiteboard
protokolliert; fehlende macOS-Jobs bleiben ein offenes Gate.
