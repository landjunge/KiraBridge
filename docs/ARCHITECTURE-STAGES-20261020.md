# Sechs Etappen: Umsetzung und tatsächliche Abnahme

Daniel hat am 20. Oktober 2026 die Umsetzung ausdrücklich autorisiert.
Codex implementiert und koordiniert, Grok prüft unabhängig über den vorhandenen
adressierten MCP-Nachrichtenweg. Ein Codex-Test ersetzt keine Grok-Prüfung.
Bestehende interaktive Sitzungen und Tunnel bleiben erhalten. Pro Etappe folgen
auf ein kleines Paket Implementierung, Grok-Prüfung, Korrektur und Nachprüfung.

| Etappe | Status | Nächster Nachweis |
| --- | --- | --- |
| 1 Ausgangspunkt | Gesichert; praktische ChatGPT-Leseprüfung und unabhängige Grok-Prüfung abgeschlossen | Sichtbare Übergabe ergänzen |
| 1a Sichtbare Übergaben und Aufhebung Voice-Gate | 0.8.0rc4 aktiviert: 660 Tests bestanden, Grok-Prüfung und produktive sichtbare Übergabe abgeschlossen | Ursprünglichen beschäftigten Codex nicht für Eingabetest unterbrechen |
| 2 Freigaben | 0.8.0rc5 aktiviert; 313 gezielte Tests und unabhängige Grok-Abnahme | Normale Voice-/CLI-Wege beim weiteren Umbau erhalten |
| 3 Aktivierung | Kandidat 0.8.0rc6: 732 Tests bestanden und Grok-Abnahmen vorhanden; Aktivierung folgt | Wartungs-/Fehlerpfade prüfen, korrigieren, aktivieren |
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
Voice-`go-go-go`-Regel war an diesem gesicherten Ausgangspunkt aktiv. Daniel hat
sie anschließend ausdrücklich aufgehoben; siehe Paket 1a und die aktuelle
[Voice-Policy](VOICE-POLICY.md). Historische Belege bleiben unverändert.

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
Daniel hat die bisherige zusätzliche Voice-Tokenpflicht für Kira und Eve danach
ausdrücklich aufgehoben. Neue Nachrichten werden ohne Sondertoken und ohne
Entfernung eines wörtlichen Markers weitergegeben. Normale Rechte bleiben
erforderlich; alte Puffer werden nicht automatisch freigegeben. Der Parser
akzeptiert `voice_messaging.release_required` ausschließlich als `false`.

### Tatsächliche sichtbare Zusammenarbeit und Korrekturen

- Erster sichtbarer Auftrag `arch-1a-visible-grok-review-20261020`: eingefügt,
  wegen nicht sichtbarer Auftrags-ID vor Return angehalten (`unknown`). Nach
  dem angekündigten manuellen Return folgten authentifizierte Grok-Quittung und unabhängige
  Rückmeldung, Sequenz 111, `0d68c1f6-0b70-4fe0-91ed-ce274d014570`.
  Grok führte selbst 30 Tests aus. Kein erneuter Prompt und kein zusätzliches
  Return wurden für diesen Auftrag geschickt.
- Grok-Befunde: Promptgrenze vor Inbox-Anlage prüfen; verspätete Antworten ohne
  erneute Eingabe abgleichen. Beides korrigiert und gezielt nachgeprüft.
- Nachprüfung `arch-1a-grok-check2-20261020`: mehrzeiliger Prompt tatsächlich
  automatisch eingefügt, separates Return, geleertes Eingabefeld, Grok-Quittung
  und Ergebnis `17842889-3d88-4703-a7cb-e18e7d94ed34`. Grok bestätigt wörtlich
  „Sichtbarer Return funktioniert.“ Neue Befunde zu alten Eingabefeldern im
  Lesefenster, terminalem Abschlusszustand und Konfliktprüfung wurden korrigiert.
- Literal-Paste verwendet ausdrücklich den normalen Terminal-Menübefehl.
  Ein Tastaturkürzel hatte stattdessen maskierte Leer-/Sonderzeichen erzeugt.
- Reale Codex-Felder fassen große Pastes als `[Pasted Content N chars]` zusammen;
  Grok zeigt je nach Fenstergröße `[Pasted: N lines]` und eine Vorschau. Die
  Prüfung berücksichtigt diese tatsächlichen Darstellungen, prüft den letzten
  Eingabebereich und protokolliert die Art des beobachteten Belegs. Eine
  Zeichenanzahl oder ein Fingerprint allein ist kein Identitätsnachweis.
