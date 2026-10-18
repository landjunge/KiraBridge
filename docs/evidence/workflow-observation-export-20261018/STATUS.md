# AA-C03 / KB-C05 – tatsächlicher begrenzter Leseexport

18.10.2026. Eigener Worktree/Branch `seven-tools-observations-20261018`, Basis
`583c000a8f226d5d9e71c51310fb0a81a3bafb49`. Nur neue spezifische Dateien; Root-M2-
Quelle, echte laufende M2-Session/-DB, Runtime, Konfiguration und andere Sessions
wurden nicht benutzt oder geändert. Keine produktiven Rollen/Grants/Stopps.

## Implementiert

`src/kirabridge/observation_export.py` mit bestehender task.read-Prüfung,
principal-/Task-/Ownergrenzen, mode=ro/query_only, Snapshotcursor und vorhandenen
Auditbezügen. `scripts/export_workflow_observations.py` lädt lediglich vorhandene
Konfiguration und erzeugt keinen Store/Bridge. Kein neuer persistenter Sender,
Transport oder Queue. [Vollständiger DE/EN-Vertrag](../../WORKFLOW-OBSERVATION-EXPORT.md).

- Originale Auditseq/-hashes und damalige Status/Zeitbezüge erhalten.
- Nur historischer vorhandener, hashgeprüfter Preflight liefert Runtimebezug;
  heutige Servicefingerprints werden nicht rückwirkend verwendet.
- Aktuelle Handoffkorrelation separat; keine erfundenen historischen Projekt-
  oder Workflowkennungen. Keine Step-Requesthash-/Workflowhash-Verwechslung.
- Begrenzung:16Tasks,500Auditzeilen,4KiB/Record,64KiB Ereignisdaten/Seite,
 16KiB Metadaten/Quellrecord,64Diagnosen/16Korrelationen und SQL-Zeitgrenzen.
  Filter-, Daten-/Vorverlaufs- und Anzeigegrenzen bleiben UNKNOWN.
- Args/Result/Error/Event-Payloads/Prompts/Dateiinhalte/Pfade/Secrets werden nicht
  exportiert. Kein generischer Config-/Runtime-/Store-Dump.
- Claimed Antwort ist kein answer_recorded, Dateiabschluss kein Agententurn,
  Turnende/Review/Ankunft keine verifizierte Projektabnahme.

## Tatsächliche Prüfungen

33 spezifische Fälle in gezielten Teilrunden:

- Erster enger Lauf:27 bestanden in0.66s, einschließlich vorhandener Eigentümer-
  und Cap-Prüfung, Historie/Minimierung, Cursor/Fremdscope, Hashfehler, Bytegrenze,
  aktuelle Korrelation, unsichere Datei/Symlink und Skript ohne Storeinitialisierung.
- Nach enger Statussemantik-/AA-Pin-/echter Subprozess-Ergänzung:4 betroffene Fälle
  bestanden in1.23s (davon2 neu). Optionale reale AA-Vertragsannahme überprüft.
-2 zusätzliche Neustart-/Diagnosengrenzen-Fälle bestanden in0.41s. Ein geschlossener
  Schreiber wird zum Lesen nicht neu initialisiert; Schema/Taskstatus bleiben
  erhalten, Events/Source-ID identisch.66 ungültige Records ergeben64 Diagnosen
  plus2 ausgelassene, ohne Endlosschleife oder Payload-Ausgabe.

-2 zusätzliche Sidecar-/Fehlerfälle bestanden: symlink-SHM wird vor SQLitezugriff
  abgewiesen und Sentinel bleibt unverändert; SQLite-Fehler wird geheimnisfrei
  gemeldet, genau ein Versuch, bestehender Task bleibt queued.

Keine alte allgemeine Suite nochmals lokal wiederholt. Ruff/Format/diff Checks
beziehen sich auf die neue Exportfunktion und deren Tests/Skript; reguläre
Projekt-CI läuft separat nach Push. Keine neuen Pflicht-Tokens/AA-Checkouts.

## Kleiner echter Funktionnachweis

Ein isolierter temporärer RuntimeState nutzt die vorhandenen echten
Store-/Audit-/Transitionfunktionen mit ausdrücklich synthetischen Datensätzen.
Kein Dispatcher/Agent/Tunnel/Provider und keine Produktivdaten. Ein wirklicher
Python-Subprozess ruft das neue Skript auf;3 minimierte Auditereignisse gehen über
stdout an den tatsächlichen vorhandenen AA-Leser. Der Test ist ein echter
Lese-/Format-/Minimierungsnachweis, keine echte Agentenarbeit/Projektabnahme.

- `selected-source/segment-1.jsonl`: tatsächliche begrenzte stdout-Ausgabe.
- `page-status.json`: tatsächliche minimierte stderr-Seitenmetadaten.
- `aa-reader-report.json`: reale vorhandene AA-Projektion; Identität, Wirkung und
  Gesamtabdeckung unbekannt, fehlender Artefakt-/Sequenzbeleg sichtbar.
- `proof-summary.json`: tatsächlicher Ablauf, Quelle/Fingerprints und Grenzen.
  Erste eigenständige Probe wurde wegen eines Symlink-Temp-Pfads verweigert;
  finale Probe nutzte dessen tatsächlichen privaten Pfad, ohne die Sperre zu
  lockern. Nachfolgende WAL/SHM-Guard-Ergänzung ist separat mit neuem Quellhash
  und Gegenfällen vermerkt, ursprünglicher Probe-Hash bleibt erhalten.
- AA-Referenzpin `c62149b567ce090df44fa8e942906c3025e879be`, Module:
  workflow.py SHA256 `50d222c156d535cfd3f502b498146d63f5681945898c03f8e9dd51b6c53e8c80`,
  workflow_rules.py SHA256 `44a85a86f8d016b508df186f23634590245ca9ad81dbdf301e151a83026bdf86`.
  Lokale optionale Prüfung validiert Quellbytes vor Import. Normaler Export/CI
  benötigt diese private Cross-Repo-Installation nicht.

## Offen und Integration

Kein neues MCP-Wire, keine geladene Runtimeänderung, kein Web-/Chat-/Sprachpush.
Root integriert eine spätere authentifizierte Lesefunktion getrennt. Produktive
externe Identität, Tunnelereignisse und Gesamtauftragserfüllung bleiben
unbeobachtet; historische fehlende G01-Businessfelder werden nicht nachgetragen.
Die SQL-VM-Grenze ist kein garantierter harter OS-/Dateisystemabbruch.

Bestehende Belege, Audit, Queue, Credentials und Daten unverändert. Revert der
neuen Quelldateien reicht als Rückweg; keine Migration oder Datenbereinigung.
README/Model/Store/Bridge/CLI/Config/Sicherheitskonfiguration werden hier nicht
verändert; ausschließlich die ausdrücklich zugewiesenen neuen Dateien/Belege.
