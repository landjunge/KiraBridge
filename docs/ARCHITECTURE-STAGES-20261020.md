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
| 5 Modulgrenzen | rc8 aktiv; 817 Tests und echte Grok-Abnahmen aller Pakete | Tatsächlicher Kira-Rückweg nach Aktivierung bestätigt |
| 6 Ausgabeablage | rc9 aktiv; 829 Gesamttests, 105 eigene Grok-Tests und tatsächliche Kira-/lokale Eve-Rückwege bestätigt | Öffentlicher Grok-Tunnel ausgefallen; physische Handy-/Audio-Abnahme weiterhin offen |

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


## Etappe 5: tatsächliche Aktivierung und Kira-Nachprüfung

Der geprüfte Quellstand wurde als Merge `1de508d` vor Aktivierung gepusht.
Das bereits bytegenau geprüfte Wheel wurde mit `uv pip install --no-deps`
installiert; nur KiraBridge wechselte von rc7 auf rc8. Die anderen installierten
Pakete blieben erhalten. Der produktive Importpfad ist jetzt das als Wheel installierte, vom Arbeitsbaum getrennte Paket unter `.venv/lib/python3.11/site-packages/kirabridge`.
Weitere Repository-Bearbeitung aktiviert damit keinen neuen Produktivcode.

Koordinierte Aktivierung `activation-d8b8925848184cad9b8890777d6c188f`,
Core-PID **15071**, Instanz `048accc501dc4048a007d57f5cc837bf`, Version **0.8.0rc8**.
Die Phasen `activating` und `verifying` wurden unabhängig beobachtet; der
Aktivierungsdatensatz und die Bedienaktion stehen auf `completed`.
Vorher wurden tatsächliche Konfiguration und SQLite-Datenbank konsistent privat
zusätzlich gesichert. Alle 16 beobachteten App-, Agenten-, TTY- und Tunnel-PIDs
blieben erhalten. Nur Core und Steuerdienst wurden gezielt neu geladen.
Beleg: `activation-stage5-rc8.json`. Die einmalige lokale Aktivierungsreservierung
verhindert blindes erneutes Ausführen des Installationsskripts.

Quelle: 83 Dateien, SHA256
`7fcb86e8f19cb7c2c6b83b91dd844d0c82ff1afdfc29fcf0edf1ee535789c847`.
Die tatsächliche Konfiguration blieb bytegleich bei
`642ef01516ff2ff8199980556b733ac97525329e78d22b14f50a93ed673d54cd`;
der wirksame Stand bei
`20b62401392a95debed96ae5ed8c6369b30b94acbf29e4d6ec085393738d8ffa`.
Kiras dauerhafte Ausnahme und alle normalen Freigaben blieben aktiv,
Voice-Sondertoken und Zusatzpuffer aus. Kiras tatsächliches `policy_inspect`
meldet Quelle und Konfiguration als `matches_loaded`.

Neue Kira-Nachprüfung `kira-rc8-check-1792481458793`: drei erhaltene Fenster
aufgelistet; das Original-Codex-Fenster über Kiras echte zwischengespeicherte
Werkzeugbindung gelesen (955 Zeichen). Eine neue harmlose Frage
`b6b7357f-f652-42f4-8115-64d9f37b642f` wurde über das bestehende Grok-Fenster
übergeben. Übergabe `channel-4fee424677b043b18c485eb7e21e2597` abgeschlossen,
authentifizierte Grok-Bestätigung und Antwort **RC8-KIRA-OK** zurück an Kira,
Antwort-ID `0fe9ec28-dce7-4e5b-9f9c-6f17182db04b`. Antwort und beide
Aufgaben-/Nachrichten-Abschlussmeldungen wurden verarbeitet und quittiert.
Keine Eingabe in den beschäftigten ursprünglichen Codex, kein Ersatzfenster,
keine Wiederholung eines alten Tests. Beleg `kira-rc8-check-1792481458793.json`.
Die hörbare physische Handy-/Sprachausgabe bleibt eine eigene offene Abnahme.


## Etappe 6: begrenzte Ausgabeablage (rc9-Kandidat, noch nicht aktiviert)

`OutputHistory` besitzt die additive Tabelle `output_snapshots` in derselben
SQLite-Datenbank. Das Schema bleibt Version 2; bestehende Tabellen, alte
Ergebnisse und historische Audit-Einträge werden nicht umgeschrieben. Neue
Terminalmitschnitte und rohe stdout/stderr-Ausgaben erhalten dort begrenzte
UTF-8-JSON-Snapshots. Die Standardgrenzen sind 16 MiB Gesamt-Nutzlast,
256 Einträge, 8 MiB je Eintrag und sieben Tage. Bei Begrenzung bleibt vom
Sitzungsmitschnitt das Ende erhalten; stdout/stderr werden vorn begrenzt.
Trunkierung und ursprüngliche Bytezahl werden ausgewiesen. Die Grenzen betreffen
diese neuen Nutzlasten, nicht Datenbankdatei/WAL, alte Audit-Inhalte oder fachliche
Antworten. Adressierte Nachrichten und strukturierte Agentenantworten bleiben
als fachliche Ergebnisbelege erhalten.

