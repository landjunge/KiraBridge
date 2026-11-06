# RC40: Quellenintegration und tatsächliche Macinstallation

Stand: 6. November 2026. Auftrag: GitHub-Abgleich, sinnvolle Zusammenführung,
Tests/Review/CI, regulärer Merge und tatsächliche geprüfte KiraBridge-Installation.

## Ergebnis und Identität

[PR59](https://github.com/landjunge/KiraBridge/pull/59) ist regulär gemergt,
Maincommit `1b77d78e5b3af7f9d5380854575ba4036b4cf6ff`. Der geprüfte und paketierte Quellpin ist
`5f4dd46007742f4a09afa8b196b3da071b115ec5`; der Main-Dateibaum war beim Merge
exakt gleich. Main `34adc03e9a3eef81abba478027c13dcb48b01314` und Integration
`0da9abbcc3fd60f7e0d1f7a89724d6c07bb83892` sind Vorfahren: alle 15 zusätzlichen
Maincommits und alle 46 Integrationscommits bleiben erhalten.

Am Intel-Mac mit macOS15.7.4 sind **Dienst und Desktop-App0.8.0rc40 tatsächlich
installiert**. Installer-Exit0, sichtbares eigenes Terminal6160/ttys005, Quellpin
`5f4dd46`. Erster unabhängiger Live-Readback: DienstPID85537,
Instanz `5754188249e24f83b1f00f8baa596099`; AppPID85582. Der native Helfer meldete
bei echter App-Abfrage ebenfalls diesen Quellpin. Dateiabruf und sichtbarer
Terminalbefehl `RC40_LIVE_TERMINAL_OK` bestanden. Nach der Installation wurden
alle228 Wheel-Dateien und alle3 nativen App-Dateien nochmals direkt mit dem
geprüften Paket verglichen: sämtliche Bytes/Hashes stimmen überein. Der aktuelle
native Helfer bestätigte zusätzlich seine Bedienungshilfen-Berechtigung als
`granted=true`, ohne eine neue Rechteanfrage auszulösen.

Dies ist ein lokal gebautes und geprüftes Intel-Paket; **kein neu veröffentlichtes
GitHub-Release und kein neuer öffentlicher RC40-Download**. Der bestehende
veröffentlichte Download bleibt getrennt bezeichnet. Dokumentationsänderungen
nach dem Produktmerge verändern den installierten Laufzeitcode nicht.

## Tatsächliche Prüfungen

| Gate | Ergebnis und Umfang |
| --- | --- |
| Lokale statische Prüfung | Ruff check und format bestanden. |
| Gezielte eigene Tests | 76 Fälle bestanden,13,34s; CI-Preflight,Timing,Runtime,Windows-Verify und Native-Package. |
| Unabhängiger Quellenreview | 33 Fälle bestanden,10,51s,0Skips;10 zusätzliche Mergeproben; beide ReadQuery-Routen, Challengegrenzen, Versionen und Elternlinien geprüft. |
| Echte Linux-CI | [Run42217252448](https://github.com/landjunge/KiraBridge/actions/runs/42217252448) erfolgreich auf Python3.11 und3.13. Je4938 Legacyfälle bestanden und224 plattform-/voraussetzungsbedingte Skips; getrennt je29 Remotefälle ohne Skips bestanden. Beide Builds erfolgreich. Kein Null-Skip-Gesamtpass behauptet. |
| Paketvertrag | Release-Smoke erfolgreich;228 Wheel-Runtimedateien exakt Gitquelle,729 Manifestmember,232 Gitpayload-Dateien und4 Installerdateien unabhängig geprüft. |
| Native App | Intel x86_64; codesign verify strict bestanden, ad-hoc signiert. |
| Echte isolierte macOS-Abnahme | RC39 aus8d331314b608→RC40:Upgrade,Datenerhalt,Idempotenz,Neustart,KeepAlive,Rollback und frische Installation bestanden. Offene Completion-Leseverbindung endete beim Wechsel ohne Replay. Testdienst unabhängig als entfernt bestätigt. |
| Produktive Aktivierung | Gebautes Bundle im eigenen bestätigten sichtbaren Terminal mit `--desktop --require-visible-terminal` aktiviert; Exit0; anschließend authentifizierter CLI- und MCP-Readback. |

Auch der nach dem Merge automatisch gestartete [Mainlauf42219066041](https://github.com/landjunge/KiraBridge/actions/runs/42219066041)
bestand beide Python-Lanes mit Remoteprüfungen und Builds am tatsächlichen
Maincommit1b77d78.

Der Pushlauf42217151208 wurde durch die PR-Concurrency ersetzt; er ist kein
Timeoutnachweis und kein erfolgreicher Lauf. Alte Timeouts und rote Teilprüfungen
bleiben im [historischen Integrationscheckpoint](BIGPLAN-INTEGRATION-STATUS-20261106.md)
erhalten. Testumfänge überlappen und werden nicht zu einem künstlichen Gesamtzähler addiert.

## Datenerhalt und Rückweg

Konfiguration und Zugangsdaten sind nach Hash und Modus unverändert. Alle8170
bisherigen Task-IDs,159 ursprünglichen UNKNOWN-Zustände samt Fehlerbytes und
58 Queue-Holds sind erhalten. Kein UNKNOWN wurde wiederholt oder durch
Datenbankrücksetzung bereinigt.

Der transaktionale Installer sicherte den Rückweg unter
`/Users/landjunge/.local/share/kirabridge/install/backups/20261106-133750-263da082`.
Vorherige RC39-Laufzeit und Daten bleiben erhalten. Ein Rückweg nutzt den
vorhandenen Installerbefehl `rollback --require-visible-terminal` in einem
frisch bestätigten sichtbaren Terminal und prüft vorher erneut Leerlauf und
Kompatibilität. Keine alte Datenbanksicherung über neue Nutzerdaten kopieren.

## Übergabe und beobachteter Betrieb

Der frühere Codex-Koordinator bestätigte die Schreibzuständigkeit dieser neuen
Sitzung; sein geänderter Dokumentationsstand und seine Belege wurden gesichert.
Die älteren KiraBridge-PRs35,36,40,41,42 und57 wurden nach frischem
Head-/Statusabgleich als redundant geschlossen: ihre exakten Headcommits sind
Vorfahren des geprüften RC40-Main. Branches und historische Belege bleiben
erhalten; abweichende PRs wurden nicht blind gemergt oder geschlossen.

Die Inventur erfasste132 KiraBridge- und34 ThreadDesk-Worktreeeinträge. Elf bzw.
vier geänderte Arbeitsstände bleiben erhalten; fünf bereits fehlende historische
KiraBridge-Pfade wurden weder als aktive Quelle benutzt noch pauschal bereinigt.

Der **separate** Supervisor bleibt PID77398 aus0da9abb. Bei der Installation
waren Profil und launchd-Plist bytegleich und AutoNext deaktiviert. Während des
nachgelagerten CI-Wartens arbeitete eine zusätzliche Koordinationssitzung
`01a1b10a-957f-7622-ba78-2fd04b43c0db` an neuen Runbook-Aufgaben. Der frische
Betriebsabgleich fand danach ausschließlich den Profilabschnitt `continuation`
geändert; PID, Quellpfad und Plist bleiben erhalten. Alle zehn ursprünglichen
Core-Tasks sind mit Zustand und Fehlerbytes unverändert, jetzt sind insgesamt
14 Tasks bei diesem Abgleich vorhanden. AutoNext meldete am06.11. um13:46UTC `enabled=true`, aber
`stopped/continuation_external_claim`; Fortsetzung weiterhin `watching`. Diese
parallele Arbeit wird nicht zurückgesetzt oder als Leistung dieser Installation
angenommen. Die andere Sitzung berichtete DE-Abschluss und EN-Folgestart nach
22,9Sekunden; das ist deren Bericht, kein hier neu abgenommener Dauerbetrieb.
`coordinator.status` am Hauptdienst weist einen fremden/nicht konfigurierten
Koordinatorbesitzer mit `coordinator_owner_required` zurück; der tatsächliche
separate Status wird über `bigplan-loop status` geprüft. Das ist keine unbegrenzte
Dauerbetriebsabnahme und kein Beweis neuer automatischer Folgearbeit.
Das eigene Installationsfenster wurde anschließend geschlossen und per frischer
Sitzungsinventur sowie Prozessprüfung als abwesend bestätigt. Hauptdienst85537
und Supervisor77398 liefen danach weiter; andere Agentensitzungen blieben erhalten.

## ThreadDesk und getrennte Windowslinien

[ThreadDesk-PR99](https://github.com/landjunge/threaddesk/pull/99) verbindet
Main067a525, Plan cd5c994, Remote a0dd4c3 und Kurzberichte6eeb465.
Die reguläre Mainintegration ist `b6774db87781be65a43a581d6637c3220ae75fbd`;
der Main-Dateibaum entspricht exakt dem geprüften PR-Head87d91ab, alle vier
Quelllinien sind als Vorfahren erhalten. [PR-CI42217592012](https://github.com/landjunge/threaddesk/actions/runs/42217592012)
bestand zwei vollständige Läufe mit jeweils2680 Fällen,0Fehlern und0Skips;
[Linux-TLS/Restore42217592084](https://github.com/landjunge/threaddesk/actions/runs/42217592084)
bestand ebenfalls. Beide echten JUnit-Dateien wurden unabhängig zurückgelesen.
Auch die automatisch gestartete [Main-CI42223212219](https://github.com/landjunge/threaddesk/actions/runs/42223212219)
bestand am tatsächlichen Mergecommit b6774db beide Gesamtläufe mit jeweils
2680 Fällen,0Fehlern und0Skips; beide JUnit-Berichte wurden unabhängig gelesen.
[Main-TLS42223212208](https://github.com/landjunge/threaddesk/actions/runs/42223212208)
und die automatische Pages-Auslieferung42223210326 bestanden ebenfalls.
Die tatsächliche TD-MCP-Gegenstelle bleibt der bisherige
`threaddesk-770bbc9/src`-Stand. Die neuen Projektfunktionen sind dort nicht
installiert; Kurzberichte verwenden weiterhin ihren eigenen6eeb465-Adapter.

Die Mainlinie enthält den separat geprüften/veröffentlichten Windows-
EinrichtungsassistentenRC37.dev1 mit sieben nativen Phasen. Das ist ein anderer
Quell-/Prüfumfang als der spätere Big-Plan-/Dirk-Kandidat179bb6f mit noch nicht
gestarteten eigenen Phasen und seiner offenen Prozessausnahme. Beide Nachweise
bleiben getrennt. Zusätzliche Windows-Producer-/Inventararbeit wurde wegen der
semantischen Abweichung vom neueren Wizard nicht blind in das Macpaket gemergt.
Sie bleibt auf GitHub `test/remote-project-verify-20261106-r2` bei21d2e2c und
`feat/bigplan-windows-parity-20261105` bei ce50405 sowie als geprüftes lokales
Gitbundle erhalten. Nativeevents9cc005c ist patchäquivalent bereits enthalten.

Die zuvor nur in jener Linie stehenden [Gesamtplanung](plans/BIGPLAN-GESAMTPLAN-20261105.md),
[Architekturquelle](plans/sources/BIGPLAN-ARCHITEKTUR-REMOTE-BESCHLUSS-20261105.md),
[Oceanplanung](plans/OCEAN-MCP-ADAPTER-20261105.md) und Windows-Kandidatenbelege
werden als datierte historische Quellen übernommen; ihre alten Gates erteilen
keine neue Autorität und ersetzen diesen aktuellen Installationsnachweis nicht.

## Bereits vorhandener Linux-Tauri-Hinweis

Beim Abgleich wurde [Dependabot1](https://github.com/landjunge/threaddesk/security/dependabot/1)
frisch gelesen: seit 24.10.2026 offener moderater Hinweis auf `glib 0.18.5` im
unveränderten ThreadDesk-Tauri-Cargo.lock. [RustSec](https://rustsec.org/advisories/RUSTSEC-2024-0429.html)
nennt 0.20.0 als erste korrigierte Version. Das lokale Tauri 2.12-Manifest bindet
GTK/WebKitGTK an Linux/BSD; dieser Pfad ist kein Bestandteil des installierten
Swift/Python-KiraBridge-Macpakets. Der Hinweis bleibt als konkreter Linux-Tauri-
Paketpunkt offen; keine Alertunterdrückung oder ungeprüfte GTK-Majoränderung.

## Lokale Belege

Private Belegwurzel: `~/.local/state/current-mac-integration-20261106/`.
Dort liegen Git-/Worktreeinventar, CI-Rohlog und JSON, Gate-/Mergebeleg, JUnit,
Paketmanifest/Hashes, `macos-acceptance/evidence.json`, sichtbarer Installations-
start/-abschluss, Vorher-/Nachhererhalt und Live-Readbacks. Unabhängiger Review:
`kb-rc40-independent-review-k2zbpxbt` unter dem macOS-Tempverzeichnis.

Bundle-SHA256: `6829c9e10f4de3bd7abf5c0836631ade0ea1ee2a94128a507a576ab325420abb`.
Wheel-SHA256: `b1cc2caa7d828c47e858a2d86a991e078f7051074557e7a6903419eb51e24831`.

## English

RC40 was built from5f4dd46, independently reviewed, accepted on the native Intel
Mac and installed visibly with the existing transactional desktop installer.
PR59 merged both histories; both Linux lanes, remote tests and builds passed.
Runtime, desktop and native helper identities were read back live. Existing
configuration, credentials,8170 tasks,159 historical UNKNOWNs and58 queue holds
were retained. At installation the separate supervisor was unchanged with
AutoNext disabled. A later parallel coordinator changed only its continuation
profile; the original ten Core tasks were retained. A later observation reported
AutoNext enabled but stopped on an external claim; no new chain acceptance is
inferred by this installation task. ThreadDesk source integration, its CI/merge and the older installed TD peer are
separate states. No new public RC40 release or ARM/Windows acceptance is claimed.
