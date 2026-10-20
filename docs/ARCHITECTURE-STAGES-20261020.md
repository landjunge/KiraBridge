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
| 3 Aktivierung | Koordinierter Betriebsdienst aktiv; alte unklare Eve-Zustellung ohne Nachversand stillgelegt | Historischen unbekannten Ausgang erhalten |
| 4 Client-Lesewege | rc7 aktiv; 776 Tests, Grok-Abnahmen und echte ChatGPT-Leseprüfung unter Last bestanden; lokaler Eve-Rückweg bestätigt | Physische Handy-/Voice-Abnahme bleibt gesondert offen |
| 5 Modulgrenzen | 5a/5b von Grok geprüft; 5c/5d isoliert umgesetzt | Mac entsperren: sichtbare Grok-Prüfung 5c, dann 5d, vor Aktivierung |
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
bestanden. Diese Quelländerung gehört zum isolierten Kandidaten aus Etappe 4
und ist weder aktiviert noch von Grok geprüft.

## Etappe 4: gemeinsamer Leseweg und reservierte Kapazität (Quellkandidat)

`operations.py` beschreibt jede unterstützte Queue-Operation mit Capability,
Wirkung und Ausführungsklasse. Der Katalog, die gemeinsame Freigabeentscheidung,
die Vorprüfung und die Queue verwenden diese Eigenschaften. Für Terminalkatalog
und Lesen ist auf allen Wegen `session.inspect` maßgeblich; die alte zusätzliche
Capability-Abweichung zwischen direkten Werkzeugen und Queue fällt weg.

`TerminalQueries` führt `session_catalog`, `session_read`, dictionaryförmiges
`read_query` und alte `task_request`-Aufträge auf dieselben Sitzungsfunktionen.
Fehlende Rechte und geänderte PID führen zu denselben Fehlercodes. Unter
„Nur mit Erlaubnis“ wird eine direkte Leseabfrage mit `approval_required` an den
vorhandenen Aufgaben-/Freigabeweg verwiesen; sie umgeht die gewählte Stufe nicht.
Bereits tatsächlich freigegebene Queue-Aufträge prüfen ihren gespeicherten
Besitzer, Operation, Argumente und Ausführungszustand. Die produktive Stufe
„Voll erlaubt“ und die bestehenden Terminalausnahmen werden nicht verändert.

Vor der Lastprüfung festgelegte Grenze: **acht Sekunden pro Terminalabfrage**,
einschließlich nativer Leseaufrufe. Standard sind zwei reservierte Lese-Worker
und maximal 32 wartende Leseaufträge (`read_concurrency`, `max_read_queued`).
Die normalen Ausführungsplätze und der separate Stopp-Worker werden dafür nicht
verwendet. Eine direkte Abfrage bei belegten Leseplätzen erhält `terminal_read_busy`
statt einer unbegrenzten Warteschlange; ein Zeitablauf `terminal_read_timeout`.
Es gibt keine behauptete Erfolgsgarantie bei gleichzeitig unbegrenzt vielen
Leseanfragen. Abgebrochene lesende Plattformaufrufe werden begrenzt abgeräumt;
ein fehlgeschlagenes Lesen wird nicht als möglicherweise ausgeführte Eingabe
klassifiziert. Historische unklare Eingaben bleiben unverändert.

Ein echter HTTP/MCP-Test belegt beide normalen Plätze mit laufenden eigenen
Testprozessen und ruft neue sowie alte Katalog-/Lesewege auf. Alle liefern unter
dem vorher gesetzten Fixture-Budget von zwei Sekunden dieselben Ergebnisse.
Ein weiterer Test blockiert beide Leseplätze und füllt deren Queue; der
unabhängige Prozessstopp bleibt erfolgreich. Es werden keine zusätzlichen
Agentenfenster geöffnet. Timeout, PID-Abweichung, fehlende Capability sowie
alle drei Rechtestufen sind gezielt geprüft. Vor Erweiterung der vorhandenen
Vier-Absender-Negativmatrix bestanden **757 Gesamttests in 179,52 Sekunden**
mit Unraisable-Warnings als Fehlern; Ruff war erfolgreich.
Danach bestanden 116 gezielte Übergabe-, Rückgabe-, Desktop- und Kapazitätstests
in 12,41 Sekunden, einschließlich fehlender Bindung, falscher Sitzungs-PID,
falscher Agenten-PID und fehlender Bereitschaft für **jeden** der vier Absender.
Die bereits vorhandenen Rückantworttests prüfen auch Groks fehlendes bzw.
während der Antwort geschlossenes ursprüngliches Codex-Ziel. Keine Variante
darf dadurch einen anderen Adapter, ein neues Fenster oder einen neuen
CLI-Prozess starten. Das Steuerfenster erhält für die Lese-RPCs zwei Sekunden
Transportreserve über dem eigentlichen Acht-Sekunden-Budget, damit es den
konkreten Core-Timeout statt eines früheren eigenen Abbruchs anzeigen kann.