Neue dauerhafte Audit-Einträge enthalten Referenz, SHA256 und Ereignismetadaten,
keinen zusätzlichen rohen Terminaltext. Der Hash bezeichnet gespeicherte Bytes,
keinen Autor, Prozess oder erfolgreichen Auftrag. Lesen benötigt weiterhin die
bestehende Session-/Task-Berechtigung und Eigentümerprüfung; es gibt keinen
öffentlichen beliebigen Referenzabruf. Katalog/Lesen über neue und alte Clientwege
liefern dieselben Resultate, auch bei abgeschnittener Ausgabe. Das lokale
Protokoll löst Referenzen auf. Ablauf oder Verdrängung wird ausdrücklich gezeigt,
der Auftrag bleibt abgeschlossen und wird nicht erneut ausgeführt. Der
Grok-Formatter beendet auch diesen Fall mit einer verständlichen Antwort.

Referenz, Taskzustand, Ereignis, Audit und Abschlussmeldung werden weiterhin in
derselben Transaktion geschrieben. Ein gezielter Fehler bei der Abschlussmeldung
rollt auch den neuen Snapshot zurück. Die Abschlussmeldung dupliziert keine
rohe stdout-Vorschau. Historische Klartextergebnisse bleiben lesbar.

### Rückkehrplan für das additive Datenformat

Die normale Betriebs-Reparatur stellt passende vorherige Konfiguration mit
aktuell kompatiblem Code wieder her; sie ist kein automatischer Code-Downgrade.
Ein expliziter Wechsel auf rc8 benötigt angehaltene neue Arbeit, vollständig
abgeschlossene aktive Arbeit, die passende alte Konfiguration ohne den neuen
`output_history`-Abschnitt und einen Codec-kompatiblen Leser oder einen zuvor
geprüften Export. Der ausschließlich interne lokale Helfer
`outputs.prepare_legacy_results()` verlangt eine persistente Wartungsreservierung
und kann neue Taskreferenzen innerhalb einer begrenzten atomaren Transaktion in
alte lesbare Taskresultate auflösen. Zu großer Gesamtexport wird vollständig
abgewiesen. Kein Zustand, Event, Empfangsbeleg oder historisches Audit wird
umgeschrieben; keine Datenbanksicherung wird zurückgespielt und keine Eingabe
wiederholt. Bereits abgelaufene Ausgaben lassen sich dadurch nicht zurückholen.
Rc8 kann die neuen Audit-Referenzen ohne kompatiblen Leser nicht auflösen;
die additive Tabelle und die Referenzen müssen daher erhalten bleiben. Dieser
Helfer ersetzt weder das kontrollierte Leerlaufen noch die tatsächliche
Versions-/Konfigurationsprüfung des anschließend gestarteten Dienstes.

### Gezielte Prüfungen vor unabhängiger Abnahme

829 Tests bestanden in 194,64 Sekunden, einschließlich Fehler-Rollback,
Zugriffsgrenzen, Hash-Abgleich, Byte-/Anzahlgrenzen, UTF-8, Ablauf ohne
Fristverlängerung, unveränderter historischer Audit-Kette, Rückkehr-Vorbereitung,
Grok-Antwort bei fehlender Ausgabe und exakter Gleichheit direkter/alter
Queue-Lesewege unter Last. Ruff, JavaScript-Syntax und Diffprüfung bestanden.
Ein früherer Gesamtlauf fand eine echte DTO-Abweichung der zwei Lesewege;
diese wurde korrigiert und mit einer zusätzlichen Trunkierungsprüfung belegt.
Die Lasttest-Fixture ersetzt nur das Plattformlesen und durchläuft weiterhin
die tatsächliche neue Beobachtungs-/Speicherfunktion. Die realen Lastzeitbudgets
und Gleichheitsprüfungen bleiben bestehen. Frühere fehlgeschlagene Prüflogs
bleiben als historische Belege erhalten. Die unabhängige Grok-Prüfung folgt
gegen den eingefrorenen, gepushten Kandidaten, vor Installation und Aktivierung.

### Tatsächliche unabhängige Grok-Abnahme von Etappe 6

Grok bestätigte den Auftrag im ursprünglichen Fenster und prüfte exakt Commit
6821268aa1d6260735054c4b43d59a8c8ce76eb2, 84 Python-Dateien, SHA256
709c188dd357512f1e86fb3776da6414a4e30fe9d65d740a3fecf352e027828b.
Er führte selbst **105 Tests in 58,61 Sekunden** aus und empfiehlt eine
begrenzte Abnahme. Die im Auftrag irrtümlich genannte Datei
tests/test_grok_connector.py existiert nicht; Grok verwendete korrekt
tests/test_grok_conversation.py. Er bestätigt Zugriffsprüfung, Grenzen,
gemeinsamen Fehler-Rollback, Ablauf ohne Replay und den begrenzten Rückkehrplan.
Keine Codeänderung oder Eingabe in Codex, kein neues Fenster; Handy-Audio nicht
geprüft. Antwort c2d81e8f-9d6d-4d18-af10-962942c10e93, Übergabe
channel-41a3b38f14c04c3aa6bc2be38e8c795a; Beleg grok-stage6-review.json.
Aktivierung folgt erst nach Push; das geprüfte Wheel enthält 84 Python-Dateien
und zehn Console-Assets bytegleich zum Kandidaten.

