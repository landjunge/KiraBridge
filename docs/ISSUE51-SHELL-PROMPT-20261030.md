# Issue 51: leere macOS-Shells und ChatGPT-Eingabe · 30.10.2026

## Neuester Stand: Teamauftrag vom 30.10.2026, Build tatsächlich installiert

Der ausdrückliche Folgeauftrag autorisierte Fehlerbehebung, Teamarbeit, Tests,
Build, produktive lokale Installation und Push. Produktcommit
`4a2d32f7383196f2eb089fe6443c64322d3ea1a6`, isolierter Branch
`fix/intel-terminal-install-20261030`, Basis PR54/`40a2e89`. Die nachfolgenden
Nichtinstallationsaussagen sind historische Stände. Kein Merge nach main und
kein öffentliches Release/Ersetzen vorhandener Release-Artefakte.

### Ursache und Korrektur

`visible_handoff.py` markierte den Eingabeversuch vor der letzten Sessionprüfung.
Eine Ablehnung `visible_target_not_ready` vor Paste konnte so als
`visible_handoff_unknown` eine Busy-Reservierung hinterlassen. Jetzt setzt der
vorhandene `before_transport`-Callback die Markierung erst nach finaler Prüfung,
unmittelbar vor Transport. Nachweislich frühe Ablehnungen senden nichts und
sperren keine neue unabhängige ID. Dieselbe alte ID wird nicht erneut ausgeführt.
Echte Unsicherheit nach Transportbeginn bleibt geschützt, ohne automatische Wiederholung.

`session_manager.py` hatte einen Sonderpfad für ungebundene Agenten, der
Idle-/Readiness-/Freigabe-/Intentprüfungen umging. Reproduktion: Busy-Codex,
`require_idle=True`, dennoch Paste/Return, kein Intent-/Freigabeaufruf. Dieser
Sonderpfad ist entfernt; Agenteneingaben brauchen die zentrale geprüfte Route.

Die beobachtete Eingabe wird vor Return erneut verglichen; eine nach der ersten
Paste-Beobachtung veränderte Eingabe wird auch mit erhaltenem Endmarker abgewiesen.
Das beweist keine beliebigen Änderungen vor der ersten Beobachtung. Ein begrenztes
Diagnoseereignis je Handoff enthält Zeit, ID, Dauer, Phase, Status und normalisierte
Fehler-/Ursachencodes, keine Inhalte oder Geheimnisse. Annahme, Übergabe, Return
und tatsächliche Ausführung bleiben getrennt; Busy wird nicht in Erfolg umgedeutet.

Im privaten Snapshot: 26 visible_target_busy, vier visible_handoff_unknown und ein
session_input_unknown-Task. Konkreter jüngster Installations-Handoff:
`codex-kirabridge-install-20261030-1712`, attempt1, started=null, Grund
visible_target_not_ready. Historische Ausführung wird daraus nicht rückwirkend
freigegeben. Kein unbelegter Bezug zu Arbeitsverzeichnis oder Diagnosequote.

Geänderte Implementierung: `visible_handoff.py`, `session_manager.py`,
`scripts/build_desktop_app.py`; Regressionen in `test_visible_handoff.py`,
`test_session_ports.py`, neu `test_desktop_builder.py`. Der Appbuilder schützt
vorhandene/Symlink-Ziele, verlangt einen sauberen Commit und bindet RC/Commit/Swift-SHA.

### Abnahme und tatsächlicher Build

- Vollständiger Intel-Lauf mit exakt gepinnten ThreadDesk-/TollGate-Quellen:
  **1912 bestanden, 1 übersprungen**, 317,28s. Ruff/Format (400 Dateien), Diffprüfung
  und unabhängige Quellprüfung bestanden. Gezielte Teilläufe 121/92/4 bestanden;
  überlappende Tests nicht addieren. Zwischenzeitliche gezielte Fehler wurden vor
  dem vollständigen grünen Lauf korrigiert, nicht nachträglich als grün umetikettiert.
- **23 echte Intel-/MCP-Checkpoints plus unabhängiges Cleanup bestanden**:
  vorhandene Eingabe erhalten, Busy/falsche PID/Race geschützt, Idempotenz belegt.
- Echter isolierter launchd-Upgrade-/Rollbacklauf vom veröffentlichten RC18-Wheel
  zum neuen Paket und zurück bestanden, samt offener authentifizierter HTTP-
  Completion-Abfrage ohne Replay. Konfiguration/Zugänge/Datenbankzeile/Benutzerdatei
  erhalten, Testdienst abschließend unabhängig abwesend (113). `--upgrade-only`
  behauptet keinen neuen Crash-/Fresh-Install-Gesamtlauf.
- Vollständiges vorhandenes Dienstpaket und native App gebaut. **Tauri-Quellen
  existieren in KiraBridge weder im aktuellen Stand noch in erreichbarer Historie.**
  Tatsächlich gebaut/installiert wurde die bestehende Swift/Cocoa/WebKit-App.
  Mach-O x86_64, strenge ad-hoc-Codesignprüfung bestanden, nicht notarisiert.
  Bestehende WebKit-Sendable-Warnung dokumentiert, Compiler Exit0.

| Lokales Artefakt | SHA256 |
| --- | --- |
| KiraBridge-macos.tar.gz | `a54a9bb4a919e9899b3dee024f0325f0d854ec594701387b52fa539f242d64dc` |
| kirabridge-0.8.0rc18-py3-none-any.whl | `b6cf48b84ad28d69642ecb07affb55b28788791c61f7468020299a395c74de8c` |
| App-Binärdatei KiraBridge | `b632ad409d96a4898bf8593f88bce30711adc19bb8eebedd6add828e4bebd2f4` |

Artefakte liegen privat im unten genannten Backupverzeichnis unter `artifacts/`.
Kein neues GitHub-Release, keine neue öffentliche Versionsnummer.

### Installierter Stand und Ausführungsbelege

Der vorhandene transaktionale Installer lief mit `--require-visible-terminal`
in eigenem bestätigten Terminal4906/ttys003/PID19932. Kontrollierter Wechsel von
PID18197 auf **Core-PID20011**, Instanz `e6b4ba7bb3f349c696ccf450177c288a`.
**0.8.0rc18 aus Commit4a2d32f** ist installiert unter
`~/.local/share/kirabridge/install/releases/0.8.0rc18-4a2d32f73831/`.
Alle122 installierten Pythondateien entsprechen dem Wheel. Live-Quellhash
`59d434c982c77d9787a0cc9426a9f6e8ba3dfca4d98366e49a91624014c649df`.
Konfigurationshash unverändert
`52747b8353bef4cc162997c34c30d8e759ca0691725d902f313ce4653cf903c2`.