Dieser Stand wird auf `architecture/stage4-candidate-20261020` und im eigenen
Arbeitsverzeichnis `/Users/landjunge/KiraBridge-stage4-20261020` erhalten.
Der produktive Installationspfad bleibt beim aktivierten rc6-Quellstand.
Die Trennung wurde tatsächlich durchgeführt: Kandidat `4763fd5` ist gepusht
und im genannten eigenen Arbeitsverzeichnis ausgecheckt. Anschließend wurde
der produktive Pfad auf seine 71 Python-Dateien zurückgeführt und deren Manifest
erneut bytegenau mit dem geladenen rc6-Pin verglichen: passend. Es erfolgte
kein weiterer Dienstneustart. Damit lädt auch ein unerwarteter Neustart im
produktiven Pfad nicht versehentlich den ungeprüften Kandidaten.
Die Kontrolle `stage4-unactivated-runtime-check.json` bestätigt dieselbe aktive
Core-Instanz, unveränderte Konfiguration, alle 16 erhaltenen PIDs und alle 65
unveränderten historischen unversionierten Belege. Die Transportreserve bestand
danach mit 21 gezielten Tests; der Kandidat selbst wurde nach der räumlichen
Trennung nochmals ausdrücklich über sein eigenes `PYTHONPATH` geprüft:
39 Tests bestanden in 3,16 Sekunden.
### Wieder lesbares Ziel und unabhängige Grok-Abnahme

Nach Daniels Bestätigung wurde nur lesend geprüft: Fenster 22228/ttys002,
Sitzungs-PID 6957 und Grok-PID 6986 passen unverändert; das Eingabefeld ist leer.
Der Providerverlauf ist bytegleich zum gesperrten Zustand und enthält weder
Auftrags-ID noch Prüfmarker des alten Eve-Tests. Eine damalige Ausführung wird
dadurch weiterhin nicht behauptet. Der ursprüngliche Task bleibt `unknown`.
Nur seine Übergabereservierung wurde mit `interrupted` administrativ aufgegeben
und die zugehörige Nachricht als `blocked/delivery_retired_unresolved` gespeichert.
Es wurde dafür kein Input, Return oder Betriebssystemsignal gesendet und keine
Agentenquittung erzeugt. Historische Ereignisse bleiben unverändert.
Nachweise: `rc6-eve-unlocked-observation.json`, `rc6-eve-delivery-retirement.json`.

Der neue unabhängige Prüfauftrag `architecture-stage4-review-20261020`,
Nachricht `f0654b5b-de68-4d6c-8a46-88909e37dc3c`, Übergabe
`channel-6464256463fb48e2abe1c060d8dddd62`, wurde tatsächlich im ursprünglichen
sichtbaren Grok-Fenster eingefügt, mit separatem Return abgeschickt und von
Grok authentifiziert quittiert. Grok bestätigte den exakten Kandidatenpfad,
Commit und Quellpin und führte selbst die sechs beauftragten Testdateien aus:
**163 bestanden in 12,92 Sekunden**. Er empfiehlt die begrenzte Abnahme ohne
Ablehnungsbefund. Seine Antwort `51420373-ae84-470b-8cd1-7906b2f6b379` wurde
verarbeitet und quittiert; `grok-stage4-review.json` enthält den Nachweis.
Den alten Eve-Test hat Grok ausdrücklich weder empfangen noch quittiert oder
wiederholt. Handy-Audio bleibt ungeprüft.

Der erste rc7-Gesamtlauf bestand mit **769 Tests in 178,79 Sekunden**. In der
anschließenden Vertragsprüfung stellte Codex drei bisher nicht abgedeckte
Fälle nach: PID 0, negative PID und ungültige TTY ergaben beim direkten Werkzeug
`session_selection_changed`, beim alten Aufgabenweg dagegen `invalid_arguments`.
`TerminalQueries` validiert jetzt vor Rechten und Plattformzugriff mit denselben
`SessionRead`-/`EmptyInput`-Modellen wie die Queue. Die drei Negativtests liefen
vorher rot und bestehen nach der Korrektur ohne Terminalprobe oder Aufgabenanlage.