Eine zusätzliche Außenprüfung fand bereits vor rc9-Aktivierung:
Grok-Connector lokal HTTP200/healthy, gespeicherte öffentliche Quick-Tunnel-
Adresse dagegen lokal nicht auflösbar und auch über Cloudflare DNS-over-HTTPS
Status3/NXDOMAIN. Das ist kein Beweis eines funktionierenden Handy-Zugangs.
Der existierende Connector meldet seine noch laufende ältere Gateway-Version
0.5.2; der Kern ist davon getrennt rc8. Die alten Gateway-/Tunnelprozesse wurden
erhalten und nicht ersetzt. Kiras tatsächlicher MCP-Rundlauf ist separat belegt.

## Etappe 6: tatsächliche Aktivierung und praktische Nachprüfung

Merge a4c4e2f wurde vor Installation und Aktivierung gepusht. Nur KiraBridge
wechselte per geprüftem Wheel und --no-deps von rc8 auf rc9. Wheel-SHA256:
20dbcb52938adea23d53dae80a5d2b2b2b9c44a906d11af02303b0cd849a934d.
Koordinierte Aktivierung activation-beb2e86fb1a84e989dd975dd617ee888 ist
completed. Core-PID 22811, Instanz 2fbe03a17028419ea4ddb2d3386d55e3;
Quelle 709c188dd357512f1e86fb3776da6414a4e30fe9d65d740a3fecf352e027828b,
84 Python-Dateien. Vorherige Konfiguration und SQLite wurden konsistent privat
gesichert; alle 16 beobachteten bestehenden App-/Agenten-/TTY-/Tunnel-PIDs
blieben erhalten. Nur Core und Steuerdienst wurden neu geladen.
Beleg activation-stage6-rc9.json.

Der neue output_history-Abschnitt steht in der tatsächlich verwendeten Datei
~/.config/kirabridge/config.toml. Datei-SHA256:
cd80c04c54e27e57bc4249261a3a2ce9f9ba9300e83fcf301b6d4eff253245c3,
effektiver SHA256:
ba72132a31dd21f44891b75a631d2f8b2495c6c82b4fba2a544f32212b21703d.
Die reale Kira-Bindung meldet Quelle und Konfiguration als matches_loaded.
Vollfreigabe/dauerhafte Terminalausnahme blieben erhalten, der zusätzliche
Voice-Sondermarker und optionale Terminalpuffer aus. Bereits laufende Gateway-
und Proxyprozesse laden ihre Konfiguration beim Start; ihre bestehenden
Prozesse wurden durch den additiven Abschnitt nicht neu gestartet.

Kiras echter alter task_request-Client listete alle drei erhaltenen Fenster auf
und las 900 Zeichen aus Original-Codex 22104/ttys000/94023/94386. Die rohe Ausgabe
steht nur im begrenzten Snapshot, Taskresultat und Audit enthalten eine Referenz.
Frage 8af53691-72d3-421d-908e-82ad0292b1bc ging an Original-Grok
22228/ttys002/6957/6986. Einfügen, genau ein submitting/return_sent, sent,
authentifizierte Bestätigung und completed sind separat belegt:
channel-d8264bef68744ca7bb1502fdc5f752fc. Antwort RC9-KIRA-OK,
54060220-05fe-471f-92ec-7897d21f9f1c, kam tatsächlich an Kira zurück und wurde
verarbeitet/quittiert; alle drei Abschlussmeldungen ebenfalls. Belege
kira-rc9-check-1792484149339.json und rc9-kira-handoff-steps.json.
Keine Eingabe in den beschäftigten Original-Codex und kein Ersatzfenster.

Ein lokaler authentifizierter grok_app-Aufruf übergab an dasselbe Grok-Fenster
und erhielt RC9-EVE-OK als finales conversation_return mit
continue_required=false. Nachricht 9e920ffe-b38c-4cc2-8369-a1a4c5f0d2fa,
Antwort 78a71c64-f772-4876-8bbb-1a8270e9f533; nach zwei zulässigen Lese-
Fortsetzungen derselben Nachricht. Keine wiederholte Eingabe; Antwort und
Abschlussmeldungen quittiert. audio_playback bleibt not_observed_by_bridge.
Beleg rc9-eve-local-roundtrip.json, kein Nachweis physischer Handynutzung.