- Fehlendes/geändertes Ziel blockiert alle Adapter, einschließlich eines
  Grok-API-Adapters als vermeintlichem Ersatz. `enabled` akzeptiert persistent
  ausschließlich `true`. Auch direkte `session.input`-Aufträge an erkannte
  CLI-Prozesse müssen über die zentrale Route gehen. `dispatch=false` darf für
  Fragen/Arbeit an CLI-Agenten keine unsichtbare Ausführung auswählen.
- Rückantworten werden über den laufenden anfordernden MCP-Aufruf und die
  dauerhafte Inbox zurückgegeben; beide ursprünglichen Terminalbindungen werden
  vor der Ergebnisrückgabe erneut geprüft. Ohne aktiven Leser bleibt die Inbox
  dauerhaft erhalten. Eine Bildschirmdarstellung wird serverseitig nicht als
  bewiesen ausgegeben (`client_not_attested`).

### Neue Fenster: Verantwortlichkeit und verbindliche Begrenzung

Codex öffnete für einen interaktiven Eingabetest selbst das zusätzliche Fenster
`terminal:23115:ttys001`, Wurzel-PID 52988, Codex-PID 53010. Das wurde Daniel
offengelegt. Zuerst blieb dessen Collapsed-Paste unbestätigt und ohne Return;
nach Beobachtung der exakten Zeichenzahl erfolgte einmalig ein separates Return.
Der Agent quittierte die Nachricht; eine endgültige Antwort ist bislang nicht
belegt. Nach Daniels anschließender ausdrücklicher Vorgabe wurden dort keine
weiteren Eingaben geschickt und das Fenster wurde nicht geschlossen.
Die anschließende ausschließlich lesende Prüfung des genau zugehörigen
Providerprotokolls belegt `turn_aborted` am 20. Oktober um 00:05:00 UTC,
Sitzung `01a1569d-e167-74c2-ba80-1258c4046614`. Ein Verursacher ist nicht
belegt. Der bereits abgebrochene Turn wurde als `interrupted` abgeglichen,
ohne neuen Input, Signal oder Fensterschließen. Diese Abnahme ersetzt keinen
Eingabetest im ursprünglichen Codex-Fenster; dieses bearbeitet währenddessen
den laufenden Umbau und wird nicht unterbrochen.

Ab dieser Vorgabe sind auch für Tests ausschließlich die ursprünglichen Fenster
zulässig: Codex `22104/ttys000/94023/94386`, Grok `22228/ttys002/6957/6986`.
Grok hat diese Regel in seiner bestehenden Sitzung als Auftrag
`arch-1a-route-policy-20261020` ausdrücklich bestätigt.

Ein frei behauptbares `user_requested_agent_window=true` wurde nach Kiras
Prüfhinweis verworfen. `session.open` benötigt stattdessen einen einmaligen
`window_authorization`-Token vom authentifizierten lokalen Bedienweg, gebunden
an Principal, Task-ID, Arbeitsverzeichnis und vollständiges argv. Es gibt keinen
MCP-Aussteller. Verbrauch und Aufgabenanlage teilen eine Transaktion;
die Transportgrenze prüft denselben Beleg. Das gilt auch für leere Shell und
Wrapper. Zusätzlich reserviert die Transportgrenze in `window_dispatches`
genau einen Versuch pro Token und Aufgabe und prüft die ursprüngliche Frist.
Auch ein direkter zweiter `open` und ein unklarer erster Ausgang erlauben
keinen weiteren Fensterstart.
Die gesamte normale Terminalausführung bei freiem OS-Zugriff unter
derselben UID ist damit ausdrücklich keine Betriebssystem-Sandbox: Ein Agent
mit vollem Shell-Zugriff könnte Betriebssystembefehle oder lokale Verwaltungs-
funktionen selbst aufrufen. Die Bridge verspricht keinen Schutz gegen dieses
andere Vertrauensmodell und erweitert oder beschneidet diese OS-Rechte nicht.

### Prüfung und Aktivierungsstand