Zusätzlich behandelt die Voice-Rückgabe `blocked` und `cancelled` wie die anderen
endgültigen Fehlerzustände: ohne weiteres Warten und mit einem finalen
Fehlerbericht unter `message_processing`. Das ist ausdrücklich keine bestätigte
Agentenantwort und keine Audio-Abnahme. Der stillgelegte unklare Test meldet
seinen unbestätigten früheren Ausgang. Empfang oder ACK werden nicht erfunden.
105 gezielte Tests bestanden nach diesen Korrekturen in 13,48 Sekunden.
Die Veröffentlichung aktualisiert außerdem die Versionsangaben auf `0.8.0rc7`.
Grok prüfte die beiden Ergänzungen unabhängig als Nachricht
`b2dc766c-6957-45c6-993b-639870c3266a`, Übergabe
`channel-76bc692cdf0a410a8edb36828cbd6f73`, im ursprünglichen sichtbaren Fenster.
Er bestätigte `3d75c8e`, rc7 und Quellmanifest
`2a63dcf33b14d80c6576bc4f943fb870df0656b466d1393206ffd7968ff4aec1`
und führte selbst 25 Tests in 12,14 Sekunden aus. Empfehlung: beide Deltas
freigeben. Antwort `5647ce00-c693-4cbb-8d33-58914be46891` und die beiden
Abschlussmeldungen wurden verarbeitet und quittiert. Nachweis:
`grok-stage4-errors-review.json`.

Der erste anschließende Gesamtlauf meldete 775 bestanden und einen
Umask-abhängigen Testaufbau: `mkdir(0755)` erzeugt unter `umask 077` bereits
ein privates Verzeichnis. Der Test setzt den absichtlich unsicheren Zustand
jetzt ausdrücklich mit `chmod(0755)`; die produktive Rechteprüfung blieb
unverändert. Zehn Sicherheitstests bestanden gezielt. Der endgültige Lauf
unter restriktiver Umask besteht mit **776 Tests in 182,50 Sekunden**, wiederum
mit Unraisable-Warnings als Fehlern. Frühere Logs und Paketkandidaten bleiben
erhalten; ausgeliefert wird der Stand aus `dist-stage4-rc7-publish`.
### rc7 tatsächlich aktiviert und praktisch geprüft

Mergecommit `40aa47a` wurde vor Installation und Aktivierung gepusht.
Ein Dokumentationskonflikt wurde mit dem aktuellen Abnahmebericht aufgelöst;
vorherige Berichte bleiben in den Elterncommits erhalten. Das geprüfte Wheel
hat SHA256 `998df531f09785424ad0e98a9936f3dd0a1c41928e3dd71cc38a70aff9d01529`;
alle 74 Python-Dateien und zehn Console-Assets stimmen mit dem Quellstand überein.
Die Installation änderte ausschließlich das Projektpaket, keine übrigen Pakete.

Der authentifizierte lokale Bedienweg führte
`activation-b197a4397ac4435d8f7c51f844e8dbfa` bis `completed` durch;
`activating` und `verifying` wurden getrennt beobachtet. Neuer Core PID 92689,
Instanz `4d20022197e24d4683675b34be6918fe`, Version `0.8.0rc7`, Quellpin
`2a63dcf33b14d80c6576bc4f943fb870df0656b466d1393206ffd7968ff4aec1`.
Alle 16 erfassten Agenten-, Terminal-, Provider-, Tunnel- und App-PIDs blieben
erhalten. Die Freigabendatei SHA256 `642ef01516ff2ff8199980556b733ac97525329e78d22b14f50a93ed673d54cd`
ist unverändert. Die effektive Revision
`20b62401392a95debed96ae5ed8c6369b30b94acbf29e4d6ec085393738d8ffa`
enthält zusätzlich die neuen Standardwerte für Lesekapazität; der gesonderte
Freigaben-Fingerprint `056ba5b4c1ef0e9db2c5bd5f857e765e4273a58a2196add20710981c5a9af2d6`
bleibt gleich. Der tatsächliche ChatGPT-Zugang bestätigt Quellen und Datei als
`matches_loaded`, dauerhafte Terminalfreigabe aktiv, zusätzliches Voice-Gate aus.

Die erste Lastprobe nahm fälschlich zwei normale Plätze an; die tatsächlich
verwendete Konfiguration hat **einen** normalen und zwei Leseplätze. Die eigenen
Sleep-Aufträge wurden gezielt abgeschlossen bzw. beendet. Als sich der Mac
erneut sperrte, lieferte der reale ChatGPT-Leseauftrag korrekt `desktop_locked`
und keinen angeblichen Terminalzugriff. Diese Beobachtung bleibt separat erhalten.
Nach erneuter lesender Prüfung des wieder zugänglichen Originalfensters bestand
die neue Probe `stage4-live-r2-20261020`: Während der eine normale Platz mit
einem eigenen `/bin/sleep 30` belegt blieb, lieferte der echte zwischengespeicherte
ChatGPT-`task_request`-Weg drei bestehende Sitzungen in 3,822 s und las das
ursprüngliche Codex-Fenster in 5,300 s. Der direkte neue Leseweg funktionierte
ebenfalls (1,330 s). Der separate Stopp des eigenen Schlafprozesses war in
1,655 s abgeschlossen. Bestehende Agenten erhielten keine Eingabe oder Signale.
Alle zugehörigen Abschlussmeldungen wurden verarbeitet und quittiert.