Die authentifizierte lokale Protokoll-API liefert neue referenzierte Ausgaben
weiter als Text. Headless-Chrome zeigte Bridge läuft und die dauerhafte
Terminalausnahme, keine JavaScriptfehler; Hauptfenster 1365x768 und mobile
Darstellung 393x852 passen jeweils in die geprüfte Ansicht, das separate
Protokoll zeigt RC9-EVE-OK. Belege rc9-local-operator-protocol-check.json und
rc9-operator-browser-check.json. Dies ist ein lokaler Renderingtest.

Alle 13.375 vor Aktivierung vorhandenen Audit-Zeilen wurden spaltenweise mit
der konsistenten Sicherung verglichen: keine geänderte/fehlende Zeile.
Die gesamte aktuelle Audit-Kette (13.530 Zeilen beim Prüfen) wurde zusätzlich
schreibgeschützt verifiziert; Schema 2 bleibt erhalten.
Beleg rc9-audit-preservation-check.json.

### Offener tatsächlicher Grok-Außenfehler

cloudflared 86602 läuft, /ready auf Port62522 liefert HTTP503/readyConnections0;
die gespeicherte öffentliche Adresse ist lokal nicht auflösbar und liefert über
Cloudflare/Google DNS-over-HTTPS Status3/NXDOMAIN. Das lokal gesunde Gateway
meldet seine erhaltene Version0.5.2. Beleg grok-public-dns-check-20261020.json.

Grok wiederholte diese Abfragen unabhängig und bestätigt denselben Befund:
Antwort 3dfd737e-8d56-4d6f-b86b-cf1374d05900, Übergabe
channel-38d3678c47324ceb9a3c3e82a6bffc9b, Beleg grok-stage6dns-review.json.
Kein Neustart, Signal, Konfigurationswechsel oder Agenteneingriff wurde dafür
vorgenommen. Ein Neuverbinden mit möglichem Adresswechsel ist wegen Daniels
Vorgabe zum Tunnelerhalt noch nicht ausgeführt; die konkrete Rückfrage steht
aus. Kiras getrennt geprüfter MCP-Zugang funktioniert. Eine physische
Grok-Handy-/Audio-Abnahme fehlt weiterhin; der Gesamtauftrag wird deshalb
nicht als vollständig funktionierend ausgegeben.

### Folgeauftrag E01 und Codex-Bereitschaft (RC11-Kandidat, noch nicht aktiviert)

Der Gesamtauftrag `kira-gesamtplan-team-20261020-1031` wurde aus zehn
geordneten `content`-Anlagen übernommen. SHA256 des unveränderten Plans:
`4b8ac493add0b76bd1a353d59d13152bbb5ec62bc956c1def9f1ccc1aa211ca8`,
107935 UTF-8-Bytes. ThreadDesk-Thread `6b5b73b9de36`, Revision 3,
„Gesamtplan ThreadDesk & 4AllPass – 20.10.2026“ wurde vollständig über die
Fach-API nachgelesen; Beschreibung nach Ablagehinweis und anschließende
Notizen ergeben ohne Trennzeichen exakt den Originaltext. Der direkt
erteilte Auftrag und Nachricht `7a7a268e-09c2-4a0f-a333-031cd7fc094c`
sind derselbe Auftrag. Die authentifiziert empfangsquittierte Nachricht
wurde über den vorhandenen Receiver-Abschluss ohne weiteren Agententurn
abgeschlossen. Das bestätigt die Übernahme, nicht die Umsetzung E01–E09.

E01 übernimmt die datierten RC9-/RC10-Belege; neue Arbeit bleibt erkennbar.
Der öffentliche Handy-/Tunnelweg ist laut Gesamtauftrag zurückgestellt.
Die laufende Codex-Übergabereparatur gehört zu E01/ST-01–ST-05. Codex führt
getrennte native Teamaufgaben für Parser-/Regressionen und Client-/Bestand-
Prüfung. Groks unabhängige RC10-Prüfung gilt nicht als RC11-Abnahme.

Der RC9-Codefehler ist unabhängig reproduziert: Bereitschaft nur im
Eingabefeld, Aktivität hingegen im gesamten gelesenen Text. Historische
oder zitierte Arbeitswörter können somit fälschlich sperren. Die aktuelle
Codex-Arbeit und Eingabefeld `q` auf der Aufnahme 10:54 rechtfertigen dort
eine Sperre; zum gescheiterten Live-Versuch 10:49 fehlt die Aufnahme.

Der Kandidat wertet aktuelles Eingabefeld und Status getrennt aus. Eine
ausdrücklich lokal zugeordnete Codex-Thread-ID samt Rolloutdatei liefert
zusätzlich typisierte `task_started`/`task_complete`/`turn_aborted`-Ereignisse.
Die Zuordnung wurde durch eine harmlose einmalige Toolausgabe in genau
22104/ttys000/94023/94386 und derselben vertrauenswürdigen Threaddatei
geprüft; im zusätzlichen Fenster fehlte sie. Keine Auswahl nach Dateialter,
keine Eingabe dafür. Das ist weder ein Identitätsnachweis durch Hash noch
eine Grenze gegen andere Prozesse mit denselben Benutzerrechten.

