# Windows dev3 und macOS RC31/RC32 · Integration vom 4. November 2026

Dieser unveröffentlichte Quellstand `0.8.0rc33.dev1` vereinigt die vollständigen
Windows-dev3- und macOS-RC31/RC32-Linien. Er ist kein neues Release oder Nachweis
einer erfolgten Installation. Die bestehenden Plattformpakete behalten ihre
ursprünglichen Quellen und Nachweise.

## Integrationsmatrix

| Linie | Stand | Entscheidung |
| --- | --- | --- |
| main / RC30 | `21a6abda85aadc8d0c361b4106d328953af9aa02` | gemeinsamer Ausgangsstand |
| macOS RC31 | `0f554bc64ba7d0cecfa5898990f1df67fc6c0591` | vollständig in RC32 enthalten |
| macOS RC32 | `d8bbe61b55af2a1b76aaa57cbf3dd57110f4f3d8` | zuerst vollständig gemergt, enthält fünf Commits seit main |
| Windows dev3 | `62aae9d2d2a3e28967573c86fd64dbad9914f9e8` | anschließend gesamte abhängige Kette mit 37 Commits gemergt |
| 16 relevante Windows-Zulieferrefs | Keyboard, Core, Preview/MCP, Bootstrap, Fixtures, Dev-Kit, Provenance, Dokumentation | Vorfahren oder patch-equivalent in dev3; keine doppelte Übernahme |
| übrige ältere Entwicklungsrefs | Graph und Patchvergleich geprüft | enthaltene Arbeit nicht erneut übernehmen; unabhängige Zusatzfunktionen getrennt halten |

Der Branch `integrate/windows-dev3-macos-rc32-20261104` liegt in einem eigens
angelegten Integrationsworktree. Vorher wurden 89 registrierte Worktrees
inventarisiert: 84 vorhanden, fünf alte fehlend; sechs vorhandene Worktrees
enthielten fremde lokale Änderungen. Status, Index-/Diff-Hashes und
Inhaltsfingerprints dieser Änderungen wurden lokal gesichert. Kein fremder
Worktree wurde umgeschaltet, gestasht, bereinigt oder entfernt.

Drei spezialisierte Codex-Unteragenten prüften Windows, macOS und weitere
Branches/PRs/Releases. Windows- und macOS-Spezialisten prüften das vereinte
Runtime-Ergebnis zusätzlich unabhängig. Audit, Rohlogs und Teamberichte:
`/Users/landjunge/KiraBridge-integration-audit-20261104/`.
Die [Windows-Review](reviews/integration-20261104/windows.md) und
[macOS-Review](reviews/integration-20261104/macos.md) sind auch versioniert.

## Merge-Plan und tatsächliche Auflösung

1. Git-Graph, alle Worktrees samt Änderungen, Remote-Refs, offene/geschlossene
   PRs, Releases, Workflow-Trigger und Abhängigkeiten lesend erfassen.
2. Eigenen Branch von gepinntem main anlegen; RC32 einschließlich RC31 mit
   Merge-Commit `090fcaf66bf4a4ce840e4b3176317d7eb811b84e` übernehmen.
3. Windows-HEAD als vollständigen zweiten Entwicklungsarm mergen;
   Ergebniscommit `d7a0b0a2d316c5b53ba6946f29eaac57f8cbaa23`. Die drei
   Textkonflikte betrafen ausschließlich Versionszeilen: pyproject, __init__,
   uv.lock. Alle drei nennen jetzt `0.8.0rc33.dev1`; damit wird zugleich die
   Windows-Ausgangsabweichung dev3 gegenüber dev2 im Lockfile korrigiert.
   Abhängigkeiten und ihre Pins wurden nicht verändert.
4. Automatisch vereinte Bridge-/MCP-/Store-Hunks fachlich prüfen. Windows-ACLs,
   WAL-/SHM-Schutz, Desktoptransaktionen, Plattformverweigerung, Katalog und
   Dispatch bleiben neben NativeQueries, Event-Leseoptimierung und SQLite-Index
   erhalten. Die READMEs vereinen beide Plattformberichte und kennzeichnen
   diesen neuen Quellstand ausdrücklich als unveröffentlicht.
