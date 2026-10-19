# Sechs Etappen: Umsetzung und tatsächliche Abnahme

Daniel hat am 20. Oktober 2026 die Umsetzung ausdrücklich autorisiert.
Codex implementiert und koordiniert, Grok prüft unabhängig über den vorhandenen
adressierten MCP-Nachrichtenweg. Ein Codex-Test ersetzt keine Grok-Prüfung.
Bestehende interaktive Sitzungen und Tunnel bleiben erhalten. Pro Etappe folgen
auf ein kleines Paket Implementierung, Grok-Prüfung, Korrektur und Nachprüfung.

| Etappe | Status | Nächster Nachweis |
| --- | --- | --- |
| 1 Ausgangspunkt | Gesichert; praktische ChatGPT-Leseprüfung und unabhängige Grok-Prüfung abgeschlossen | Sichtbare Übergabe ergänzen |
| 1a Sichtbare Übergaben | Neu von Daniel autorisiert, in Arbeit | Kira/Eve/Codex/Grok, Einfügen/Return/Bestätigung getrennt |
| 2 Freigaben | Offen | Gemeinsame Entscheidung und Matrix |
| 3 Aktivierung | Offen | Persistente Wartung und Fehler-/Parallelitätstests |
| 4 Client-Lesewege | Offen | Gleiche Rechte, reservierte Lesekapazität, Lastprüfung |
| 5 Modulgrenzen | Offen | Fachliche Abfragen, austauschbarer Transport |
| 6 Ausgabeablage | Offen | Begrenzte Rohdaten, unveränderte historische Audit-Kette |

## Etappe 1: gesicherter Ausgangspunkt

- Paket `0.8.0rc3`; Quellpin `4188f001d405a9f04ee63f6bbe1b088c6f39d26e`;
  Dokumentationscommit `d9727ac1a484281f4a49aae99dab7f89b82bdacd`;
  Testergänzung/HEAD `56809213d956b2c08e974dbb254b248878cea9e0`.
- Lokaler unveränderlicher Ausgangstag `architecture-baseline-0.8.0rc3-20261020`;
  Arbeitszweig `architecture/six-stages-20261020`.
- Produktiver Dienst: PID 46820, Instanz `f97eff577f454bf9a397b2a3b396e55b`.
  Der tatsächliche ChatGPT-Aufruf `policy_inspect` bestätigt geladene Quelle und
  Konfiguration jeweils als `matches_loaded`.
- Konfiguration: `~/.config/kirabridge/config.toml`, Datei-SHA256
  `67240b187b0f84207dc9118fd59edce468e3f24ba8f5c4dcceb5a730a9e1e8cf`,
  wirksamer SHA256 `63417ca175b7a866e79c8f1ebcedb31380e5680594304b1d11a9af63d3b116fc`.
- Quellmanifest (69 Python-Dateien):
  `fa28d75f679f46d03498a58e0eadcc1ec418dedce53e2b189f87c3d2aea2030e`.
- 65 vorher vorhandene unversionierte Dateien wurden erhalten und zusätzlich
  mit SHA256-Manifest privat gesichert. Hinzu kommen Konfigurationskopie und
  konsistente SQLite-Sicherung. Ort:
  `~/.config/kirabridge/repairs/architecture-six-stages-20261020/`.
  Diese Sicherung ist ein Beleg, kein Auftrag zum Zurücksetzen aktueller Daten.
- Produktive Datenbank meldet tatsächlich `PRAGMA user_version=2`; die bisherige
  Architekturdokumentation mit Version 1 ist entsprechend berichtigt.

### Praktische Prüfung und Grenzen

Über die tatsächliche bestehende ChatGPT-Werkzeugbindung liefert `agent_status`
beide nativen Fenster: Codex Fenster 22104, TTY `/dev/ttys000`, Wurzel-PID 94023,
Codex-PID 94386; Grok Fenster 22228, TTY `/dev/ttys002`, Wurzel-PID 6957,
Grok-PID 6986. `session.read` über das bereits zwischengespeicherte
`task_request`/`task_get` schloss als Auftrag
`stage1-codex-read-1792453244373` ab und lieferte 1018 Zeichen tatsächliche
Codex-Ausgabe. Abschlussmeldung wurde verarbeitet und quittiert.
Keine Eingabe und kein Neustart dieser Sitzungen wurde vorgenommen.