Der neue lokale Eve-Auftrag `stage4-eve-rc7-return-20261020` lief anschließend
tatsächlich über das ursprüngliche Grok-Fenster, ein separates automatisches
Return, authentifizierte Quittung und Antwort
`aaf7310e-c755-4e2a-84b1-b1d511516281` zurück. Die Rückgabe lautet
`RC7-EVE-RUECKWEG-OK`, `final=true`, `continue_required=false`,
`scope=addressed_agent_reply`. Während der Wartezeit wurden drei nicht-finale
laufende Zustände gemeldet; der Aufrufer fragte jeweils denselben Auftrag ab.
Genau ein `submitting` und ein `return_sent` sind belegt. Antwort und Abschluss
wurden verarbeitet und quittiert. Der alte rc6-Test wurde nicht wiederholt.
Dies ist ein lokaler MCP-Test mit Eves Identität; Handy-Gerät und hörbare Ausgabe
sind weiterhin ausdrücklich **nicht** abgenommen. Daniel wurde um den praktischen
Sprachtest im laufenden Handy-Gespräch gebeten; eine Antwort liegt noch nicht vor.

Private Nachweise: `rc7-publish-manifest.json`, `activation-stage4-rc7.json`,
`stage4-live-locked-load-observation.json`, `stage4-live-chatgpt-load-proof.json`,
`rc7-eve-roundtrip.json`. Weiter geht es mit dem kleinen Paket 5a für fachliche
Status-/Protokollabfragen; eine neue Nutzerfreigabe ist dafür nicht nötig.

## Etappe 5, Paket 5a: fachliche Status- und Protokollabfragen (Kandidat)

Der Kandidat liegt isoliert unter `/Users/landjunge/KiraBridge-stage5a-20261020`.
Produktiv bleibt der geprüfte rc7-Stand. `OperatorQueries` fasst die lokalen
Bedienabfragen zusammen, ohne eigene SQL-Abfragen oder ein gesamtes Bridge-Objekt.
Aufgabenabfragen gehören `task_manager.Store`, Nachrichtenabfragen dem
`MessageManager`, Team-Zähler dem `TeamManager` und Audit-Seiten `AuditReader`.
Es werden weder neue Netzwerkdienste noch zusätzliche Datenbanken eingeführt.

`ControlCenter.busy`, wartende Aufgaben, Verbindungsbelege und Protokollseiten
verwenden diese fachlichen Abfragen. In diesen Wegen kennt die Oberfläche keine
Fremdtabellen mehr. Ihre eigene Aktionsablage und weitere Bedien-/Betriebslogik
bleiben ausdrücklich Arbeit für Paket 5b; die Sitzungsports und Plattformadapter
folgen anschließend. Die gemeinsame Transaktion für Aufgabenwechsel, Audit und
Abschlussnachricht wurde nicht verändert.

Die Protokollprüfung verbessert auch zwei konkrete Zeitbezüge: Eine später
angelegte Aufgabe wird keinem früheren Audit-Ereignis zugeordnet; spätere
Zustellung und Quittung einer Nachricht erscheinen nicht schon im früheren
Queue-Eintrag. Der Nachrichtentext bleibt unverändert verfügbar. Bestehende
Audit-Ketten und historische Inhalte werden nicht umgeschrieben.

86 gezielte Tests bestanden in 52,95 Sekunden: austauschbare fachliche Abfragen
ohne Core-Aufbau, Authentifizierung vor Datenzugriff, historische Zustände,
mutationsfreie Abfragen, bestehende HTTP-Oberfläche, Aufgaben-, Nachrichten-,
Abschluss- und Aktivierungsregressionen. Ruff und Whitespace-Prüfung bestanden.
Grok prüfte Paket 5a tatsächlich im bestehenden sichtbaren Fenster: Auftrag
`architecture-stage5a-review-20261020`, Nachricht
`e5a6f490-4e12-428e-8e7c-40ba7cf2e11c`, Übergabe
`channel-bea40cc46dd14e6ca33b7297a86ce00f`. Er bestätigte Commit `d7934e3`,
75 Python-Dateien und Quellpin
`474f4965bff87ee90d9516c9861f1dee46860fe574978ae44c5746e83dc51f0e`.
Sein eigener Lauf derselben sechs Testdateien bestand mit **86 Tests in 54,16 s**;
er empfiehlt die begrenzte Abnahme. Antwort
`f9f5af35-580a-480b-a235-aea72129fb1b` wurde verarbeitet und quittiert;
`grok-stage5a-review.json` enthält den Nachweis. Produktiv blieb rc7 unverändert.