Commit `58de36b` ist auf `architecture/six-stages-20261020` gepusht.
Der produktive Dienst wurde bei nachgewiesen leerer aktiver Queue ersetzt;
die SQLite-Abfrage war nur lesend, kein Prozessaufruf hielt eine Schreibtransaktion.
Agenten, Fenster und Tunnel blieben erhalten. Der neue Dienst PID 60271,
Instanz `05b026ed12144002aec474010be8af65`, meldet Version `0.8.0rc4`.
Aktive Datei-SHA256:
`642ef01516ff2ff8199980556b733ac97525329e78d22b14f50a93ed673d54cd`;
wirksame Konfiguration:
`1786b287511313d7bbd518006b4afcbc26c445a929ca1a011385faa999e4089a`.
Der tatsächliche ChatGPT-Zugang bestätigt Konfiguration und Quelle jeweils
als `matches_loaded`, Terminalausnahme vorhanden, Voice-Tokenpflicht aus.

Produktiver Auftrag `arch-1a-live-rc4-20261020`, Nachricht
`fcd20a65-cdb7-4499-b972-1e4a20a74e57`, Übergabe
`channel-b6b163fa9efe4cd898571295bca173b9`: Einfügen, einzelnes automatisches
Return, geleertes Feld, authentifizierte Grok-Quittung und Antwort
`446a7913-7a4c-486d-aacb-172a26235a3e` sind getrennt belegt.
Grok bestätigt Empfang und geladenen Stand unabhängig im ursprünglichen Fenster;
seine Antwort wurde verarbeitet und quittiert. Private Belege:
`rc4-loaded-proof.json`, `activation-idle-core.json`, `rc4-live-handoff.json`.
Die beim ersten Queue-Zustand noch unzutreffende Bezeichnung `managed_receiver`
wird als konkrete Anzeigekorrektur in Etappe 2 mitgeführt; die tatsächliche
Ausführung erfolgte über `existing_visible_terminal`.

Der positive Eingabetest im ursprünglichen Codex bleibt offen, solange er den
laufenden Auftrag bearbeitet. Handy-/Voice-Audio wurde hier nicht geprüft.

Der unveränderte Python-Kandidat hat 660 Tests bestanden
(`-W error::pytest.PytestUnraisableExceptionWarning`, 173,89 Sekunden).
Ruff und Paketbau sind erfolgreich; Wheel-Inhalte stimmen mit allen 70
Python-Quelldateien überein. Quellmanifest:
`9f05b61b773dc93fb6e5e02e3068eb250768dcfdd105ec91f2b4444a16c4fbd1`.
Wheel-SHA256:
`813ffdebaa6932192101c688600c386263d2124d86b615b940a4c8dee21d0578`.

Ein früherer
Gesamtlauf: 612 bestanden, ein Test erwartete noch das ausdrücklich abgelöste
Voice-Gate; dieser Test wurde auf den unmittelbaren tatsächlichen Antwortrückweg
umgestellt und gezielt erfolgreich ausgeführt. Ein späterer Lauf traf die
bereits vorhandene knappe Startfrist eines Fake-CLI-Tests; er bestand separat
und danach im Gesamtlauf. Die Anwendungsfrist wurde nicht verändert.

Grok führte im bestehenden ursprünglichen Fenster selbst 91 Tests aus und
meldete drei weitere konkrete Befunde. Nach Korrektur führte er als Auftrag
`arch-1a-grok-fixes4-20261020` selbst 64 Tests erfolgreich aus und bestätigte:
„Die drei Fixes halten. Kein verbleibender konkreter Fehler in diesen drei
Punkten.“ Seine tatsächlichen Rückmeldungen sind privat unter
`grok-visible-review-1a.json`, `grok-visible-review-1a-check2.json` und
`grok-visible-fixes4.json` erhalten. Das ist eine begrenzte unabhängige
Prüfung, keine vollständige Sicherheitsabnahme.

Ein weiterer echter HTTP-MCP-Test prüft die ursprüngliche Auftragsnachricht,
genau eine authentifizierte Agentenantwort und keine zweite interne
Auftragskopie. Negative Tests decken alle vier Absender, alle Adapter,
fehlende/veränderte Ziele, Rückzielverlust, belegte Agenten sowie Shell- und
Wrapper-Starts ohne vertrauenswürdigen Auftrag ab. Alte Inbox-Aufträge werden
durch einen Retry nach dem Update nicht nachträglich dispatched.