Historische Arbeitswörter mit belegtem beendetem Turn blockieren den
bekannten leeren aktuellen Prompt nicht. Aktuelle Arbeit, vorhandene
Eingabe, Scrollansicht, unbekannter Zustand und Zielabweichung bleiben
getrennte Gründe. Unvollständige, veränderte oder nicht gebundene Protokolle
liefern unbekannt. Aktuelle Fortschrittsanzeige darf auch durch ein
abweichendes Idle-Protokoll nicht übergangen werden. Sitzungslesewege
zeigen dieselbe Einschätzung; begrenzte Ausgabereferenz und Beobachtungszeit
begleiten Ablehnungen. Die ursprünglichen Fenster bleiben verbindlich.

Ein zweiter Bereitschaftscheck erfolgt vor dem ersten Eingabeversuch.
Wird er abgebrochen, werden `preinput_abort=true` und
`terminal_input_attempted=false` gespeichert; nur dieser belegte Ausgang
ist ohne Eingabewiederholung erneut einreihbar. Nach möglicherweise
ausgeführter Eingabe bleibt der Ausgang unbekannt. Einfügen, separates
Return, authentifizierter Empfang und Antwort bleiben eigene Nachweise.
Bereits extern quittierte Queue-Nachrichten benötigen keinen freien
Terminalprompt, um ohne neuen Turn abgeschlossen zu werden.

Der ursprüngliche Kira-Kurztest `d5f54c18-7068-4abb-9d2f-339fb9a8a526`
bleibt offen. RC10 schrieb vor dem zweiten Check bereits `inserting`;
ein folgender Bereitschaftsfehler wurde deshalb als unbekannt gespeichert.
Vor einem Wiederanlauf sind konkreter Quellstand, Fehlerpfad, Ereignisse,
frische Zielbindung und Eingabefeld abzugleichen. Kein pauschales Löschen
unbekannter Reservierungen. Erst ein beobachteter Ablauf im ursprünglichen
Codex-Fenster samt bei Kira empfangener Antwort `KIRA-TEST-OK` schließt die
praktische Abnahme. Während dieses Reparaturturns ist Codex aktiv.

### RC11 tatsächlich aktiviert, E01-Abnahme weiterhin offen

Commit `20620558aacd03f000843b01fa9a5d75b93901e7` wurde nach Groks Prüfung
über `2f19aa0` auf den bestehenden Architekturbranch übernommen und gepusht.
921 Gesamttests bestanden in169.89s; danach172 gezielte Tests am endgültigen
Korrekturstand. Grok prüfte denselben Commit unabhängig:172 Tests in4.23s,
Ruff sauber, Urteil ship im geprüften Umfang. Antwort
`08fde798-0c91-4643-94c1-f348b67dcf4e`, Übergabe
`channel-0692569ee1864f978a5ef8e5f92b3db3`, authentifizierter Empfang und
verarbeitete Antwort/Abschlussquittung sind getrennt belegt. Grok hat zwei
native Lese-Unteragenten gestartet; deren Ergebnisse lagen bei seiner Antwort
noch nicht vor. Seine Abnahme beruht auf eigener Prüfung und tatsächlichen Tests.

Wheel-SHA256 `5e636856a49d02f9ed632d8ce448f9a58103d14ccbffe13c318e1c0cbb95e4e6`,
alle97 Paketdateien vor Installation mit dem Arbeitsstand byteweise verglichen.
Koordinierte Aktivierung `activation-1de1241553d34a968effcd1cde06c90a`
abgeschlossen, produktiver CorePID40409,86 Python-Dateien, Quell-SHA256
`4acc2f65e9ea1f9b98f14058675a3dc81134353424a7a2d33ae8ae77679b6235`.
Datei-SHA256 `fffa301b73fafb2a52c521d0349b2502c62220914ef89ef4665fa818e9855173`,
effektiver SHA256 `333e5d37d11b40e3cc479af4e2c500ad33680c30c7331409678b33727d063dd5`.
Die tatsächlich verwendete Datei erhielt ausschließlich die beiden zusätzlich
belegten Codex-Protokollfelder; Freigaben, Gate-Abschaltung und sonstige
Einstellungen sind semantisch identisch. Alle16 überwachten bestehenden App-/
Agenten-/TTY-/Tunnelprozesse erhalten. Nur Core und Steuerdienst neu geladen.
Kiras tatsächliche Connectorbindung bestätigte geladenen Quell-/Konfigurationspin.