Die anschließende Feldprüfung fand noch einen verbliebenen Zukunftsbezug:
`finished` war trotz historischem laufendem Zustand schon aus der späteren
Aufgabenzeile vorhanden. Zwei Tests für späteren Erfolg und Fehler liefen
zunächst rot. Eine zusätzliche Zuweisung blendet den späteren Abschlusszeitpunkt
jetzt ebenso aus wie spätere Ergebnisse und Fehler. 56 gezielte Tests bestanden
nach dieser Korrektur in 32,87 s. Grok bestätigte `6c05938` und den Quellpin
`f579255e6ff1299bfbfd3328fa775cdcfc81fcdda6b3ddf4c153463e17f16aea`
mit **22 eigenen Tests in 0,80 s** und empfiehlt die Abnahme der Korrektur.
Auftrag `24be2cf1-4370-40f2-bb20-162428290131`, sichtbare Übergabe
`channel-e5adec61b72d42b7b1d89dbf73e11d2b`, Antwort
`7c63af5d-ed5a-419d-9d8f-3a3c6f61f0da`; Antwort und Abschluss quittiert.
Beleg: `grok-stage5a-finish-review.json`. Die Aktivierung der gesamten Etappe 5
steht noch aus.

## Etappe 5, Paket 5b: Bedienwege hinter Anwendungsschnittstellen (Kandidat)

Isolierter Arbeitsstand: `/Users/landjunge/KiraBridge-stage5b-20261020`.
Die vier HTTP-Präsentationen (`ControlCenter`, `ApprovalConsole`, Team- und
Grok-Verbindungsansicht) erhalten schmale Anwendungspartner statt des gesamten
Bridge-Objekts. Sie authentifizieren, prüfen HTTP-Eingaben und stellen Ergebnisse
dar. Keine dieser Oberflächen kennt SQL-Tabellen oder startet Betriebssystemprozesse.
Nur `operator_application` als zentrale Verdrahtung kennt den vollständigen Kern.

`OperatorControl` führt Bedienaktionen und Zustandsabfragen über benannte Ports
aus. `LocalDaemonClient` kapselt den bestehenden authentifizierten MCP-Zugang;
`LocalProcessPlatform` die begrenzten Prozessaufrufe und Beobachtung. Die
Konfigurationsaktivierung verbleibt beim bereits geprüften `OperationsService`.
`ConnectorAdministration` ist gemeinsamer Besitzer der OAuth-Bedienabfragen;
`OperatorTaskDecisions` nutzt die vorhandene atomare Aufgabenfreigabe und Ablehnung.
SQL für Aufgabenansichten liegt beim Task-Store, eigenständige Konsolenereignisse
bei `AuditWriter`. Gemeinsam zu speichernde Fachänderungen behalten ihre Transaktion.

`ControlActionRepository` besitzt die unveränderte `control_actions`-Tabelle.
Kennungsprüfung, Reservierung und Audit passieren in einer kurzen Transaktion,
auch über getrennte SQLite-Verbindungen. Ausführung wartet außerhalb. Wiederholte
Kennungen lösen keine zweite Aktion aus; andere Inhalte erzeugen einen Konflikt.
Eine abgebrochene wartende Ausführung wird als `unknown` gespeichert und nicht
wiederholt. Ein Prozessabbruch vor dem Abschluss lässt die vorhandene Reservierung
erhalten. Ein bestätigter Bridge-Neustart wird als `completed` gespeichert; bloßes
`launchctl` ohne den vorhandenen Aktivierungsnachweis genügt dafür nicht.

Vorhandene Agentensitzungen bleiben erhalten. Der ausdrücklich vom lokalen Nutzer
gewählte Start verwendet weiterhin die einmalige vertrauenswürdige Fensterfreigabe.
Ein Neustart bei fehlendem Agentenfenster erzeugt keine Ersatzfreigabe und keinen
Ersatzprozess. Diese interne Abgrenzung ist keine Sandbox gegen freie OS-Rechte
desselben Mac-Benutzers. Sitzungsmanager und Terminaladapter folgen in Paket 5c.