Die dynamisch erzeugten Einfüge- und Return-Skripte werden zusätzlich durch
`osacompile` ohne UI-Ausführung kompiliert. Eine Syntaxkorrektur erfolgte vor
der letzten Gesamtabnahme. Paste öffnet den normalen Menüpunkt ausdrücklich
und erhält die Zwischenablage bis zum beobachteten Echo; Return ist separat.
Vor einer erneuten Einfügung im vierten Grok-Paket wurden das leere aktuelle
Feld, fehlende Quittung, das Fehlen eines Return-Versuchs und das unveränderte
zugehörige Grok-Providerprotokoll ohne diesen Nutzerturn abgeglichen.
Die erste fehlende Einfügung und der folgende Compile-Fehler bleiben erhalten;
erst anschließend folgten Einfügen, ein einziges Return und die echte Quittung.

Der tatsächliche bisherige Daemon bestätigte außerdem über einen rein lesenden
`terminal.execute`-Aufruf `uiEnabled=true`, `menuBarReadable=true`, Exit 0
(`architecture-ui-daemon-probe-20261020`). Das ist kein Eingabetest und noch
kein Nachweis einer gesprochenen Antwort auf dem Handy.

Ein alter providergebundener verwalteter Codex-Resume darf die zugeordnete
sichtbare Sitzung nicht ersetzen; er wird vor einer Eingabe als
`visible_owned_resume_unsupported` gemeldet. Die Integration dieses separaten
Workflowpfads bleibt in Etappe 5 offen. Ein sichtbarer UI-Turn wird nicht als
erfundene verwaltete Provider-Sitzung ausgegeben.

Die neue kanonische Konfiguration ist privat als
`config-pending-visible.toml` vorbereitet und validiert. Sie bindet ausschließlich
die zwei ursprünglichen Fenster und erhält beide dauerhaften Terminalfreigaben.
Sie ist noch nicht in die kanonische Datei übernommen. Der produktive Daemon
läuft während dieser Entwicklungsprüfung weiterhin mit dem Ausgangsstand;
Codeänderung, Aktivierung und praktischer Daemontest werden getrennt belegt.

Die 595 bestandenen Tests und die Paket-/Lint-/JavaScript-Prüfungen des
Reparaturstands sind historische Belege; sie wurden für diese reine
Ausgangssicherung nicht erneut ausgeführt und ersetzen spätere Etappenprüfungen
nicht.

## Etappe 2: eine verbindliche Freigabeentscheidung

Capability, Stufe, dauerhafte Operationsausnahme und optionaler Terminalpuffer
werden gemeinsam ausgewertet. Die Entscheidung enthält einen Grund, den
geladenen effektiven Konfigurationshash und einen Fingerprint der aktuell
ausgewerteten Freigabefelder. Anzeige, Queue und Ausführungsgrenze verwenden
diese Funktion. Fehlende Rechte werden durch keine Ausnahme ersetzt.

Vorhandene Terminalausnahmen für Kira und Eve werden erhalten und sichtbar
ausgewiesen. Der authentifizierte lokale Widerruf ist gezielt pro Principal
und Operation. Anschließende Reparatur und Wechsel full/medium/ask fügen
die Ausnahme nicht wieder hinzu. Die volle Sammelstufe bleibt dabei unabhängig
von einer Ausnahme wirksam. Die wartende Nachrichtenroute heißt vor ihrem
Start `pending_visible_terminal`; Claim und Abschluss sind eigene Belege.

Codex-Prüfung: 148 Tests für Entscheidungen, Steuerfenster, Eingabepuffer,
sichtbare Übergaben, Nachrichten, MCP und Status; weitere 74 Tests für
Installation, Kontoeinrichtung, Grok-Laufzeit, Vorprüfung, Leseweg, Reserven,
Aufgaben und Security (21 bereits in einem früheren Teilaufruf enthalten).
Die 24-fache Entscheidungsmatrix prüft die drei Stufen, mit/ohne Ausnahme,
mit/ohne Capability und mit/ohne optionalen Puffer. Ein echter HTTP-MCP-Test
vergleicht Katalog und wartenden Auftrag. Lokaler Widerruf ohne Authentifizierung
wird abgewiesen. Browserdarstellung mit simuliertem ask-Stand zeigt beide
Ausnahmen und Widerrufknöpfe ohne horizontales Scrollen; produktive Rechte
wurden dabei nicht geändert. Dies war keine CSP-Abnahme.