App `~/Applications/KiraBridge.app`, **PID20022**, sichtbares Fenster „KiraBridge“,
keine Fehlersheets, Version/Quellcommit im Info.plist und Signatur geprüft.
Console **PID20033**, neuer Runtimepfad durch launchd-PID/Argumente und tatsächlich
geöffnete neue venv-Erweiterungen bestätigt. Die alte Console-Plist war positiv
abwesend (113), Port8766 geschlossen; nach Sicherung wurden nur ihr Runtimeargument
und der alte Freigabenstarter aktualisiert. Übrige Plistfelder/Console-Schlüssel
blieben erhalten. Signierter HMAC-Probe bestanden. Eine anfängliche reine
Pfadassertion scheiterte am kanonisierten Homebrew-Python.app-Pfad in ps;
die korrigierte nur lesende Herkunftsprüfung bestand. Keine neue Produktänderung nötig.

Echte HTTP-MCP-Initialisierung als **chatgpt**, 67 Tools/Health bestanden.
Task `intel-terminal-installed-e2e-20261030`: Annahme, completed/attempt1, sichtbare
Ausgabe/Exit0/ein append-only TTY-Beleg. Identische Wiederholung nach bewiesenem
Erfolg bleibt completed/attempt1, Beleg weiterhin einmalig. Der folgende getrennte
native Teil brach mit visible_focus_changed ab; der Gesamtlauf bleibt
**failed_do_not_resend**, die unklare Probe wurde nicht wiederholt.

Danach eigene leere/idle Shell ohne alten Probeinhalt beobachtet; reine Fokusprüfung
ohne Eingabe bestanden. Neue unabhängige Probe `installed-separate-return-v2-20261030`:
Paste sichtbar und noch kein Effekt; anschließend expliziter Return und erwartete
sichtbare Ausgabe/Dateiinhalt bestanden. Diese mit `>` geschriebene Datei beweist
allein keine Genau-einmal-Ausführung; dafür gilt der erste HTTP-Task mit append-only
Beleg. Keine bestimmte externe Ursache des früheren Fokuswechsels wird behauptet.

Eigenen Installations-Terminal nur im bestätigten leeren Idle-Zustand geschlossen,
Abwesenheit unabhängig bestätigt. Vier vorher vorhandene Ansichten
3033/3206/3546/4572 und sieben frisch erfasste Prozessidentitäten erhalten.
Ein zwischen früheren Aufträgen hinzugekommener Operator-Tab blieb unangetastet.
Neue App/Dienste laufen nach Fensterschluss weiter; MCP antwortet.

### Sicherung, Rückweg, offene Punkte

Privat: `~/.local/share/kirabridge/backups/intel-terminal-install-20261030/`:
Gitbundle, alte App/Console-Dateien, aktuelle konsistente SQLite-Sicherung,
Artefakte/Hashes, Installationssteuerung, Testlogs und getrennte fehlgeschlagene/
bestandene Belege. Vollständige alte RC18-Laufzeit zusätzlich unter
`../install-request-20261030-preflight/installed-rc18.tar` verifiziert.
Transaktionaler Rückweg zur vorherigen RC18:
`~/.local/share/kirabridge/install/backups/20261030-174012-8dfa1e9d/`.
RC17-Rückweg `~/.local/share/kirabridge/install/backups/20261029-233225-bdaf86ef/`
unverändert. Produktiver Rollback war nicht erforderlich; keine alte Datenbank
zurückspielen. App/Console-Rückweg wird unabhängig vom Core geführt.

**88 geschützte Dateien hashgleich; 55 unknown Tasks, 24 unknown/blocked Messagejobs
und 7 unknown Handoffs vollständig zeilenhashgleich.** Keine historische Bereinigung,
Freigabe oder Doppelzustellung. Keine OS-Rechte geändert oder umgangen.

Offen bleiben Tauri (keine Quellen), allgemeine logische Eingabeleerheit bei
identischen Anzeigedaten, historischer einzelner Ctrl-U/Tab-Befund und vollständige
Ready-Codex-/Live-/Voice-Host-Abnahme. ARM/Hosted-Mac/Notarisierung nicht abgenommen.
PR54 bleibt Draft, Issue51 offen; lokale Installation war durch neuen Auftrag autorisiert.
Strukturierte Belege stehen unter `intel_terminal_install_20261030` im bestehenden JSON.

## Historischer Einstieg: vorherige Aufträge

Auftrag `channel-fa23a557d4a44e8da2e2be149c9d2564`, Konversation
`shell-control-issue51-oct30`, Nachricht `0416af39-7e3a-4ae5-8849-46be8c9dcf7f`.
Empfang gelesen, Receipt `184202e8-c676-459e-adb0-699743d6d3a9` bestätigt.