Der konkrete alte Kurztest bleibt noch unknown: Ein erster lokaler Abgleich
wurde transaktional zurückgerollt, weil der bestehende Receiver-Abschluss
absichtlich keine bereits unbekannten Jobs umklassifiziert. Es wurde keine
Eingabe wiederholt. Der anschließend korrigierte, ausschließlich auf diesen
belegten Vor-Eingabe-Abbruch beschränkte Operatorabgleich scheiterte vor jeder
Mutation am erneut gesperrten Mac. Der Betriebssystemindikator
`CGSSessionScreenIsLocked=Yes` bestätigt diese Sperre unabhängig vom Bridgecode.
Ein begrenzter einmaliger lokaler Prüfer wartet höchstens15Minuten auf Entsperren,
wiederholt dann alle Quell-/Ereignis-/Ziel-/Eingabeprüfungen und führt höchstens
einen Abgleichversuch aus; er sendet selbst keinen Prompt oder Return. Die
ursprüngliche Nachricht würde anschließend über die zentrale Route warten.
Keine allgemeine Unknown-Wiederholung, kein neuer Testauftrag.

Der getrennte Beobachter verwendet ausschließlich Kiras echte angebotene
Connectorbindung und die ursprüngliche Konversation; Frist10:37:58UTC.
Authentifizierter Codex-Empfang, einzelnes Return und tatsächlicher Antwortabruf
von KIRA-TEST-OK bleiben bis zum beobachteten Ablauf offen. Ein Connectorabruf
beweist kein hörbares Audio und weckt keinen inaktiven fremden Workchat.
Der Codex-Reparaturturn muss enden, damit das ursprüngliche Fenster bereit wird.
E02 wird mit isolierten, noch nicht Grok-abgenommenen Kandidaten vorbereitet;
E03–E09 sind damit nicht als abgeschlossen ausgewiesen.

### PR #7 auf dem Mac aktiviert; neue Codex-Sitzung tatsächlich abgenommen

Am 20.10.2026 wurde Kiras Commit `4e0e06680da736344e8fed2e2f854c4147da1307`
auf Basis `500144d` abgeglichen und als `971e685` in den bestehenden
Architekturbranch integriert und gepusht; PR #7 ist merged. Die vorhandenen
unversionierten Nachweise wurden erhalten. Die Korrektur isoliert Empfänger,
speichert Verbindungsfehler vor Übernahme und ermöglicht genau eine passende
Abschlussantwort eines bereits angenommenen Auftrags am Gesprächslimit.
Auf diesem Mac/Python 3.11 bestanden alle **931 Tests in 177.58 Sekunden**,
Ruff für Quellen/Tests und Diff-Prüfung. GitHub-Jobs konnten wegen der
Kontozahlungs-/Ausgabensperre nicht starten; dies ist kein CI-Testnachweis.

Das Paket behält die Versionsnummer `0.8.0rc11`; der korrigierte Stand ist durch
den neuen Quellfingerabdruck eindeutig unterscheidbar. Alle 97 Paketdateien des
Wheels wurden vor und nach Installation byteweise verglichen. Wheel-SHA256:
`5ff399f8dbb3343a841c7de1e6e503678ff58a276d32de8eb2c9ae5d54a0ba85`.
Koordinierte Aktivierung `activation-8dcd99aac6be4de7b0f22d98af75c3f1` ist
completed. Neue Core-PID **73628**, Start **2026-10-20 13:20:56.429925 UTC**,
Instanz `b3407a2b11bd475483249ec1c3b6caed`, 86 Python-Dateien, Quelle:
`8ef2742c04a0a49b67e57136b1e90b1ee7774789830ab6e50ef15a50fd8c5728`.
Kiras echte Connectorbindung bestätigte dieselben geladenen Pins; die lokale
Bereitschaft meldet `service_matches_local_config_and_source=true`.

Die neu gestartete Sitzung wurde durch eine harmlose eindeutige Toolausgabe in
genau dem sichtbaren Fenster und derselben vertrauenswürdigen Rolloutdatei
zugeordnet; in den anderen bestehenden Fenstern fehlte diese Ausgabe.
Ziel bleibt `terminal:22104:ttys000`, Login-PID 94023; Codex-PID jetzt **68530**,
Thread **01a15965-0af7-7562-8e0a-da3b5434eef4**, Rollout:
`~/.codex/sessions/2026/10/20/rollout-2026-10-20T14-59-16-01a15965-0af7-7562-8e0a-da3b5434eef4.jsonl`.
Ausschließlich diese drei Bindungsfelder änderten sich. Berechtigungen,
Zugangsdaten, bestehende Fenster und Tunnel wurden erhalten.

Eine vollständige Kopie der bisherigen venv, das alte geprüfte Wheel,
Konfigurationskopien und konsistente SQLite-Backups liegen privat unter
`~/.config/kirabridge/repairs/receiver-resilience-20261020/`.
Der nachweislich untätige alte Core wurde unter SQLite-Writerlock angehalten;
die drei exakt bestimmten unbeanspruchten Grok-Nachrichten blieben während
Installation und koordinierter Aktivierung erhalten. Der neue Core startete
unter der dauerhaften Aktivierungsbarriere. Alle drei Queueeinträge und 20
überwachte bestehende Terminal-/Agenten-/App-/Tunnelprozesse sind nach Aktivierung
unverändert belegt. Kein Datenbank-Restore und kein Fehler-/Rollbackpfad wurden
ausgeführt. Der Steuerdienst wurde zusätzlich mit signiertem Vor-/Nachprobe auf
PID 73776 neu geladen; Core und Steuerdienst sind die einzigen ersetzten Dienste.