Weitere 91 Voice-/Team-Tests bestanden. Zwei Voice-Testfälle hatten in ihrem
gemockten Transport das tatsächlich erforderliche `session.inspect` nicht
erteilt; die Testvoraussetzung wurde ergänzt, die Rechteprüfung blieb bestehen.
Damit bestanden insgesamt 313 verschiedene gezielte Tests für dieses Paket.
Ruff und Paketbau sind erfolgreich. Die Wheel-Inhalte stimmen mit allen 70
Python-Dateien des Kandidaten überein, Quellmanifest:
`20067bbae8b439ab2beaa6460d1c9a93f9a77d68e1ac8b610435547e452b1bcf`.

Grok-Prüfung im ursprünglichen sichtbaren Fenster, Auftrag
`architecture-stage2-review-20261020`, Nachricht
`ca819675-1c37-42f7-a7e9-e8bdd7e993f6`: Grok führte selbst 113 Tests aus
und nahm die drei gezielten Anforderungen ohne Ablehnungsbefund ab.
Antwort `f1f874cd-0755-4071-a39d-00d9929d5d8e` wurde verarbeitet und quittiert.
Er weist ausdrücklich auf den erhaltenen groben Legacy-Health-Schalter hin;
die konkrete Entscheidung und ihre Ausnahme stehen daneben.
Quelländerung und Aktivierung werden getrennt erfasst.

Commit `9272240` wurde vor Aktivierung gepusht. Der aktivierte Dienst PID 67474,
Instanz `f17991c1b70042568fe9223cd1c37027`, meldet `0.8.0rc5`, Quellmanifest
wie oben, Konfiguration unverändert zu Paket 1a. Der tatsächliche ChatGPT-Zugang
bestätigt Quelle und Konfiguration als `matches_loaded`; Katalog und
Terminalanzeige geben dieselbe konkrete Freigabeentscheidung zurück.
Das neu geladene Steuerfenster zeigt die erhaltenen Ausnahmen.
ChatGPT-Auftrag `stage2-codex-read-20261020` las das ursprüngliche Codex-Fenster
erneut erfolgreich (932 Zeichen); Abschluss verarbeitet und quittiert.
Nachricht `4080db28-ea8c-426a-b99d-2fa7ce8a65d1` gelangte vom tatsächlichen
ChatGPT-Zugang ohne Sondertoken über das sichtbare Grok-Fenster bis zur
authentifizierten Antwort `a673f750-7c93-4409-97cb-e5d21c946d37`.
Einfügen, Return und Quittung sind getrennt belegt; Antwort verarbeitet und
quittiert. Die Queue zeigte jetzt korrekt `pending_visible_terminal`.
Private Nachweise: `stage2-loaded-proof.json`, `activation-stage2.json`,
`grok-stage2-review.json`. Handy-Audio und positiver Input im beschäftigten
ursprünglichen Codex sind weiterhin keine behauptete Abnahme.

## Etappe 3: Betriebsdienst und persistente Aktivierung (0.8.0rc6 aktiv)

Konfigurationsgenerierung und Core-Neustart liegen in `operations_service.py`.
Das Steuerfenster reicht authentifizierte Bedienaktionen an diesen Dienst
weiter. Ein kurzer SQLite-Vorgang reserviert `activation_runs`: draining →
activating → verifying → completed. Alle neuen Task-, Dispatch-Nachrichten-,
Team- und sichtbaren Übergabepfade sowie neue Fensterfreigaben beachten diese
Reservierung. Bereits gespeicherte Arbeit darf in draining auslaufen.
Ein vorab reservierter Teamauftrag darf ausschließlich seine versiegelte
Kernaufgabe nachreichen; Principal und Request-Hash müssen passen. Neue
Anfragen können dafür keinen laufenden Run-ID-Text als Beleg verwenden.
Prozessstopps bleiben während draining erreichbar.

Warten und launchctl laufen außerhalb schreibender Transaktionen. Vor dem
Neustart prüft auch die Transportgrenze eine eigene persistente Reservierung
und den Leerlauf. Nach dem Start werden neue Instanz, Version, Python-Quellpin,
Datei- und effektive Konfigurationsrevision geprüft. Ein erfolgreiches
launchctl allein genügt nicht. Ein veralteter Steuerfenster-Prozess darf keine
Aktivierung beginnen.