Der Shell-Fehler ist im Entwicklungszweig behoben und lokal geprüft.
[Draft-PR54](https://github.com/landjunge/KiraBridge/pull/54), Branch
`fix/issue51-shell-prompt-20261030`, Codecommit
`f869aa53ed84edfa00bb8e7b26538b0d58aa5be4`, Basis main
`307004e5b2e4285c19e8d7544bedf45b28297a0b` nach PR53.
[Issue51](https://github.com/landjunge/KiraBridge/issues/51) bleibt offen.
Keine produktive Installation, kein Neustart, Merge oder Release dieses Auftrags.

## Aktueller Abschlussauftrag: sichere Korrekturen, Merge und Installation gesperrt

Auftrag `channel-83351b4848674ae399afb12e121a982a`, Konversation
`rc18-issue51-finish-20261030`, Nachricht `b537340f-dff3-47f0-ba76-1672a21246fa`,
Receipt `f42ad006-4ecf-4620-9aca-0e99ebaf9ac2` bestätigt. Ausgangs-HEAD
`81070628d2bdcf5b42f3065e5bc7f9f6ed61b06a` war sauber, PR54 offen/Draft, main
`307004e5b2e4285c19e8d7544bedf45b28297a0b`. Kein Merge oder Installationsversuch:
die sichere Eingabeleerheit ist in einem nachgewiesenen Fall nicht entscheidbar,
und vollständige Integrationsgates sind nicht grün.

### Tatsächliche Produktionsfehler korrigiert

Der bisherige Parser akzeptierte beispielsweise `➜  ~ echo$ ` als leer: Nach
Ablehnung durch die strikte Theme-Regel fiel die Zeile in die allgemeine `$`-/`#`-/`%`-
Regel. Außerdem akzeptierte `endswith("KiraBridge visible % ")` einen kontrollierten
Marker innerhalb vorhandener Eingabe. Acht konkrete alte Falschannahmen wurden
als reine Funktionen reproduziert; alle werden jetzt abgewiesen.

Die erkennbare Pfeil-Promptfamilie kann nicht mehr in die allgemeine Regel fallen.
Der reservierte kontrollierte Marker verlangt die vollständige exakte Promptzeile.
Es wird kein Whitespace entfernt oder vorhandene Eingabe gelöscht. Der bisherige
Fehlercode `visible_input_not_empty` bleibt kompatibel; die Meldung beschreibt
jetzt korrekt, dass die Leerheit nicht bestätigt werden kann und vorhandene oder
mehrdeutige Eingabe erhalten bleibt.

Neue ChatGPT-Pfadtests prüfen promptähnliche Eingabe und Marker-Spoofing vor dem
Intent-/Native-Schritt. Im echten MCP-/Intel-Lauf wurden zusätzlich vorhandene
Kommentare mit `$ `, `# `, `% ` und kontrolliertem Marker getestet: alle vor Mutation
abgewiesen und bytegleich erhalten. Die gewöhnlichen unterstützten Prompts bleiben
positiv getestet.

### Renderer und Ctrl-U anhand aktueller Bytes untersucht

Das lokale `/bin/zsh`, Version5.9, wurde auf einem neu erzeugten privaten PTY ohne
Benutzerprofile gemessen. Nach Eingabebyte `0x15` erzeugte es beispielsweise
`ESC[16D`, **16 echte Ausgabeleerzeichen**, anschließend wieder `ESC[16D`.
Der eigene ZLE-Zeuge bestätigte gleichzeitig leeren `BUFFER`, leeres `POSTDISPLAY`
und Cursor0. Rücklöschen und kürzere Zeilen zeigten denselben Bereinigungsmechanismus.
Der eigene Kindprozess endete normal und wurde bestätigt eingesammelt.

Damit ist für das Leeren einer Zeile ein konkreter Ursprung der sichtbaren Restzellen
im tatsächlichen lokalen Zsh-Ausgabestrom belegt. Apples veröffentlichter
[Rendererquellstand](https://github.com/apple-oss-distributions/zsh/blob/666e91a595af505ef61d5f9b87df7a014a4937c6/zsh/Src/Zle/zle_refresh.c#L1890)
beschreibt das Auffüllen einer verkürzten Anzeige auf die alte Breite; später wird
der Cursor zurückgesetzt. Dieser Quellstand wird nicht als Build-Attest des lokalen
Binaries ausgegeben. Der genaue historische Renderzweig beim ursprünglichen
Tastatureinfügen bleibt ohne damaligen Wiretrace nicht rekonstruierbar.

Ein begrenzter Vordergrund-Rohdatenleser im eigenen sichtbaren Fenster empfing
dreimal Ctrl-U als `15`, dreimal die Tab-Kontrolle als `09` und dreimal den
Probe-Tastengriff als `18 02`. Alle neun Phasen haben Bytebestätigung und Ruhefenster;
die gespeicherten TTY-Attribute waren nachher exakt wiederhergestellt. In drei aktuellen
ZLE-Ctrl-U-Versuchen war der Puffer anschließend leer; aktives Binding war
`kill-whole-line`. Eine allgemeine Ctrl-U-zu-Tab-Übersetzung ist damit nicht belegt.
Der einzelne frühere Tab-Befund wurde nicht reproduziert und bleibt ungeklärt.

### Warum die falsche Leerablehnung nicht sicher durch Trimmen reparierbar ist

Ein gezieltes Gegenbeispiel lieferte **identische native Bildschirmbytes und identische
erfasste AX-Werte einschließlich Text, Auswahlbereichen und Einfügezeile** für:

- tatsächlich leeren ZLE-Puffer, Cursor0, verbliebene gerenderte Leerzellen;
- drei tatsächlich eingegebene Leerzeichen im ZLE-Puffer, Cursor0 vor diesen Zeichen.

Nur der ausdrücklich im eigenen Testterminal eingerichtete logische BUFFER-Zeuge
unterschied diese Zustände. Identische beobachtbare Daten können nicht gleichzeitig
als sicher leer und als vorhandene Eingabe klassifiziert werden. Eine Cursor- oder
`rstrip()`-Heuristik würde daher reale Eingabe freigeben. Produktiv bleibt dieser
Fall sicher abgewiesen. Eine allgemeine Lösung benötigt einen zusätzlich autorisierten,
zuverlässigen logischen Eingabekanal; der Diagnose-Hook wird nicht in fremde oder
laufende Benutzershells injiziert. Diese Funktionsgrenze ist ein Mergeblocker dieses
Abschlussauftrags, kein behaupteter vollständig behobener Befund.

### Tests, CI und Erhalt des Rückwegs

- Gezielter erster Lauf: 55 bestanden, davon47 Shelltests und8 Discovery-Prüfungen.
  Verwandter sichtbarer Intel-Lauf: 93 bestanden, einschließlich derselben8.
  Neuer Mehrdeutigkeitsfall einzeln: 1 bestanden.
- Vollständiger Intel-Testlauf mit den unveränderten CI-Pins für ThreadDesk/TollGate:
  **1.890 bestanden, 1 fehlgeschlagen, 1 übersprungen**, 295,08 Sekunden. Der Fehler
  war der alte Test auf die frühere englische Formulierung. Der Test prüft jetzt den
  weiterhin gleichen Fehlercode und weiterhin keinen Intent-/Native-Aufruf.
  Betroffener und direkt verwandter Test danach: **2 bestanden**, 0,33 Sekunden.
  Kein wiederholter Gesamtsuitenlauf und kein umetikettierter grüner Erstlauf.
- Neuer vollständiger realer Intel-/MCP-Lauf: **23 Checkpoints plus unabhängiges
  Cleanup bestanden**. Alle17 Tasks haben Versuchszähler1; acht Abweisungen erfolgten
  vor Eingabeversuch. Drei Payloads liefen je einmal, der Race-Task blieb geschützt.
  Task-`completed` bestätigt nur die Eingabeübergabe; Exitstatus und Ausgabe wurden
  über getrennte Shell-Zeugen belegt.
- Ruff/Format/Compile/Diffprüfung sowie unabhängige Read-only-Sicherheits- und
  Belegprüfung wurden durchgeführt. Einzelne CI-Ergebnisse werden getrennt bewertet.

Am Ausgangs-HEAD gab es **0 Actions-Läufe, 0 Checkruns, 0 Statusmeldungen**.
`MERGEABLE/CLEAN` bedeutete lediglich Konfliktfreiheit. Die letzten Linux-Erfolge
lagen auf älterem HEAD106a777; die dortigen Hosted-Mac-/Paketjobs hatten null Schritte
und eine Zahlungs-/Ausgabenlimitannotation. Lesbare Metadaten zeigen keine erzwungenen
Checkkontexte; administrative Regeln sind nicht vollständig lesbar. Unabhängig davon
gilt die ausdrückliche Betreiberbedingung eines verifiziert grünen Ergebnisses.

Der bestehende Verify-Workflow erhält einen expliziten manuellen Linux-Scope auf den
vorhandenen Debian-Runnern3.11/3.13; automatische Push-/PR-Ereignisse behalten ihre
unveränderte Vier-Plattform-Matrix. Der endgültige Commit wird nach dem Committen
einmal mit `scope=linux` angefordert. Ergebnis und exakter HEAD werden im zugehörigen
Actions-Lauf und im aktuellen PR54-/Issue51-Ergebnis festgehalten; dieser vor Dispatch
geschriebene Bericht ist **kein** CI-Erfolgsnachweis. Manuelle Linux-Jobs erfüllen
keine eventuell geforderten PR-Ereignischecks und machen ausgelassene Mac-/ARM-Jobs
nicht grün. Keine Billingänderung, kein manuelles Hosted-Mac-/ARM-Dispatch.

Alle Hardwarephasen nutzten nur das eigene Fenster4449/PID5469. Es wurde abschließend
geschlossen und unabhängig abwesend geprüft. Die aktuellen ursprünglichen drei
Codex-Tabs3033/3206/3546 und sechs Prozessidentitäten blieben erhalten. RC18 blieb
PID18197 mit gleicher Instanz, Quelle und Konfiguration; alle88 geschützten
Ausgangsdateien einschließlich früherer Aufträge und erfasster RC17-Rückwegdateien
sind unverändert. Keine historische Unknown-/Blocked-/Library-Ausführung.

Private Sicherung, Rohdaten, Testlogs und Gitbundles:
`~/.local/share/kirabridge/backups/rc18-issue51-finish-20261030/`.
Der unveränderte RC17-Rückweg bleibt unter
`~/.local/share/kirabridge/install/backups/20261029-233225-bdaf86ef/` erhalten;
kein produktiver Restore wurde versucht. Strukturierte Belege stehen im bestehenden
JSON unter `rc18_issue51_finish`. Kein Installer oder Release wurde gebaut/veröffentlicht,
keine produktive Installation geändert. Solange Funktions- und Integrationsgates
offen sind, wird die laufende KiraBridge-Verbindung für keinen Installationsversuch
unterbrochen; PR54 und Issue51 bleiben offen. Die vollständige Agentenübernahme mit
ACK/ChatGPT-Empfang und die tatsächliche Live-/Voice-Oberfläche sind durch die
isolierte Shellabnahme ebenfalls nicht abgenommen.

## Vorheriger Stand: Race-Ursache reproduziert, vollständige Abnahme bestanden

Auftrag `channel-8f3be0698a9c44e2822382b88e5f57cb`, Konversation
`issue51-intel-race-retest-20261030`, Nachricht `0a5ed62f-7989-4407-b370-65a187e274b3`,
Receipt `bdfba3c0-67c7-4c91-b93c-1afeb4e8e6dc` bestätigt.
Geprüfte Basis `651cd19bce5a896dcf0102df9f75f44f0e264c02`; nur manuelle Testskripte
und Belege geändert, kein produktiver Quellcode. PR54 bleibt Draft; Issue51 bleibt offen.

**Der neue vollständige Intel-Abnahmelauf ist durchgehend bestanden: 15 Checkpoints
und unabhängig bestätigtes Cleanup.** Frühere fehlgeschlagene Läufe bleiben fehlgeschlagen.

### Belegte Ursache der reproduzierten alten Race-Prüfung

Das alte Tastaturereignis `se.keystroke("# KB_ACCEPT_RACE")` lieferte wiederholt
den korrekten 16-Zeichen-Zsh-Puffer. `POSTDISPLAY` war leer. Trotzdem lieferte
`tab.contents()` hinter diesem Text zusätzliche `U+0020`-Leerzellen. Die damalige
Prüfung `last_line.endswith(" # KB_ACCEPT_RACE")` blieb deshalb über das gesamte
Fünfsekundenfenster falsch; während des gesamten Messfensters blieb dieser
Inhaltsunterschied bestehen. Der erwartete Text fehlte nicht und wurde in diesen
Messungen auch nicht durch das Tastaturlayout übersetzt.

| Abgeschlossene Kontrollreihe | Tatsächlicher Puffer | Sichtbarer Suffix | Alte Prüfung |
| --- | --- | --- | --- |
| Drei originale Tastaturereignisse | jeweils exakt `# KB_ACCEPT_RACE` | zusätzlich 3 / 1 / 5 Leerzellen | in allen Messungen falsch |
| Drei weitere Originalereignisse ohne Puffer-Probe vor der Eingabe | jeweils exakt derselbe Text | zusätzlich 1 / 4 / 8 Leerzellen | in allen Messungen falsch |
| Drei bewachte Paste-Kontrollen desselben Texts | jeweils exakt derselbe Text | exakt, keine zusätzlichen Leerzellen | jeweils richtig |
| ASCII `abc`, einzelnes `_` | jeweils exakt | exakt | richtig |
| Einzelnes echtes Eingabeleerzeichen | tatsächlicher Puffer `U+0020` | Leerzeichen vorhanden | zeigt, warum Leerzeichen nicht pauschal entfernt werden dürfen |

Die zweite Reihe begann jeweils mit einer erkannt leeren Promptzeile und führte
vor dem Tastaturereignis keinen Probe-Widget-Aufruf aus. Dieser Aufruf vor der Eingabe
ist damit keine notwendige Bedingung des Effekts. Der eigene ZLE-Hook wurde erst nach den
Bildschirmaufnahmen ausgeführt und schrieb `BUFFER`/`POSTDISPLAY` in private Dateien.
Sein Name beginnt mit `_`, damit der vorhandene Autosuggestion-Wrapper diese
Beobachtung nicht vorher durch Leeren von `POSTDISPLAY` verändert.

Präziser Befund: **Die alte Testannahme, gerenderte Terminalzeichen endeten exakt
mit den Eingabebytes, ist für diesen reproduzierten Tastaturweg falsch.** Der interne
Ursprung der variablen Leerzellen im Renderer ist nicht nachgewiesen. Der alte V1-Lauf
enthält keine gespeicherte Bildschirmaufnahme nach seinem Tastaturereignis; seine
individuellen damaligen Endbytes sind nicht nachträglich rekonstruierbar. Der gleiche
Ereignis-/Erwartungspfad mit seinem Timeout ist jetzt mehrfach belegt reproduziert.
Die 5-Sekunden-Beobachtung scheiterte vor dem eigentlichen nativen Guard; die
15-Sekunden-Native- und 30-Sekunden-Admission-Timeouts sind damit nicht gleichzusetzen.

Der produktive Textpfad verwendet `doScript` bzw. bewachten AX-Paste; ein
`se.keystroke()`-Textpfad existiert im geprüften `src/kirabridge` nicht. Für die
Race-Fixture bleibt deshalb der echte bewachte Paste-Weg aus dem vorherigen Auftrag
maßgeblich. Produktionsguards wurden weder durch `rstrip()` aufgeweicht noch durch
automatisches Löschen oder Return ersetzt.

### Vollständiger aktueller Intel-Lauf und Datenerhalt

Nach der Ursachenprüfung wurde **dasselbe** eigene Fenster `terminal:4098:ttys003`,
PID68961, für die komplette authentifizierte MCP-Abnahme wiederverwendet. Die private
Übernahmebescheinigung wird mit Task, UID, PID/TTY/Startzeit/Image, erkannt leerem
Prompt und vollständigem ursprünglichem Fenster-/Prozesssatz abgeglichen. Ein
beliebiges bestehendes Terminal wird anhand einer bloßen gespeicherten pane_id nicht
als Testfenster übernommen.

Im neuen durchgehenden Lauf bestanden alle vorherigen Fälle: authentifizierter
ChatGPT-Principal, Eingabe/Submit/Return, echte Ausgabe und Status0/7, gleichzeitige
und späte identische Anfrage ohne Doppelwirkung, Inhaltskonflikt, vorhandene Eingabe
bytegleich geschützt, positiv belegtes Busy, falsche PID/TTY vor Mutation, keine
spätere Ausführung einer abgewiesenen ID, tatsächlicher `visible_input_changed`-Guard
und kein versteckter Ersatzweg. Genau drei Payload-Ausführungsdateien enthalten
je eine TTY-gebundene Zeile, Status0/7/0. Alle sechs Ablehnungs-/Konflikt-/Race-Dateien
fehlen. Der erwartete Race-Task bleibt konservativ `unknown`; auch dessen identische
Folgeanfrage verursacht keinen weiteren Dispatch. Alle Taskversuche haben Zähler1.
Inputversuch-Flags wurden aus den erhaltenen Taskevents schreibgeschützt nachgelesen.

Fenster4098 wurde nach dem vollständigen Lauf geschlossen und seine Abwesenheit
unabhängig verifiziert. Ursprüngliche fünf Tabs und acht Prozessidentitäten sind
unverändert; der private MCP-Port ist unabhängig unerreichbar. RC18 bleibt PID18197
mit unveränderten Instanz-/Konfigurations-/Quellhashes. Alle 28 vorab geschützten
Dateien einschließlich früherer privater Taskzustände und erfasster RC17-Rückwegdateien
sind hashgleich. Keine Installation, kein Installerbau, Restore, Merge oder Release.

Zwei zusätzliche Diagnoseabbrüche sind vollständig erhalten: `diagnosis` erfasste
einen Originalversuch und scheiterte danach an der optischen Leerprüfung beim
Aufräumen; `diagnosis-repeat` erfasste zwei und stoppte vor Return, weil Ctrl-U einen
tatsächlichen Tab im Puffer zurückließ. Dessen Ursache ist offen. Beide Fenster
4032 und4035 wurden ausschließlich als eigene, idle Fixtures geschlossen, die
Abwesenheit und ursprünglichen Identitäten unabhängig geprüft. Danach leert ein
eigener ZLE-Testhook den Puffer nur nach unmittelbarem Vergleich mit den zuvor erfassten
eigenen Bytes; eine vollständige Bestätigung und erneute Empty-BUFFER-Prüfung gehen
dem leeren Return voraus. Unbekannte Eingabe wird niemals mit Return abgeschickt.
Die erfolgreiche Diagnose und Vollabnahme nutzten anschließend nur Fenster4098.

### Reproduzierbare Befehle und Grenzen

Aus dem Entwicklungs-Worktree, mit neuem, noch nicht vorhandenem privatem Testpfad:

```sh
KB_TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/kirabridge-race.XXXXXX")"
uv run python scripts/diagnose_shell_keystroke_intel.py --root "$KB_TEST_ROOT/diagnosis-controlled" --repeats 3 --allow-one-owned-visible-window
uv run python scripts/diagnose_shell_keystroke_intel.py --root "$KB_TEST_ROOT/diagnosis-no-preprobe" --repeats 3 --allow-one-owned-visible-window --owned-window "$KB_TEST_ROOT/diagnosis-controlled/owned-window.json" --without-preprobe --original-only
uv run python scripts/accept_shell_input_intel.py --root "$KB_TEST_ROOT/full" --allow-one-owned-visible-window --case full --owned-window "$KB_TEST_ROOT/diagnosis-no-preprobe/owned-window.json"
```

Tatsächliches `KB_TEST_ROOT` dieses Auftrags:
`~/.local/share/kirabridge/backups/issue51-race-retest-20261030/`.
Vorheriges Git-Tar/Bundle und geschützte Dateihashes wurden vor Eingriffen geprüft;
private vollständige Logs, Screens, ZLE-Zeugen und Taskdatenbanken bleiben erhalten.
Der bestehende [strukturierte Beleg](evidence/issue51-shell-prompt-20261030.json)
enthält die Messreihen und den vollständigen Lauf unter `intel_race_retest`.
Read-only-Review bestätigte die Messungen, Statusdateien, fehlenden Effektdateien,
Taskevents und Cleanup unabhängig. Ruff/Format/Compile/Diffprüfung bestanden.

Wesentliche Grenze: Nach tatsächlichem Leeren kann eine sichtbare Restfläche aus
Leerzellen bleiben. Der Produktionsparser kann diese tatsächlich leere Shell weiterhin
konservativ abweisen. Der nur im eigenen Diagnoseterminal verfügbare BUFFER-Zeuge
ist keine generelle Voraussetzung oder neue Funktion von KiraBridge. Echtes bereits
eingegebenes Whitespace muss geschützt bleiben. Die interne Ursache der sichtbaren
Restzellen und des getrennten Ctrl-U/Tab-Befunds bleibt offen; kein CWD-Kausalbeleg.
Atomarer Schutz gegen jeden möglichen manuellen Eingabezeitpunkt ist nicht bewiesen.

ARM/gehostete macOS-CI wurden nicht ausgeführt oder vorausgesetzt. Der Test-/Belegcommit
verwendet `[skip ci]`; fehlende Pflichtgates sind weiterhin kein Erfolg. Die vollständige
Codex-Übernahme/ACK/ChatGPT-Empfangsabnahme und tatsächliche Live-/Voice-UI-Abnahme
bleiben offen. Produktiver Wechsel ausschließlich nach neuer Freigabe.

## Kontrollierte Intel-Abnahme · vorheriger Zwischenstand 30.10.2026

Auftrag `channel-6608bf39af4544e891acd84fb7e9cbff`, Konversation
`issue51-intel-acceptance-20261030`, Nachricht `cb56d321-3d00-4f71-a8a2-cc5c4cb18c15`,
Receipt `255c6c1b-2b7c-4fc0-9db4-c3f3f2775987` bestätigt.
Geprüfte PR54-Basis `106a777c6ae195847b31adc456a4dcd14857adb8` unverändert.
Produktionscode wurde in diesem Folgeauftrag nicht verändert.

Die angeforderten Shell-Fälle sind durch den ersten Lauf und die gezielte Wiederholung
des fehlerhaften Testfixture-Falls belegt. **Der erste Gesamtlauf bleibt fehlgeschlagen**;
es wird kein durchgehend erfolgreicher Gesamtlauf behauptet. Die Wiederholung prüfte
ausschließlich den Zustandswechsel und direkt zugehörige Schutz-/Cleanup-Prüfungen.

Methode: [manuelles Intel-Abnahmeskript](../scripts/accept_shell_input_intel.py),
leerer privater Zustandsordner, flüchtiger zufälliger Token für Principal `chatgpt`,
authentifizierter lokaler HTTP-MCP-Endpunkt auf freiem Loopback-Port. Der Weg ist
`action_request` → echte Autorisierung/Preflight/native Admission → `session.input`
→ bestätigter nativer Transport. Es wurden weder `_execute` direkt aufgerufen noch
die Bereitschaft erfunden. Die reale Katalogbeobachtung wurde auf das eigene Fenster
eingegrenzt. Raw-send, unsichtbare Kommandoausführung und weitere Fensteröffnungen
waren mit fehlschlagenden Testfallen versehen; kein solcher Ersatzweg wurde aufgerufen.
Die Token wurden weder ausgegeben noch versioniert.

| Fall | Bestätigtes Ergebnis |
| --- | --- |
| Eingabe und Return | Native `doScript`-Übermittlung mit `submitted=true`; tatsächliche Kommandos auf der eigenen `/dev/ttys003` ausgeführt. Kein behauptetes separates Tastatur-Return-Ereignis für diesen Submit-Zweig. |
| Ausgabe und Abschluss | Standalone-Ausgabezeilen über MCP `read_query/session.read` gelesen, Shell-Statusmarker und private Statusdateien für Exit0 und Exit7 verglichen. |
| Genau einmal | Zwei gleichzeitige identische HTTP-Anfragen und eine späte identische Anfrage: ein Taskversuch, ein nativer Dispatch, eine Ausführungszeile. Geänderter Inhalt bei gleichem Schlüssel: `idempotency_conflict`, keine Ausführung. |
| Vorhandene Eingabe | Eigener harmloser Kommentar per echtem Paste-only-Weg eingefügt; neue Eingabe mit `visible_input_not_empty` vor Mutation abgewiesen, Puffer bytegleich erhalten. Erst danach eigener verifizierter Kommentar mit bewachtem Return abgeschlossen. |
| Busy | Eigene begrenzte Vordergrundfixture positiv als busy beobachtet; `session_busy` vor Mutation. Dieselbe abgewiesene ID blieb nach Idle fehlgeschlagen und wurde nicht nachgeholt. |
| PID/TTY | Falsche PID und nicht vorhandene TTY ausschließlich innerhalb der eigenen Fenster-ID: `session_selection_changed`, keine Mutation und keine Ersatzfenster. |
| Zustandswechsel | Im gezielten zweiten Lauf eigenen Kommentar über bewachten Paste-Weg unmittelbar vor dem echten nativen Guard eingefügt und sichtbar gelesen; `visible_input_changed`, kein Prüfkommando ausgeführt. Der Task blieb konservativ `unknown`; identische Folgeanfrage bewirkte keinen neuen Dispatch. |
| Isolation | Unauthentifizierte Anfrage: HTTP401. Beide privaten Endpunkte nach Ende unabhängig unerreichbar. |

`session.input` meldet weiterhin nur den Abschluss der Eingabeübergabe, keinen eigenen
Shell-Exitstatus. Die Abnahme trennt daher diesen Taskstatus von den tatsächlichen
Ausgabe-/Exitstatuszeugen; insbesondere ist der Inputtask bei Shell-Exit7 `completed`.
Das ist keine neue produktive Funktion zur allgemeinen Prozessüberwachung.

Erster Lauf `run-v1`: zwölf bestätigte Checkpoints, dann Timeout beim Beobachten der
per Tastaturereignis erzeugten Race-Fixture. Deshalb privater Testtask
`intel-race-rejected` = `unknown/execution_error`, Exceptiontyp `TimeoutError`;
kein Ausführungsreceipt. Mangels gespeicherter endgültiger Fixture-Zeile ist die genaue
Ursache dieses Tastatur-Fixture-Verhaltens offen. Der eigentliche native Race-Guard
war in diesem Lauf nicht als geprüft zu werten. Log und privater Taskzustand wurden
geschützt, nicht umgeschrieben oder erneut ausgeführt; alle 14 geschützten Dateien
blieben nach dem zweiten Lauf hashgleich.

Danach ausschließlich die Testfixture auf den bereits geprüften bewachten Paste-Weg
umgestellt. `run-v2 --case state-change` verwendete einen neuen privaten Zustandsordner
und neue IDs; vier Checkpoints und vollständiges Cleanup erfolgreich. Das ist die
gezielte Nachprüfung des betroffenen Falls, keine Wiederholung historischer Nachrichten.
Die erwartete konservative `unknown/visible_input_changed`-Test-ID bleibt erhalten.
Read-only-Review des Abnahmeskripts vor beiden Läufen: keine verbleibenden Blocker.

Fenster nacheinander, nie gleichzeitig: v1 `terminal:3922:ttys003`/PID52314,
v2 `terminal:3928:ttys003`/PID53092. Beide geschlossen und jeweils durch neue Inventur
unabhängig abwesend. Vorher/nachher dieselben fünf ursprünglichen Tab-IDs
3033/3206/3541/3546/3903 und dieselben acht UID/PID/TTY/Startzeit/Parent/Image-Identitäten.
RC18 blieb PID18197, Instanz-, Quell-, Konfigurations- und effektiver Konfigurationshash
vor/nachher identisch. Sieben erfasste RC17-Rückweg-/Manifestdateien blieben hashgleich.

Neue private Sicherung `~/.local/share/kirabridge/backups/issue51-intel-acceptance-20261030/`:
verifiziertes Vorab-Tar/Gitbundle, Harnessstände, vollständige lokale Logs, Screens,
Status-/Ausführungsreceipts, beide privaten Taskdatenbanken und SHA256-Manifeste.
Der bestehende [strukturierte Beleg](evidence/issue51-shell-prompt-20261030.json)
enthält den Nachtrag unter `intel_acceptance`; ursprüngliche Belege bleiben erhalten.

ARM und gehostete macOS-CI wurden in diesem Auftrag **nicht ausgeführt**. Der reine
Test-/Dokumentationscommit verwendet wegen dieses ausdrücklichen Auftrags `[skip ci]`;
übersprungene CI ist kein Erfolg und ersetzt keine offenen Integrationsgates.
Keine Installation, kein produktiver Neustart, keine Änderung am RC17-Rückweg,
kein Merge, Release oder Schließen von Issue51. Offen bleiben beliebige Prompt-Themes,
atomarer Schutz gegen jeden möglichen manuellen Eingabezeitpunkt und die vollständige
Codex-Paste/Return/ACK/ChatGPT-Empfangsabnahme. Die private MCP-Authentifizierung ist
kein Nachweis der Bedienoberfläche einer tatsächlichen ChatGPT-Live-/Voice-Sitzung.

Nächster sicherer Schritt: diese Belege in Draft-PR54 prüfen und Integrationsgates
getrennt entscheiden; produktiver Wechsel erst nach neuer ausdrücklicher Freigabe.

## Belegte Ursache

1. Ein vorhandener freier Shell-Tab wurde ausschließlich gelesen. Seine letzte
   nichtleere Bildschirmzeile war `➜  ~ ` mit unverändertem abschließendem Leerzeichen
   und anschließend leeren Terminalzeilen. `.zshrc:11` setzt `ZSH_THEME="robbyrussell"`;
   die vorhandene Theme-Datei definiert Pfeil, zwei Leerzeichen, Verzeichnis und
   Leerzeichen sowie optionale Git-Dekoration. Diese Dateien wurden nicht geändert.
2. Der tatsächliche Pfad ist `session.input` → `SessionManager.send` →
   `direct_terminal_required` für Principal `chatgpt` oder `client_type=chatgpt` →
   `TerminalAppTransport.send_confirmed` → `empty_shell_prompt`.
   Der Parser in `platform_adapters/shell_prompt.py` akzeptierte `%`, `$`, `#`
   und den kontrollierten KiraBridge-Prompt, nicht den beobachteten Theme-Prompt.
   Deshalb `visible_input_not_empty`, bevor die native Eingabe beginnt.
3. `send_confirmed` enthielt zusätzlich eine eigene JavaScript-Promptprüfung mit
   derselben Lücke. Eine alleinige Python-Korrektur hätte diese zweite Ablehnung
   nicht beseitigt. Der Agent-Promptparser `visible_readiness.py` steuert diesen
   Shell-Zweig nicht. Die Ursache ist keine belegte Arbeitsverzeichnisstörung.
4. Frühere erfolgreiche Shelltests als Principal Codex verwendeten den anderen
   `send`-Zweig und waren kein Nachweis für funktionierende direkte ChatGPT-Eingabe.
   Die neuen Tests prüfen ausdrücklich den ChatGPT-Zweig.

Quellen: [Promptparser](../src/kirabridge/platform_adapters/shell_prompt.py),
[SessionManager](../src/kirabridge/session_manager.py),
[Cliententscheidung](../src/kirabridge/permissions.py),
[nativer Transport](../src/kirabridge/platform_adapters/terminal_app.py).

## Änderung und Sicherheitsgrenzen

- Zusätzliche strikte Erkennung `➜  <ein Verzeichnistoken> `: exakt zwei Leerzeichen
  nach dem Pfeil, genau ein abschließendes Leerzeichen, maximal 240 Tokenzeichen.
  Vorhandene Eingabe, zusätzliche Leerzeichen, Steuerzeichen, Fortsetzungsprompts,
  Git-Dekoration und Verzeichnistoken mit Leerzeichen bleiben abgelehnt.
- Die doppelte native Promptheuristik entfällt. Stattdessen prüft der native Schritt
  die letzten 8192 Unicode-Codepoints des akzeptierten Bildschirminhalts vor und
  nach dem Fokussieren auf Gleichheit. Auch ein Wechsel zu einem anderen gültigen
  leeren Prompt führt jetzt zum Abbruch. Busy wird unmittelbar vor `doScript`
  erneut geprüft; UID/TTY/PID/Startzeitprüfung und Unsicherheitsbehandlung bleiben.
- Kein Löschen vorhandener Eingabe, kein Probe-Return, keine automatische Wiederholung,
  kein Wechsel in einen anderen Tab und kein versteckter Transport als Ersatz.

Textbasierte Promptbeobachtung ist weiterhin begrenzt: beliebige Themes, Git-Dekoration,
  mehrzeilige Prompts und Shells mit Verzeichnisleerzeichen sind nicht allgemein
  abgenommen. Die Bildschirmvergleiche sind kein atomarer Betriebssystem-Lock gegen
  gleichzeitige manuelle Eingabe. Der Fehlercode für einen unbekannten Prompt bleibt
  aus Kompatibilitätsgründen `visible_input_not_empty`.

## Tests und unabhängige Prüfung

Intel iMac17,1, macOS 15.7.4 / Build24G517, x86_64, Python3.11.15, uv0.11.6,
isolierte Worktree-venv, `uv sync --locked --dev --python /usr/local/bin/python3.11`.

Gezielter Lauf:

```sh
uv run pytest -q tests/test_shell_prompt.py tests/test_plain_shell_paste.py tests/test_discovery_visible.py tests/test_session_dispatch_evidence.py tests/test_sessions.py tests/test_terminal_tabs.py
```

Erster Lauf: **124 bestanden, 1 fehlgeschlagen**. Ausschließlich der neue Test
verwendete den nicht vorhandenen Enum-Namen `State.SUCCEEDED`; nach Korrektur auf
`State.COMPLETED` bestand der einzelne betroffene Test. Der zusätzliche Test für
den gemeinsamen Paste-only-Promptpfad bestand ebenfalls. Damit sind **126 verschiedene
relevante Tests bestanden**, kein wiederholter lokaler Gesamtsuitenlauf.

Die sieben Tests mit tatsächlich erzeugtem nativen JavaScript prüfen Erfolg,
Inputänderung vor Dispatch, Wechsel zu anderem leeren Prompt, Inputänderung beim
Fokuswechsel, Busy beim Fokuswechsel, Busy vor Dispatch und geänderte Prozessidentität.
JavaScript läuft gegen einen Fake-Application-Host ohne Zugang zu Terminal.app.
Nach Ergänzung des Subprozess-Aufräumens im Harness wurden genau diese sieben Fälle
erneut erfolgreich geprüft. Fehlerfälle belegen null `doScript`-Aufrufe.
Weitere Tests prüfen den echten Task-/ChatGPT-Zweig, Callback-Abbruch und verhindern
den ungeschützten Raw-send-Fallback. Ruff, Formatprüfung und `git diff --check` bestanden.
Native Read-only-Subagentprüfung des Source-/Test-Diffs: kein blockierender Befund.

## Echter isolierter Intel-Test

Nur ein neu angelegtes eigenes Fenster `terminal:3912:ttys003`, Shell-PID43881.
Die übrigen Tabs wurden weder beschrieben noch geschlossen. Isolierte Bridge-Instanz
mit explizitem Principal `chatgpt`, eigenen temporären Zustandsdateien und ausschließlich
Entwicklungscode; keine Verbindung zu einer zweiten Daemoninstanz und keine Änderung
der produktiven Konfiguration.

Der echte frische Prompt `➜  owned-shell ` wurde vom Baseline-Parser abgelehnt und
vom Fix akzeptiert. Zwei `SessionManager.send("chatgpt", ...)`-Aufrufe über den
nativen bestätigten Pfad schrieben jeweils einen unterschiedlichen harmlosen Marker
in eine private Receipt-Datei. Beide Marker sind exakt einmal vorhanden, zusammen
zwei Zeilen; Receipt-SHA256:
`338c2c7480c8208f1094273d58589e9bbba6b82ca41370264af029d9768e4bf9`.
Dies belegt diese zwei Shellkommandos; es ist keine vollständige Agent-Handoff-Abnahme.

Das eigene Fenster wurde nach Idle-/PID-Prüfung geschlossen. Eine neue unabhängige
Inventur bestätigt denselben ursprünglichen Satz aus fünf nativen Tab-IDs
3033/3206/3541/3546/3903; alle acht ursprünglichen Prozessidentitäten unverändert.
[Strukturierter Beleg](evidence/issue51-shell-prompt-20261030.json).

## Sicherungen, Produktion und verbleibende Gates

Private lokale Sicherung:
`~/.local/share/kirabridge/backups/issue51-shell-prompt-20261030/`.
Vor Änderungen `main-before.tar` und vollständiges `before.bundle`, beide SHA256
gegen `backup-manifest.json` nachgelesen; `git bundle verify` erfolgreich.
Nach dem Abschnitt Kopien aller vier geänderten Code-/Testdateien mit unabhängig
nachgelesenen SHA256 in `verified-change-manifest.json`. Privater `live_probe.py`,
`live-probe-result.json` und Receipt erhalten. Keine Geheimnisse in Git aufgenommen.

Produktionsbeobachtung vor/nach Test identisch: RC18, PID18197,
Instanz `82cd506b1d854b50b4cc58c5016fc856`,
Quellhash `bea0158935efd09a2304be2eb024ce79d5a100cf754742dcbe52aaddce1dc9ee`,
Konfigurationshash `52747b8353bef4cc162997c34c30d8e759ca0691725d902f313ce4653cf903c2`.
RC17-Rückweg und veröffentlichte Releases bleiben unverändert; siehe vorhandenen
[Installationsbericht](RC18-PUBLISH-INSTALL-20261029.md).

Automatische GitHub-Läufe zum Codecommit: Verify push40987909261,
Verify PR40987936366, macOS-Paket40987936257. Paketjobs haben null gestartete Schritte;
Annotation von Job123843220658 nennt fehlgeschlagene Kontozahlung/Ausgabenlimit.
Kein manueller Dispatch oder Retry, keine Billingänderung. Linux war beim ersten
Dokumentationsstand noch in Arbeit; maßgeblich ist der aktuelle PR-Checkstatus.
ARM und bezahlte macOS-Ausführung bleiben zurückgestellt, kein behaupteter Erfolg.
Der GitHub-Connector lehnt den direkten Job-GET als nicht zugelassenen Endpunkt ab;
deshalb wurde ausschließlich diese fehlende Read-only-Ansicht über `gh api` gelesen.

Historische unknown/blocked-/Library-Aufträge wurden weder wiederholt, freigegeben
noch bereinigt. Die aktuelle Übergabe wurde tatsächlich empfangen, hat aber einen
separaten `delivery_timeout`/unknown-Status nahe Return; sie wurde nicht erneut gesendet.
Dieser Zeitablauf ist kein Beleg für eine Ursache im Shell-Promptparser.

Der damalige nächste Schritt war die Shellabnahme einschließlich Ausgabe/Exitstatus;
der Folgeauftrag oben belegt diese im privaten authentifizierten MCP-Test. Die
vollständige Codex-Paste/Return/ACK/ChatGPT-Empfangsabnahme und separate Freigaben
bleiben offen. Issue51 erst nach seinen vollständigen Abnahmekriterien schließen.