Die frühere tatsächliche Eingabeprüfung betraf ausschließlich ein eigenes
unbeschäftigtes Testterminal und ein einmaliges `printf`; siehe
[CHATGPT-TERMINALS-20261020.md](CHATGPT-TERMINALS-20261020.md).
Das belegt weder eine Testeingabe in den laufenden Codex noch eine hörbare
Antwort in Grok Voice. `busy` ist keine Aussage über Antwortbereitschaft.

Die dauerhafte Kira-Ausnahme `automatic_operations=["session.input"]` bleibt
erhalten. `session_input_policy.enabled=false` deaktiviert den zusätzlichen
Terminal-Bestätigungspuffer, nicht den Terminalzugang. Die eigenständige
Voice-`go-go-go`-Regel bleibt aktiv.

### Tatsächliche Grok-Kommunikation

Adressierter Auftrag Codex → Grok: Sequenz 108,
`e90c29fc-7c39-4fbb-b8b7-fb276fd8bfc8`, Konversation
`architecture-six-stages-20261020`. Zustellung und gestarteter Grok-ACP-Lauf
`channel-734393fe935c437aad9c587322250c11` sind belegt. Ergebnis:
`unknown`, `agent_timeout`, keine Antwort. Das ist keine Grok-Abnahme.
Ein kleinerer ausschließlich lesender Prüfauftrag folgte als Sequenz 109,
`adc81025-1d39-40e1-baf8-6eca78270ae6`. Auch dieser Lauf endete nach der
tatsächlich konfigurierten 90-Sekunden-Grenze mit `agent_timeout`, ohne Antwort.
Beide unbekannten Ausgänge bleiben unverändert und werden nicht wiederholt.
Der ausdrücklich neue reine Leseprüfauftrag
`architecture-stage-1-grok-extended-20261020` nutzt denselben echten Grok-ACP-
Adapter über die vorhandene `agent.execute`-Schnittstelle mit 300 Sekunden
und eigenem dauerhaftem Rückkanal. Konfiguration, Dienst und bestehende
interaktive Grok-Sitzung wurden dafür nicht verändert. Der Lauf ist abgeschlossen,
Grok-ACP-Sitzung `01a1568e-6f98-7262-8c67-fb30828e6cfa`, `stop_reason=end_turn`.
Grok bestätigt unabhängig die drei geprüften Aussagen (Puffer, vorhandene
Ausnahme, Schema 2) und nimmt dieses begrenzte Paket ab. Er hat Quelltext und
betroffene Konfigurationsstellen gelesen, den ChatGPT-Live-Test und die
Live-Datenbankabfrage aber ausdrücklich nicht wiederholt. Rückmeldung privat
in `grok-stage1-review.json`; dauerhafte Abschlussmeldung verarbeitet und quittiert.
Diese Hintergrundprüfung ersetzt ausdrücklich nicht die anschließend von Daniel
geforderte sichtbare Zusammenarbeit im bereits offenen Grok-Fenster.

## Ergänzendes Paket 1a: verbindliche sichtbare Übergaben

Daniel verlangt die sichtbare Kette Kira → Codex → Grok. Die zentrale Route gilt
für alle Absender einschließlich Kira (`chatgpt`), Eve (`grok_app`), Codex und
Grok. Eve ist eine Voice-Identität und kein CLI-Fenster. Ziel ist das jeweils
eindeutig gebundene bestehende Agentenfenster. Kein stiller Ersatz durch neue
Hintergrundsitzungen. Vor jedem Zugriff werden Fenster, TTY, Sitzungswurzel und
Agenten-PID erneut geprüft. Einfügen, Return und authentifizierte Bestätigung
erhalten getrennte Zustände und eine stabile Auftrags-ID. Unklare Ausgänge
werden nicht automatisch wiederholt. Bereits laufende Arbeit wird abgeglichen.
Die bisherige Voice-Freigabe für Kira und Eve bleibt getrennt erhalten.

Die 595 bestandenen Tests und die Paket-/Lint-/JavaScript-Prüfungen des
Reparaturstands sind historische Belege; sie wurden für diese reine
Ausgangssicherung nicht erneut ausgeführt und ersetzen spätere Etappenprüfungen
nicht.