155 gezielte Tests in 26,76 s bestanden nach Anpassung zweier Testinjektionen an
die neuen fachlichen Besitzer. Enthalten sind echte getrennte SQLite-Verbindungen,
einmalige Aktionsausführung, unklare Unterbrechungen, Konflikte, lokale Authentifizierung,
Freigaben, OAuth/PKCE, Team-, Protokoll- und Aktivierungsregressionen. Zusätzlicher
Negativtest für den fehlenden Agenten-Neustart bestand anschließend mit insgesamt
20 gezielten Tests in 0,92 s. Grok prüfte Commit `7713646` (80 Python-Dateien,
Quellpin `9ddade1ccaf9014a1f0acf3cca583127752ceb91d1fabdadfa62db8222ea6547`)
und führte **156 Tests in 27,37 s** selbst aus. Seine begrenzte Abnahme kam als
Antwort `d8f30b1c-c594-4a2d-a891-43b938b6a58f` auf Auftrag
`3dfe83bb-93ca-4adc-81b2-3419054bfe5b`, sichtbare Übergabe
`channel-0c6b564f76ff4ae5abe363daabe761b0`. Antwort und Abschluss sind quittiert;
Beleg `grok-stage5b-review.json`.
Keine produktive Codeaktivierung, keine neuen echten Agentenfenster oder Eingaben
in bestehende Codex-Sitzungen gehören zu diesen Tests.

## Etappe 5, Paket 5c: schmale Sitzungsports und ersetzbare Transporte (Kandidat)

Arbeitsstand: `/Users/landjunge/KiraBridge-stage5c-20261020`; produktiv weiterhin rc7.
`SessionManager` erhält `SessionPorts` mit Autorisierung, Eingabefreigabe,
Audit, konfigurierter Umgebung und Agentenzuordnung. Die zentrale Bridge verdrahtet
ihn erst nach Eingabepolicy und Clipboard-Partner. Der Sitzungsmanager kennt kein
Bridge-Objekt, keine SQL-Tabelle und keine Prozessstart- oder AppleScript-API.
`TerminalAppTransport` und `TmuxTransport` implementieren explizite Transportports.
Beide lassen sich ohne Aufbau des Kerns vollständig ersetzen.

Terminal.app behält Katalog, exakte Fenster-/TTY-Auswahl, Fokusprüfung, wörtlichen
Paste-Menübefehl, Erhalt aller Clipboard-Formate und separates Return. Vor jeder
Mutation erfolgt weiterhin die neue Sitzungsauswahl mit PID-Prüfung und persistierter
Agentenbindung. Native Zielskripte prüfen zusätzlich, dass Terminal.app noch läuft,
bevor sie Fenster abfragen. Die eigene kurzlebige Prozessbeobachtung wird auch bei
Abbruch beendet. tmux besitzt nur die bisherigen bestehenden Lese-/Eingabewege;
kein Adapter startet einen Ersatzagenten, ein Fenster oder einen tmux-Server.
Der einzige Fensterstart bleibt der gesondert freigegebene lokale Startauftrag.

Tests ersetzen beide Transporte ohne Bridge und prüfen Kira, Eve, Codex und Grok
gegen fehlende, falsche, doppelte und veraltete Ziele. Keine dieser Prüfungen erreicht
Paste, Return, Fensterstart oder Eingabe über einen anderen Adapter. Direkte Eingaben
in erkannte CLI-Agenten benötigen weiterhin die zentrale Übergabe. Mehrzeiliger Paste
und Return bleiben getrennte Aktionen; ein unklarer Return hat genau einen Versuch
und löst keinen Ersatz aus. Transportflags bestätigen keinen Agentenempfang.

214 gezielte Tests in 14,38 s bestanden, Ruff und JavaScript-Syntax ebenfalls.
Vorherige Testinjektionen wurden an die tatsächlichen neuen Adapter verlegt.
Zusätzlich las der isolierte Kandidat tatsächlich die beiden Originalfenster
`terminal:22104:ttys000`/PID 94023 (1001 Zeichen) und
`terminal:22228:ttys002`/PID 6957 (1103 Zeichen), Katalog mit drei erhaltenen Fenstern.
Diese rein lesende lokale Prüfung verwendet die tatsächlich gespeicherten
Capability-Einstellungen, aber keinen gestarteten Kandidaten-Daemon und keine
produktive Datenbankschreibaktion. Beleg `stage5c-candidate-native-read.json`.
Sie ersetzt weder die spätere Prüfung nach Aktivierung noch eine Eingabe in das
beschäftigte Original-Codex-Fenster oder die physische Handy-Sprachausgabe.

Die Terminalauswahl nennt OS-`busy` jetzt „Programm läuft“ beziehungsweise
„Terminal wartet“; tmux ohne diese Beobachtung zeigt „Prozess erkannt“.
Agentenbereitschaft wird erst vor der tatsächlichen Übergabe geprüft.
Groks unabhängige Prüfung dieses Pakets steht noch aus: Nach dem Push von
`579ab65` (83 Python-Dateien, Quellpin
`f7048b777cf874ffa026efc6b60af65c119053a96522557eefa6b94a90b00f9e`)
meldete der tatsächliche Terminalzugang `desktop_locked`. Deshalb wurde kein
neuer Grok-Auftrag gesendet. Es gibt weder einen Hintergrundersatz noch einen
erneuten Return in ein unbekanntes Feld. 5c bleibt unverändert für die Prüfung;
die Entsperrung der bestehenden Mac-Benutzersitzung wurde angefragt.