Der bisher als offen dokumentierte Originaltest
`d5f54c18-7068-4abb-9d2f-339fb9a8a526` war inzwischen schon unter PID 94386
abgeschlossen: Antwort `7a1bc622-ceeb-4baa-9441-d1826e6e4ba8` mit KIRA-TEST-OK
wurde von Kira empfangen und quittiert. Dies wurde über den echten Connector
nachgelesen; **keine erneute Ausführung**. Der veraltete Grok-Receiverdatensatz
`e4c91752-bd49-425d-a3ce-a1c8bd887dc4` wurde anhand authentisiertem ACK,
passendem Resultat und abgeschlossenem sichtbaren Handoff ohne Eingabe von
unknown auf completed abgeglichen. Sieben ältere unbekannte verwaltete Aufträge
ohne ausreichenden Abschlussbeleg bleiben unknown; keine Wiederholung.

Für die neue Sitzung wurde genau ein gesonderter Diagnosetest über Kiras echten
Connector eingereicht: Nachricht `e8ecb291-aa21-4abd-9697-bcc1aeddda03`,
Konversation `kira-receiver-session-check-20261020`, Handoff
`channel-33314f046c704376855e5aace657ad8f`. Er wartete ohne Eingabe bis zum
belegten Ende des Reparaturturns. Der danach beobachtete Ablauf (UTC):

| Nachweis | Zeitpunkt |
| --- | --- |
| Einfügen beobachtet, Return ausdrücklich false | 13:24:39.521966 |
| Separates Return gesendet | 13:24:42.727216 |
| Eingabefeld geleert | 13:24:44.673531 |
| Authentisierter Codex-Empfang quittiert | 13:24:53.528699 |
| Passende KIRA-TEST-OK-RECEIVER-FIXES-Antwort erzeugt | 13:24:53.575268 |
| Antwort über Kiras echten Connector empfangen | 13:24:58.419604 |
| Nach Inhaltsprüfung mit Kiras tatsächlichem Receipt quittiert | 13:25:06.298752 |

Antwort-ID `4d9ab69d-b8fb-4bdf-bee5-ed3f991024a3`, sender=codex,
recipient=chatgpt, reply_to=Diagnosetest. Genau je ein
inserting/inserted/submitting/return_sent/sent/confirmed/completed-Ereignis;
Receiverjob und Handoff completed. Der begrenzte Beobachter führte keine Eingabe,
Quittierung oder Wiederholung aus. Dies belegt den aktuellen Terminal- und
Connectorweg, keine hörbare Audioausgabe oder das Aufwecken inaktiver Workchats.

Grok wurde über seinen vorhandenen Zugang unabhängig hinzugezogen. Seine
Prüfung des lokalen Aktivierungsskripts nannte drei Fehlerpfad-Hinweise: einer
war vor Ausführung schon korrigiert; die spätere Prüfung vor Queuefreigabe und
das Anhalten eines untätigen Ersatzcores vor einer hypothetischen Dateirückkehr
wurden zusätzlich abgesichert. Der erfolgreiche Aktivierungslauf betrat diese
Fehlerpfade nicht. Dies ist kein PR-Codeurteil. Die getrennte Prüfung des
vollständigen PR-Diffs und Quellkontexts lieferte bis zu diesem Kontrollpunkt
noch kein Abschlussurteil; sie wird nicht als bestanden ausgegeben.
[Maschinenlesbarer, bereinigter Nachweis](evidence/receiver-resilience-mac-20261020.json).

### Grok-Befunde reproduziert, korrigiert und endgültiger Stand aktiviert

Groks danach eingetroffene PR-Prüfung fand zwei konkrete Blocker: `_waiting`
ersetzte die gespeicherte `receiver_retry`-Frist; unerwartete Exceptions eines
Empfängers konnten über die TaskGroup Geschwister abbrechen. Neun zusätzliche
Regressionen scheiterten vor der Korrektur. Nachtrag
`956b0f81c380895105d32c585b569ea52979adc9` behebt beide Fälle: ursprüngliche
Fristen bleiben erhalten, unerwartete Fehler vor Claim werden sanitisiert als
failed gespeichert, nach Claim als unknown ohne Wiederholung; eine weitere
Fehlergrenze schützt die anderen Empfänger auch bei Beobachtungs-/Speicherfehlern.
Beendete Workerhandles lassen sich wieder starten. Ein zusätzlicher zunächst
scheiternder Test belegt nun auch den Abbruch eines Stop-Warters.

Der verbindliche Lifecycle-Vertrag lautet: Ein angeforderter Stop bleibt bestehen,
wenn nur sein wartender Aufrufer abbricht. Shield erhält die laufende Arbeit; der
Workerhandle bleibt bis zum tatsächlichen Ende zugeordnet. Wartende Nachrichten
bleiben queued und werden erst durch einen ausdrücklich späteren Start nach Ende
des alten Workers genau einmal verarbeitet. Grok bestätigt beide ursprünglichen
Fixes und nennt nach Klärung dieses Vertrags keine konkrete Verletzung mehr.
Grok prüfte ausschließlich lesend und führte selbst keine Tests aus.