Team-Ergebnisaktionen nach einem bereits abgeschlossenen nativen Turn sind
ein dauerhafter Zwischenstand (`processing_result`). Während der Aktivierung
können sie mit identischen Aktionskennungen warten; der Providerturn wird nicht
wiederholt. Neue Teilaufträge werden erst nach Freigabe der Sperre angelegt.
Eine abgewiesene Folgeaktion darf den bereits gespeicherten Abschluss nicht
verwerfen.

Die tatsächlich geladene Konfiguration wird als private, unveränderliche Datei
unter `activation-configs/<Datei-SHA256>.toml` erhalten. Das Audit enthält
Referenzen und Metadaten, keine Konfigurationstexte. Bei Fehlschlag nach einer
Dateiaktivierung wird nur die nachgewiesene eigene Dateiänderung auf die passende
vorherige Konfiguration zurückgenommen. `failed_blocked` bleibt sichtbar und
sperrt neue Arbeit, bis der lokale Doktor eine Wiederherstellung tatsächlich
geprüft hat. Ein abgestürzter Controller hinterlässt die Sperre; ein anderer
lebender Controller wird nicht automatisch ersetzt.

Das Schema bleibt Version 2 mit additiven Tabellen. Wiederherstellung ersetzt
niemals eine Datenbank durch eine alte Sicherung. Bei abweichender Schemaversion
blockiert sie und verlangt einen eigenen Migrations-/Rückkehrplan. Die normale
Wiederherstellung nutzt den aktuellen kompatiblen Code und die passende frühere
Konfiguration; sie ist kein automatischer Quellcode-Downgrade. Freier OS-Zugriff
desselben lokalen Benutzers bleibt außerhalb dieser Bridge-Protokollgrenze.

Gezielt geprüft wurden gleichzeitige Einreichung, fertiger Drain samt
Abschlussmeldung, zwei Controller, persistente Sperre nach Neuöffnung der DB,
abgestürzter/laufender Besitzer, fehlgeschlagener und fälschlich erfolgreicher
Neustart, Schemaabweichung, gleichzeitige Dateiänderung, alle vier Absender
und ihre Rückantworten. Eine separate SQLite-Verbindung kann während des
wartenden Supervisoraufrufs schreiben. Unabhängige Grok-Abnahme und tatsächliche
Aktivierung sind nachfolgend getrennt belegt.

### Abnahmen vor Aktivierung

Der erste Gesamtlauf meldete 728 bestanden und einen alten Eve-Test ohne
`session.inspect`. Die Testvoraussetzung wurde ergänzt; die Rechteprüfung blieb
unverändert. Anschließend bestanden 729 Tests. Bei der Prüfung eines älteren
Clientwegs fand Codex zusätzlich eine echte Rückgabelücke: bestätigte Antworten
aus `session.input` wurden von Groks Rückgabehilfe weiterhin nur als Eingabe-
zustellung behandelt. Jetzt wird der zentrale completed-Beleg samt Fenster/PID,
Auftrags-/Antwort-ID und authentifiziertem Principal ausgewertet. Erst dann
kommt die vorhandene Antwort als final/addressed_agent_reply zurück.
Transport allein und bloß behauptete bool-Felder bleiben nicht-final.
Ein integrierter Test führt Queue, sichtbare Route, separates Return, Agenten-
quittung und tatsächliche Antwort bis zu diesem Rückgabefeld durch.
Audio bleibt ausdrücklich `not_observed_by_bridge`.

Grok nahm die drei Betriebsanforderungen im ursprünglichen sichtbaren Fenster
als Auftrag `architecture-stage3-review-20261020` ab und führte selbst 140 Tests
aus. Nachricht `9aa8a041-82d2-4aaa-bdb6-27d078f1bbb4`, Antwort
`e7ddf703-b9dd-42d1-986b-74b7483603fc`, verarbeitet und quittiert.
Die Rückweg-Ergänzung prüfte Grok danach separat mit 79 Tests, Auftrag
`architecture-stage3-voice-return-20261020`, Nachricht
`9f32a10c-63f0-4017-8df5-4dcbad72b101`, Antwort
`52aa1b63-950a-45db-946a-6f965b2e6e82`, ebenfalls verarbeitet und quittiert.
Beide Prüfungen melden im beauftragten Umfang keinen Ablehnungsbefund.