## Etappe 5, Paket 5d: fachliche Betriebsabfragen (isolierter Kandidat)

Während der blockierten sichtbaren 5c-Prüfung liegt diese unabhängige Restarbeit
separat unter `/Users/landjunge/KiraBridge-stage5d-20261020`. Sie verändert keine
Datei im festgehaltenen 5c-Prüfbaum. Es handelt sich um einen weiteren Teil der
Etappe 5, keine Abnahme oder Aktivierung von 5c und keinen Beginn von Etappe 6.

`OperationsService` kennt keine SQL-Tabellen oder Zustandslisten von Aufgaben,
Nachrichten, Teams und sichtbaren Übergaben mehr. Die jeweiligen Besitzer liefern
`activation_work_count`; `OperatorQueries.maintenance_counts` verbindet die Werte.
Der Betriebsdienst übergibt seinen tatsächlichen Store als Transaktionskontext.
So bleiben auch Abfragen innerhalb einer gemeinsamen Schreibtransaktion konsistent,
wenn ein zweiter Steuerprozess eine eigene SQLite-Verbindung verwendet.
Warten und Prozess-/Netzwerkaufrufe bleiben außerhalb der Schreibtransaktion.

Dabei wurde eine konkrete Lücke berichtigt: Die frühere Warteprüfung zählte einen
Teamauftrag in `processing_result` nicht. In derselben temporären Datenbank liefert
die tatsächliche rc7-Funktion dafür **0**, die neue Besitzerabfrage **1**.
Beleg `stage5d-processing-result-before-after.json`; keine produktive Datenbank-
oder Agentenänderung. Auch die Wiederherstellung erkennt diesen aktiven Zustand.
Die Ergebnisse selbst, ihre Belege und Abschlussmeldungen bleiben beim bisherigen
atomaren fachlichen Speicherweg.

100 gezielte Tests in 52,91 s bestanden: Besitzerabfragen, gemeinsam sichtbare
noch nicht bestätigte Änderungen auf einer zweiten Verbindung, Abwarten laufender
Ergebnisverarbeitung, blockierter Neustart bei unerledigter Arbeit, erhaltene
Konfiguration, Aufgaben-/Nachrichten-/Teamabschlüsse und vorhandene UI-/Betriebswege.
Die Gesamtsuite des vorbereiteten `0.8.0rc8`-Kandidaten bestand mit
**817 Tests in 171,05 s**, einschließlich als Fehler behandelter
`PytestUnraisableExceptionWarning`. Ruff, Whitespace-Prüfung, Wheel-Bau und
`uv lock --check --offline` bestanden. Die 83 Python-Dateien und zehn
Oberflächenassets im Wheel wurden bytegenau mit dem Quellbaum verglichen.
Quellpin: `7fcb86e8f19cb7c2c6b83b91dd844d0c82ff1afdfc29fcf0edf1ee535789c847`;
Wheel-SHA256: `16c34efab00a9477117c6dc21b093364337a291797db5e08b49eed3631161f57`.
Private Belege: `stage5-rc8-full-tests.log`, `stage5-rc8-candidate-manifest.json`.
Die unabhängige sichtbare Grok-Prüfung erfolgt erst nach 5c und nach Entsperrung.
Produktiver Stand bleibt unverändert `0.8.0rc7`; keine Freigaben oder Alt-Puffer
werden automatisch verändert.

### Fortsetzung nach Entsperrung

Zuerst die bestehende Grok-Zuordnung neu lesen und 5c gegen den unveränderten
Pin `579ab65` unabhängig prüfen lassen; erst danach 5d gegen dessen dokumentierten
Pin. Keine dieser beiden Prüfungen wurde während `desktop_locked` eingereiht.
Bei Befunden korrigieren und gezielt nachprüfen. Anschließend erst den geprüften
Stand in den produktiven Zweig übernehmen, vor Aktivierung pushen, Paketmetadaten
aktualisieren und Core/Steuerdienst koordiniert aktivieren. Sitzungskatalog,
ursprüngliches Codex-Lesen und eine neue sichtbare Grok-Übergabe praktisch prüfen.
Bestehende Fenster und Tunnel bleiben dabei erhalten. Danach folgt Etappe 6.
Die hörbare Handy-Antwort im laufenden Grok-Gespräch bleibt zusätzlich offen;
der bereits belegte lokale Eve-MCP-Rückweg ersetzt diese Abnahme nicht.