Der endgültige Produktionscode bestand **941 Gesamttests in 178.61 Sekunden**
auf dem Mac sowie **35 gezielte Receiverprüfungen**, einschließlich der erweiterten
Stop-/Wiederanlaufprüfung; Ruff für alle Quellen/Tests und Diff-Prüfung sauber.
Commit `956b0f8` ist auf dem bestehenden Architekturbranch integriert und gepusht.
Das neue Wheel wurde erneut in allen 97 Paketdateien vor und nach Installation
byteweise verglichen. Wheel-SHA256:
`bff5aa46541e24124aa9d15a59815a6605c0f9734f49cb87dd735369490ccbcb`.

Koordinierte Aktivierung `activation-c492e4e34fc944f18649da8a37b8c343` completed;
endgültige Core-PID **79466**, Start **2026-10-20 13:38:41.776401 UTC**, Instanz
`1085478016e84c838c55c6eada33d9bf`, 86 Python-Dateien, Quelle:
`cfad2a3026c435192374f26580be3556e51b7641cb36918452ad0f280362ceb7`.
Kiras echter Connector bestätigt diese Pins und aktiven Receiver ohne
Wartungssperre; lokale Quelle/Konfiguration stimmen überein. Steuerdienst nach
signiertem Vor-/Nachprobe PID 79560. Die Konfiguration blieb beim Nachtrag
bytegleich (`e4f3d2aa…43601f8`), einschließlich neuer Codex-Bindung und aller
Berechtigungen. Alle drei ursprünglichen unbeanspruchten Grok-Queueeinträge,
die sieben alten unknown-Datensätze und alle 20 überwachten Prozesse erhalten.
Ein zweiter vollständiger Installationsrückweg liegt unter dem privaten
Belegverzeichnis in `followup/`; kein DB-Restore oder Rollbackpfad ausgeführt.

Die oben belegte einzelne sichtbare Terminaleingabe/Rückantwort gehört zur
dabei geladenen Quelle `8ef2742c…`. Nach dem Nachtrag wurde gemäß ausdrücklichem
„kein weiterer Testauftrag“ keine weitere Terminaleingabe veranlasst. Der Nachtrag
ist durch Fehlerregressionen und die vollständige Suite geprüft; seine aktuellen
geladenen Pins und der authentisierte Nachrichtenrückweg sind zusätzlich live
bestätigt. Die endgültige Ergebnisnachricht
`8c2cd45c-4f1b-43c9-8467-df26b0fce6ce` im beauftragten Gespräch
`kira-receiver-fixes-20261020` wurde als codex/result ohne Dispatch/Antwortanforderung
über den endgültigen Dienst gesendet, um **13:40:19 UTC** über Kiras echten
Connector empfangen und um **13:40:20 UTC** mit dessen tatsächlichem Receipt
quittiert. Ihre Meldung trennt Code, Dienst, Terminalübergabe, Rückantwort und
verbleibende historische Unklarheiten. Der maschinenlesbare Nachweis enthält
beide Aktivierungen und die jeweilige genaue Prüfreichweite.

## E08.2: optionaler Dateiindex, erster begrenzter Prüfschnitt

Auf Architekturbasis `41f4b891a77abd3635738d10a6c38b66efc9ff8d` ergänzt ein eigener
Branch einen standardmäßig ausgeschalteten, separaten Projektdatei-Cache mit
begrenztem Scan/Reconcile, Quellprüfung je Treffer und `file.search` im bestehenden
authentisierten `read_query`. Ein lokaler `file-index`-CLI-Bedienweg erlaubt den
ausdrücklichen Cacheaufbau/-ersatz. Die vorhandenen Rechte `file.read` **und**
`file.list` bleiben erforderlich; Projektwahl schafft keine Freigabe. Weder `/`
noch Home werden als Scanwurzel akzeptiert, aus Rechten werden keine Wurzeln
abgeleitet. Kein Produktdatenbestand, Dienst, Credential oder Livekonfiguration
wurde dafür verändert.

Der [genaue Bedien- und Sicherheitsvertrag](FILE-SEARCH.md) trennt frische
Trefferprüfungen von einer nicht vorhandenen globalen Dateisystem-Snapshotgarantie.
Ergebnisse bleiben ausdrücklich unvollständige Beobachtungen. Der
[Prüfnachweis](evidence/e08-file-index-20261020.json) nennt gezielte Fälle und
noch offene Abnahmen. Dieser Stand schließt **nicht E08 insgesamt**: Watcher,
Änderungsbündelung/Overflow-Recovery, optionale Paketverdrahtung sowie Bridge-
10k/100k-Messungen sind noch offen. Unabhängige Prüfung und Integration folgen
über Root; keine Laufzeitaktivierung ist Bestandteil dieses Patches.
