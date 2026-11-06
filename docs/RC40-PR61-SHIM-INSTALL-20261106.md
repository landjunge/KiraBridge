# RC40-Quellupdate: Grok-Routing-Fix aus PR61

6. November 2026. Folgekarte `BP-GROK-ROUTING-PR61-INTEGRATE-20261106`,
ThreadDesk 188ce4729a62/54b9ae9bf97e#439, im bestehenden Integrations-/Macauftrag.

[PR61](https://github.com/landjunge/KiraBridge/pull/61) wurde nach grüner
[PR-CI42233426554](https://github.com/landjunge/KiraBridge/actions/runs/42233426554)
regulär als Main `74fb441951402ba4cab0b17c18b444f4ca8d305d` gemergt. Der
Main-Dateibaum ist exakt der angenommene Head
`a5d381ae61146850ab83f332a032679d4d5896cf`. Die drei Fixdateien sind bytegleich
mit dem separat unabhängig geprüften Runtimefix 56c8c7e.

**Tatsächlich installiert bleibt Version 0.8.0rc40, jetzt mit Quellpin a5d381a.**
Es wurde keine Versionsnummer allein für den Auftrag erhöht. Der frühere
[RC40-Erstinstallationsnachweis](RC40-INTEGRATION-INSTALL-20261106.md) aus 5f4dd46
bleibt historisch erhalten. Beide gleich benannten Versionen werden über
Quellpin, Manifest und tatsächlichen Paketpfad unterschieden.

## Änderung und Abnahme

Der native Grokadapter und der Effortshim lieferten zuvor beide
`--no-auto-update`; die CLI wies die doppelte Option schon vor einem Modellturn
ab. Der Shim ergänzt sie jetzt nur, wenn vor dem Argumenttrenner `--` keine
exakte Option vorhanden ist. Originalargumente, Reihenfolge und bereits
vorhandene Duplikate werden erhalten. Eine Grok-spezifische Shimrevision 2
verwendet einen neuen Cachepfad; alte unveränderliche Shims und ihre Belege
bleiben erhalten. Codex-Shims und bestehende Modell-, Effort-, Umgebungs-,
Billing- und Readonlygrenzen sind unverändert.

Vorhandene Quellenabnahme: 109 gezielte Autorenfälle mit Interpreter-/Import-/
Quellbindung auf dem neuen Mainbasisstand bestanden, Ruff check/format bestanden.
Der unabhängige statische Codexreview des identischen Drei-Datei-Payloads fand
keine P1/P2-Befunde. Die vorhandene Parserprobe nutzte ausschließlich `--help`:
alt Exit2, korrigierter Shim Exit0, kein Modellaufruf. Die tatsächliche PR-CI
bestand beide Linux-Python-Lanes einschließlich Remoteprüfungen und Builds.
Auch die [Main-CI42235891732](https://github.com/landjunge/KiraBridge/actions/runs/42235891732)
bestand: je Python 3.11/3.13: 4942 Legacyfälle, 224 erwartete Plattform-/Prerequisiteskips,
zusätzlich 29 Remoteprüfungen ohne Skips und erfolgreiche Builds.

## Paket, sichtbare Installation und Liveprüfung

Das native Intel-Paket wurde aus sauberem a5d381a gebaut: 737 Manifestmitglieder,
228 Wheel-Runtimedateien exakt Gitquelle, Intel x86_64 und codesign verify strict
bestanden. Release-Smoke und echte isolierte macOS-Abnahme bestanden: Wechsel
vom RC40-Quellpin 5f4dd46 auf a5d381a, Datenerhalt, Idempotenz, Neustart, KeepAlive,
Rückweg auf den alten Pin und frische Installation. Beide Pakete tragen RC40;
die tatsächlichen Quell-/Releasepfade blieben getrennt. Weil eine Versionsprüfung
allein gleich benannte RC40-Pakete nicht unterscheidet, bestätigte eine zusätzliche
isolierte, authentifizierte Quellpfadprobe ausdrücklich 5f4dd46→a5d381a→5f4dd46;
Konfiguration und Zugänge blieben gleich, Testdienst anschließend abwesend.
Offene Completionlesung
endete ohne Replay; der Testdienst wurde unabhängig als entfernt bestätigt.

Nach frischer Prüfung von 0 aktiven Primärtasks/0 unheld Receiverjobs und gesicherten
Hash-/Modusständen wurde das Paket im bestätigten eigenen sichtbaren Terminal
6274/ttys000/PID755 mit `--desktop --require-visible-terminal` aktiviert: Exit0.
Letzter authentifizierter CLI-/MCP-Readback: Dienst PID2209,
Instanz `51d442713afe403ab3a79020e6c8c400`, VersionRC40, Paketpfad
`0.8.0rc40-a5d381ae6114/source/.venv/lib/python3.11/site-packages/kirabridge`.
App und nativer Helfer melden ebenfalls a5d381a; Bedienungshilfen beim frischen
Helfer `granted=true`, keine neue Rechteanfrage. Der sichtbare Terminalbefehl
`PR61_RC40_SOURCE_LIVE_OK` bestand. Eigenes Fenster geschlossen und in frischem
Katalog unabhängig als abwesend bestätigt; fremde Sitzungen erhalten.

Alle 228 tatsächlich installierten Wheeldateien wurden direkt mit dem geprüften
Wheel verglichen. Zusätzlich wurde das installierte Routingmodul mit einer
lokalen deterministischen argv-Fixture ausgeführt: genau eine Updateoption,
Originalargumente korrekt, synthetische API-Umgebungsvariable entfernt, alte
Shimdatei unverändert. Das war kein Grok-/Codex-Provider- oder Kettenlauf.

## Daten, Rückweg und getrennte Koordination

Alle 8194 vor diesem Update vorhandenen Main-Tasks sind nach ID/Zustand/
Fehlerbytes unverändert; darunter 160 historische UNKNOWNs. Alle 58 Holds sind
erhalten. Konfiguration, Zugänge, Koordinatorprofil und launchd-Plist blieben
gegenüber der frischen Sicherung nach Hash und Modus gleich. Die 21 bisherigen
separaten Core-Taskzustände blieben unverändert; kein UNKNOWN wurde wiederholt.
Rückweg: `/Users/landjunge/.local/share/kirabridge/install/backups/20261106-154707-fb9596c3`.
Der vorherige RC40-Quellpin bleibt installiert verfügbar; der vorhandene
Rollbackweg erfordert erneut einen bestätigten sichtbaren Leerlauf. Alte
Datenbanken werden nicht über neue Nutzerdaten zurückkopiert.

Der separate Supervisor97450 auf 56c8c7e wurde nicht umgestellt. Seine andere
Sitzung hatte die reale Codex→Grok-Structured→Codex-Verifier→Checks→Receipt-Kette
mit automatischem Folgestart nach 23,643Sekunden abgenommen. Das ist deren
Abnahme, kein neuer Durchlauf dieses Installationsauftrags. Alter Grok-Fixreview 02
und andere UNKNOWNs bleiben historische Originale. Interne Evidenzwerkzeuge
und Anleitung aus df33f5a wurden nicht still in PR61 aufgenommen.

Quellenmerge, Paketabnahme, Installation, Livefunktion, adressierte Übergabe
und beobachteter Betrieb werden getrennt festgehalten. Kein neues öffentliches
RC40-Release, keine ARM-/Windowsabnahme oder unbegrenzte Dauerarbeit behauptet.

## Belege

`~/.local/state/pr61-mac-integration-20261106/`: Quell-/Reviewbindung, tatsächliche
CI-Quittungen/Rohlogs, Paketmanifest, macos-acceptance/evidence.json, sichtbarer
Installationsstart/-abschluss, installierte Shimprobe, Erhalt- und Livebelege.

Bundle-SHA256: `768fbecf4343242a55250eb545e4574397482f50b335eeafcc5d2b91ced55388`.
Wheel-SHA256: `df7d0d31119d098b43d186f2961911e94918a670ab1b556123be83933fe17c41`.

## English

PR61 removes the duplicate injected Grok update option while retaining original
argv and immutable historical shims. Both reviewed source pins carry the same
three-file payload. RC40 was rebuilt from a5d381a, natively accepted and visibly
installed without a version-number bump. The responding runtime, desktop and
helper identities bind that exact source. Installed wheel bytes and a local argv
fixture passed; no new provider/chain run or historical UNKNOWN replay occurred.
The separate supervisor remains unchanged. No new public release is claimed.