Der vorbereitete 5d-/rc8-Kandidat ist als `aab0bf7` auf dem Zweig
`architecture/stage5d-owned-drain-20261020` gepusht. Die Produktivquelle wurde
nicht durch diesen ungeprüften Kandidaten ersetzt.


## Zusätzliche aktuelle Kira-Funktionsprüfung

Daniels Auftrag „check die kira verbindung und funktion“ wurde über die tatsächlich
vorhandenen ChatGPT-Werkzeuge geprüft; die Bridge authentifizierte `chatgpt`/Kira.
Produktiv antwortet rc7, PID 92689. Quelle und Konfiguration melden `matches_loaded`.
Die dauerhafte Terminalfreigabe ist automatisch; Voice-Sondertoken und Zusatzpuffer
sind aus. `session_input_policy.enabled=false` ist keine Terminalsperre.

Testkennung `kira-check-1792480431762`: Über den zwischengespeicherten
`task_request`-Zugang wurden der Katalog mit drei erhaltenen Fenstern und die
Ausgaben der Originalfenster Codex `22104/ttys000/94023/94386` (945 Zeichen)
und Grok `22228/ttys002/6957/6986` (1103 Zeichen) tatsächlich gelesen.
Aufgaben und Abschlussmeldungen wurden verarbeitet und quittiert.

Kira schickte anschließend ohne Sondertoken eine neue harmlose Frage an Grok,
Nachricht `f8b7a5b2-f924-4110-ace4-cd9ec89953e2`. Die verbindliche sichtbare Route
verwendete das bestehende Grok-Fenster. Übergabe
`channel-141fa2568b274f4689d17a7302fd04ab`: `inserting`, `inserted`,
`submitting`, `return_sent`, `sent`, authentifiziert `confirmed`, `completed`.
Genau ein Return-Versuch ist belegt. Grok quittierte die Nachricht und antwortete
an `chatgpt` exakt **KIRA-VERBINDUNG-OK**, Antwort
`03514836-0763-445c-8ba0-3e99208dcede`. Kiras wirklicher MCP-Empfang und ACK
sowie die Abschlussquittierung sind belegt. Das ursprüngliche beschäftigte
Codex-Fenster bekam keine Eingabe; kein Fenster oder Agent wurde neu gestartet.

`message_receiver_active=true` bezeichnet den zentralen CLI-Dispatcher;
`receiver_configured=false` für Kira bezeichnet ihr extern gelesenes Clientpostfach.
Es fehlt deshalb kein eigener Kira-Hintergrundagent. `existing_session_attached=false`
bezeichnet fehlende dauerhafte Agenten-Protokollanbindung; der praktisch geprüfte
Fensterzugriff erfolgt pro Aktion über die exakte aktuelle Zuordnung.
Der Test belegt keine hörbare Ausgabe auf einem Handy und kein automatisches
Aufwecken eines inaktiven Chats. Private Nachweise: `kira-check-1792480431762.json`
und `kira-check-1792480431762-handoff.json`. Keine Konfigurationsreparatur war nötig.

Der Mac ist bei dieser Prüfung wieder tatsächlich zugänglich. Der zuvor nicht
abgesendete 5c-Prüfauftrag wurde danach als Codex über dieselbe zentrale sichtbare
Grok-Route eingereiht: `7f397465-25be-4400-a37d-f8be5189d669`.


## Etappe 5: unabhängige Schlussprüfungen nach Entsperrung

Grok prüfte 5c im bestehenden sichtbaren Fenster gegen `579ab65` und den
83-Dateien-Quellpin `f7048b777cf874ffa026efc6b60af65c119053a96522557eefa6b94a90b00f9e`.
Er führte selbst **214 Tests in 17,16 s** aus und empfiehlt die begrenzte Abnahme.
Antwort `f2e80c21-b2f1-4712-9c02-528f492bf6f1`, Übergabe
`channel-7da0f7482af74b3ea25080eb6c187c52`; Antwort und Abschluss quittiert.

Danach prüfte er 5d gegen `aab0bf7`/rc8 und Quellpin
`7fcb86e8f19cb7c2c6b83b91dd844d0c82ff1afdfc29fcf0edf1ee535789c847`.
**100 eigene Tests in 53,90 s**, begrenzte Abnahme ohne neue Befunde.
Antwort `1e19ed6a-d7cc-48fb-b606-f4eb0075be1e`, Übergabe
`channel-82fa917839cb44d49d853ee8ead2a154`; Antwort und Abschluss quittiert.
Belege `grok-stage5c-review.json` und `grok-stage5d-review.json`.
Die Aktivierung dieses geprüften Standes folgt erst nach dem Push.