5. Gemeinsame Pythonintegration gezielt neu prüfen. Vorhandenen Test zur
   verweigerten nativen macOS-Leseoperation zusätzlich mit `win32` ausführen;
   Windows-Operationen bleiben unter `windows.keyboard.*` / `windows.window.*`.
6. Nach Ergebnissen und Review separaten Integrationsbranch synchronisiert;
   [Draft-PR #58](https://github.com/landjunge/KiraBridge/pull/58) gegen main
   angelegt und unabhängig zurückgelesen: offen, Draft, konfliktfrei mergeable,
   nicht gemergt. main, bestehende PRs/Releases und Installationen erhalten.

Zurückgestellte eigenständige Deltas sind ausdrücklich nicht als enthalten
bewertet: `fix/output-completeness-20261026` ergänzt terminal.output-Metadaten,
`fix/readiness-effective-20261026` ergänzt execution_ready. Sie sind keine
Voraussetzungen dieser Plattformintegration. README-PR #55 enthält zusätzliche
Produktnavigation/Icons, aber alte RC21-Downloads und ist ein eigener
Dokumentationsumbau. Lizenz-PR #47 und der Public-Sanitizing-PR #10 bleiben
gesondert. Historisch offene PRs werden weder pauschal gemergt noch geschlossen.

## Prüfungen am integrierten Stand

Eigene Python-3.11.15-Umgebung, ausschließlich mit
`uv sync --locked --offline --dev --python /usr/local/bin/python3.11`
aus dem lokalen Cache eingerichtet. 37 Pakete installiert, einschließlich des
gepinnten cryptography 48.0.1. Keine fremde virtuelle Umgebung verändert und
keine Dependencies neu aufgelöst. Nur das für Tests erforderliche lokale
Editable-Paket wurde erzeugt; kein auslieferbares Plattformpaket gebaut.

Die genaue Auswahl und Ergebnisse stehen im
[maschinenlesbaren Integrationsnachweis](evidence/integration-dev3-rc32-20261104.json).
Ergebnis: **622 bestanden, vier Windows-Coretests auf macOS übersprungen,
null Fehler**, 41,10 Sekunden. Ruff und Formatprüfung der drei gemeinsamen
Runtime-Dateien sowie Version/Testergänzung bestanden; Lockprüfung offline
und Diff-Prüfung bestanden. Beide unabhängigen Plattformreviews fanden keine
blockierenden Integrationsfehler.
Sie umfasst NativeQueries/Transport, Task-/Beobachtungs-Hotpaths, MCP- und
Read-/Batch-/Range-Verträge, EventJournal/Prozessausgaben und Windows-Core,
Tastatur/Shortcuts/Fenster/Manager/Preview. Die echten Windows-Coretests sind
auf macOS zu überspringen und gelten damit nicht als Windows-Ausführung.
Swift-Produktquelle, Native-Harnesses und Windows-Backendquellen sind gegenüber
ihren geprüften Ausgangslinien unverändert; ihre datierten nativen Belege wurden
auf Hash-/Quellenbindung geprüft und nicht als neuer Integrationslauf gezählt.

## Aussage zu Windows

SendInput-Tastatur, Ctrl/Alt/Shift-Shortcuts und sieben abgesicherte
Fensteraktionen sind im gemeinsamen Quellstand enthalten. Die native
[dev3-Abnahme](WINDOWS-DESKTOP-20261104.md) belegt sechs frische Gastphasen für
`271605a5049255b007ea903a28bdfe40c51cf7f7`; bis Windows-HEAD wurden nur
Dokumentation/Belege ergänzt. Close bestätigt die einmalige Annahme eines
WM_CLOSE-Requests, nicht das Ende der Anwendung. Zielidentität und native
Handle-Wiederverwendung bleiben explizite Grenzen.

`scripts/build_windows_dev_kit.py` und `scripts/start_windows_preview.cmd` sind
absichtlich auf den historischen Release `0.8.0rc31.dev3` gepinnt. Sie wurden
nicht auf rc33 umetikettiert. Für einen künftigen Kandidaten ist der vorhandene
Moduleinstieg `python -m kirabridge.windows_preview` separat zu prüfen; die
historischen Launcher/Receipts ersetzen keine neue Paket-/Gastabnahme.

Der volle Python-Quellhash ändert sich durch RC31 und die gemeinsamen Dateien.
Vor Veröffentlichung/Installation eines konsolidierten Windows-Pakets sind
neue passende Staging-/Quellenmanifeste und sechs native Phasen erforderlich.
Windows-key-Globals, nativer stdio-Nachweis, Windows 10, ChatGPT/Voice und
vollständige Datei-/Prozess-/Terminalautomation bleiben außerhalb der bisherigen
positiven nativen Abnahme. Die laufende VM und ihre dev2/dev3-Installationen
wurden bei dieser Integration nicht gesteuert oder verändert.

## Aussage zu macOS

Direkte autorisierte native Reads, begrenzte AX-Unterbäume, Event-Index und
RC32-Attributbatches sind erhalten. `native.read` mit `windows.list` ist weiterhin
der macOS-Vertrag; Windows-Handleaktionen verwenden eigene Operationsnamen.
Baumgrenzen, frische Rechte-/Zielprüfung, sichere Felder und fehlende Atomarität
werden nicht durch Windows-Adapter oder Performanceoptimierung ersetzt.

Die [RC31](RC31-NATIVE-READS-20261103.md)- und
[RC32-Belege](RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md) gehören weiter ihren
Quellpins. Die unveränderte Swift-Quelle hat SHA256
`3b578d5ae885bd833c3f338b7b1c1c04e938308258df069386c9d37479721ace`.
Die gemessenen 16,856 → 8,138 ms für zwölf eigene Buttons sind historische
lokale Summarymessungen, keine neue Cloud-/Voice-/Gesamtbaum-Zeitmessung.
Für ein neues integriertes macOS-Paket fehlen eigener Build, Paketprüfung,
isolierte native Installerabnahme und kontrollierte Installation.

## Remote-, Release- und Sitzungsgrenzen

Beim Inventar: main `21a6abd`, RC31-PR #56 und darauf RC32-PR #57 offen/Draft.
Windows dev3 und macOS RC31/32 sind getrennte veröffentlichte Prereleases mit
fünf bzw. jeweils sieben Assets. Es wurde kein neuer Tag/Release/Asset angelegt.
Branch-Protection/Rulesets sind über die API mit HTTP403 nicht positiv prüfbar;
Commitstatus für die drei Ausgangsstände war leer. Lokale Tests sind keine
erfüllten GitHub-Pflichtchecks oder externe PR-Freigabe.

Push-/PR-Workflows könnten mehrere Plattformläufe und macOS-Paketbuilds starten.
Integrationscommits verwenden `[skip ci]`; keine dispatch-/release-Trigger und
kein `release/**`-Branch. Ein fehlender/übersprungener Check wird nicht als grün
ausgegeben. main wird nicht über unbekannte oder ausstehende Gates hinweg bewegt.

Frische lesende Core-Beobachtung bestätigt produktiv RC30, PID66439,
Instanz `777222cce58e4b38b503c2f3d20900e1`. Keine Dienste, OS-Rechte,
Credentials, Queues, historischen unknown-Tasks oder Terminal-/Agentensitzungen
wurden umgestellt. Der Rückweg besteht im Erhalt der bisherigen Quellen und
Installationen; es ist kein produktiver Rollback erforderlich.

Die unabhängige Abschluss-Healthabfrage bestätigte dieselbe Core-Instanz/PID,
Quellrevision und Permissionrevision. Der Vorher-/Nachhervergleich
07:03:22 → 07:11:07 UTC bestätigt bei allen **89 ursprünglichen Worktrees**
dieselben HEADs, Branches, Status-, Index-/Diff- und Inhaltsfingerprints; die
fünf fehlenden blieben fehlend. Alle sechs fremden schmutzigen Worktrees sind
unverändert. Neu ist ausschließlich der eigene Integrationsworktree. Lokaler
Detailbeleg: `evidence/preservation-check.json` im Auditverzeichnis.