Eine zusätzliche konservative Besitzerprüfung verhindert `kill(pid, 0)` auf
Nicht-POSIX-Systemen. Die tatsächliche launchd-Abnahme gilt für diesen Mac;
die Betriebssupervisor-Tests simulieren keine Windows-Dienstverwaltung.
Der abschließende unveränderte Kandidat besteht mit 732 Tests in 162,58 Sekunden,
mit Unraisable-Warnings als Fehlern. Ruff und Paketbau sind erfolgreich;
alle 65 historischen unversionierten Belege sind unverändert erhalten.
Commit `1173b41` wurde vor Aktivierung gepusht. Das geprüfte Paket hat SHA256
`6b6cff52ae52c6f994e4a5a7bfb8a9867f26c25dd58b14d241c603ac707344d6`,
das geladene Manifest der 71 Python-Dateien
`d7a4401bbe56c99b2cfa8e4f2691d0cfa6451016099ff05cc99367452d6cc1a3`.

### Tatsächliche Aktivierung und verbleibende praktische Abnahme

Der alte Core ohne Aktivierungsprotokoll wurde einmalig nach überprüftem
Leerlauf ersetzt; bestehende Agenten und Tunnel blieben erhalten. Danach
führte das authentifizierte Steuerfenster den neuen koordinierten Neustart
`activation-d76210420ef046eaa92db5bf0c4448de` tatsächlich durch:
PID 77939 → 78133, neue Instanz `12654aed980a4ce18474b8eedb98e75a`,
Zustand `completed`. `activating` und `verifying` wurden gesondert beobachtet.
Während `verifying`, vor Rückkehr des HTTP-Aufrufs, konnte eine unabhängige
SQLite-Verbindung `BEGIN IMMEDIATE` und `ROLLBACK` in 0,393 ms abschließen.
Alle 16 zuvor erfassten Agenten-, Provider-, Tunnel- und App-PIDs lebten danach
weiter. Datei-Konfiguration
`642ef01516ff2ff8199980556b733ac97525329e78d22b14f50a93ed673d54cd`
und effektive Revision
`1786b287511313d7bbd518006b4afcbc26c445a929ca1a011385faa999e4089a`
blieben unverändert. Private Nachweise: `activation-stage3-bootstrap.json`,
`stage3-coordinated-restart.json`, `rc6-publish-manifest.json`.

Die zusätzliche tatsächliche Eve-Abnahme des alten `session.input`-Wegs
`stage3-eve-terminal-return-20261020` endete anschließend mit **unknown**.
Der zentrale Beleg enthält `inserting` und danach
`session_transport_unavailable`; kein `submitting`, kein Return und keine
Agentenquittung sind protokolliert. Ob Text im Eingabefeld verblieb, ist damit
nicht entschieden. Die macOS-Konsole meldet für UID 501 tatsächlich
`CGSSessionScreenIsLocked=true`; Terminal.app hat keine zugänglichen
AX-Fenster. Der Grok-Providerverlauf enthält den Prüfmarker nicht, was allein
einen ungesendeten Paste nicht ausschließt. Der Auftrag wird weder erneut
eingefügt noch durch einen zusätzlichen Return geraten. Nach Entsperren ist
zuerst dieselbe exakte Sitzung samt Eingabefeld und Belegen zu lesen.
Private Zustandsaufnahme: `rc6-eve-terminal-unknown-locked.json`.

Neue Grok-Prüfaufträge sind bis zur Zustandsklärung ebenfalls blockiert.
Ein Hintergrundreceiver ersetzt keine sichtbare Prüfung. Die physische
Handy-/Audio-Abnahme bleibt offen; lokale MCP-Antworten bestätigen keine
hörbare Rückgabe im laufenden Grok-Sprachgespräch.

### Kleines Folgepaket: konkrete Desktop-Diagnose (noch nicht aktiviert)

Ein Kandidat liest den lokalen Console-Lock-Zustand mit einem begrenzten
`ioreg`-Aufruf, ohne UI-Eingriffe. Bei eindeutig gesperrter oder inaktiver
eigener Sitzung blockiert er Terminal.app vor osascript und meldet den Grund;
unbekannte Zusatzdiagnose nimmt keine vorhandenen Berechtigungen zurück.
Andere tmux-Ziele werden davon nicht ersetzt oder pauschal gesperrt.
Die letzte Beobachtung wird mit Zeitpunkt und begrenzter Aussage im Status
geführt, der Doktor zeigt den konkreten Transportfehler.
45 gezielte Tests einschließlich vorhandener Sitzungs- und Steuerfenstertests
bestanden. Diese Quelländerung ist weder aktiviert noch von Grok geprüft.
