# Issue 51: leere macOS-Shells und ChatGPT-Eingabe · 30.10.2026

## Neuester Stand: RC20 behebt die Sperre nach geschlossenem Terminal

Der Nutzer bestätigte das versehentliche Schließen des Terminals und beauftragte
ausdrücklich die dauerhafte Behebung samt Installation. **RC20 aus
`da1bdaed019c31aa11bb28a39ef8bead7e73c1d4` ist tatsächlich installiert und aktiv.**
Die folgenden RC19-Stände bleiben historische Nachweise.

### Ursache und Korrektur

Der neue Auftrag `codex_hallo_test_20261030_2` scheiterte um20:27:51 mit
`visible_target_busy`: altes UNKNOWN für3033/ttys001/Shell70676/Agent71896,
neues ausdrücklich adressiertes Fenster6022/ttys001/Shell42082/Agent42144.
macOS hatte nach dem Schließen dieselbe TTY-Kennung wieder vergeben. Die
Ressourcenprüfung verlangte auch vor der starken nativen Abwesenheitsprüfung eine
andere TTY und erreichte den bereits vorhandenen Nachweis deshalb nie.

`distinct_window_processes` erlaubt nun ausschließlich den Einstieg in diesen
Nachweispfad bei anderer Fenster-ID und disjunkten positiven Shell-/Agent-PIDs.
Erst eine frische vollständige native Fensterinventur und zwei OS-Prozessinventuren
vor/nach dieser Inventur bestätigen, dass altes Fenster und beide alten Prozesse
fehlen. Unveränderte strikte Ressourcenregeln gelten weiterhin für die Ausnahme
ohne Abwesenheitsnachweis. Lebende/unklare Fenster, überlappende oder wiedervergebene
PIDs, unvollständige Inventuren und aktuelle Arbeit/Eingabe bleiben geschützt.
Alte UNKNOWN-Nachrichten werden weder wiederholt noch pauschal abgeschlossen.

Zusätzlich bleibt bei A→B→C-Zielwechseln der ursprüngliche Konfigurationsanker A
erhalten. Nach einem Dienstneustart wird dadurch C wiederhergestellt. Eine unabhängig
manuell geänderte Bindung beginnt eine neue Kette. Der native Abwesenheitsnachweis
und seine Queue-Retirement-Verwendung wurden nicht aufgeweicht.

### Belege

Gegen unveränderter Basis99ddc20 scheiterten beide neuen Übergabewege reproduzierbar
mit Busy. **213 verschiedene relevante Tests bestanden**: ein gemeinsamer212er-Lauf,
danach ausschließlich der zusätzliche Reviewfall für eine gesendete, nachweislich
beendete Reservierung. Weitere21 Tests für Appmetadaten und sichtbare Installation
bestanden. Ruff/Format/Diff und unabhängige Quellen-/Sicherheitsprüfung bestanden;
keine wiederholte Gesamtsuite.

Die echte Intel-Abnahme verwendete nacheinander eigene `head`-Prozesse und höchstens
ein zusätzliches natives Testfenster. Beide Übergänge **6037→6040→6043** verwendeten
tatsächlich **ttys002**. Der alte Guard war jeweils false, der korrigierte Guard
bestand mit echten Fenster-/Prozessnachweisen. Live-Reservierung blieb gesperrt;
nach beiden Schließvorgängen war das neue Ziel bereit. Eine neu geöffnete Bridge
stellte das dritte Ziel aus der ursprünglichen Konfiguration wieder her. Alte
Fixturezeilen/-nachrichten/-events blieben hashgleich. Kein Paste, Return oder Replay;
alle eigenen Fenster/Prozesse unabhängig abwesend, ursprüngliche6021/6022 und ihre
Prozessidentitäten erhalten. Dies ist keine neue vollständige Codex-ChatGPT-Übergabe.

Zwei vorangegangene Abnahmeläufe bleiben als fehlgeschlagen dokumentiert: zuerst
verwechselte der Test visuell gruppierte Tabs mit nativen Scriptingfenstern; danach
fehlte dem isolierten Testzugang `task.read`. Beide Testaufbaufehler sind im Harness
korrigiert. Das erste eigene Fenster wurde separat über exakte Identitäten und den
privaten Ausgabedeskriptor kontrolliert bereinigt; der zweite Lauf bereinigte sich
selbst. Keine Produktionsänderung während dieser Läufe. Der dritte Lauf bestand
vollständig samt Cleanup. Der Produktcode blieb seit dem Paketbuild unverändert.

Auch der tatsächliche alte Nutzerfall3033→6022 mit wiederverwendeter ttys001 wurde
gegen echte native Abwesenheitsnachweise ausschließlich lesend bestätigt.

### Installation, Erhalt und Rückweg

Quellgebundenes Paket und native Swift/Cocoa/WebKit-Intel-App aus exakt da1bdae,
strenge ad-hoc-Signaturprüfung bestanden. Umschaltung durch den vorhandenen
transaktionalen Installer im frisch bestätigten separaten Terminal6021/ttys000,
Shell42079/Installer47011. App und Console nur nach Eigentümer-/Leerlaufprüfung
ersetzt, kein Agent gestoppt. App und Dienst melden beide **0.8.0rc20**; CorePID47085.
Alle122 installierten Pythondateien stimmen bytegenau mit dem Wheel überein.
Live-Quellhash: `4ddc9c375532fcdaa1e77c9b55f05d3f28eaf5e943ad29ba0a9eca39f55dbbe6`.

Konfiguration und beide Zugangsdaten-Dateien sind bytegleich. Alle57 vorherigen
UNKNOWN-Tasks,8 UNKNOWN-Handoffs und24 unknown/blocked Messagejobs sind vollständige
Zeilenhashgleich. Originale Terminalfenster und Shell-/Codex-Prozesse erhalten,
Installer kehrte in die ursprüngliche Shell zurück. ThreadDesk-Discovery weiterhin
aktiv mit34 Werkzeugen. Werkzeugkatalog nach Versionswechsel frisch gelesen.

Sicherung/Logs/Artefakte/native Belege:
`~/.local/share/kirabridge/backups/closed-terminal-reservation-20261030/`.
Transaktionaler Rückweg zur vorherigen RC19:
`~/.local/share/kirabridge/install/backups/20261030-205600-1c16e539/`.
Keine Konfigurationsmigration und kein Datenbank-Restore. Strukturierter Nachtrag
im bestehenden JSON unter `closed_terminal_reuse_20261030`.
Kein main-Merge und kein neues öffentliches Release; breitere Plattform-/Hostabnahme
bleibt getrennt von dieser konkreten Fehlerbehebung.

## Historischer RC19-Stand vor der Korrektur für wiederverwendete TTYs

## Neuester Stand: konkrete globale Busy-Sperre behoben, installiert und erfolgreich getestet

Auftrag: dauerhaft sichtbare ChatGPT→Codex-Übergabe reparieren, laufende Sitzungen
schützen, im Team arbeiten, installieren/committen/pushen. Quelle:
`b3aaabaa55965c3d59497454cc2281b60b4865b4`, Branch
`fix/visible-busy-reservation-20261030`. Die früheren Abnahmesperren unten bleiben
historische Belege; der neue erfolgreiche Nutzerlauf wird separat vollständig bestätigt.
Kein main-Merge und kein neues öffentliches Release dieses Auftrags.

### Konkrete Ursache und begrenzte Korrektur

`codex_hello_20261030` adressierte ausdrücklich Terminal5527/ttys000/PID31668;
ein früherer Versuch adressierte5346/PID27237. Beide wurden dennoch durch die alte
UNKNOWN-Reservierung `codex-kirabridge-install-20261030-1712` für **3033/ttys001/
Shell70676/Agent71896** blockiert. Der Guard scannte global nach Agentenname codex.
Die vorhandene Ausnahme für unabhängig identifizierte Terminals galt nur für
Paste ohne Return, nicht für `submit=True`.

`visible_handoff.py` führt nun explizite Caller-Provenienz bis zum Guard. Die Ausnahme
gilt ausschließlich für eine andere Task-ID, ursprünglichen Zustand UNKNOWN und
eine eindeutig andere native Ressource: andere Fenster-ID UND TTY, disjunkte Shell-/
Agent-PIDs, taskgebundene UID/Startzeit/Image/Parent-Identitäten und erneut positive
Bereitschaft. Aktive Reservierungen, gleiche Pane/TTY/Fenster/PIDs, alte IDs und
unbestätigte Identitäten bleiben geschützt. Default-Agent-Routing wird nicht auf
einen anderen Tab umgebogen. Alte Zeile, Nachricht, Events und Defaultbindung bleiben
unverändert; keine Bereinigung, automatische Wiederholung oder falsche Erfolgsmeldung.

Zusätzlich korrigiert `platform_adapters/terminal_app.py` den belegten alten
Ansichtsfehler. Apples lokale Terminal.sdef beschreibt contents als sichtbaren
Ausschnitt und history als gesamten Scrollpuffer. Pythonread, nativer Preinput-/
Return-Guard und Paste-Beobachtung verwenden jetzt durchgehend denselben aktuellen
begrenzten History-Tail. Kein bedingter Fallback, Trimmen, Scrollen oder Löschen;
Identitäts-/Fokusprüfungen bleiben erhalten. Getestet sind auch aktuelle echte Eingabe
bei alter leerer Ansicht, Änderung vor Transport, mehrere Tabs/TTYs und Unicode-Grenzen.

Geänderte Produktdateien: `visible_handoff.py`, `terminal_app.py`. Tests:
`test_visible_handoff_reservation_scope.py`, `test_terminal_current_buffer.py` und
angepasste `test_visible_selection.py`. Gegenbeispiele scheiterten am Originalcode.
Danach **155** verwandte Reservierungs-/Handoff-/Selection-/Admissiontests und
**80** native verwandte Tests bestanden; der portabel angepasste Unicode-Fall danach
einzeln bestanden. Überlappende Tests nicht addieren. Ruff/Format405Dateien,
Diffprüfung und unabhängige gegenseitige Review bestanden. Keine Gesamtsuite wiederholt.

### Gebaut, tatsächlich installiert und im Betrieb geprüft

Nativer Swift/Cocoa/WebKit-Intel-Build mit strenger ad-hoc-Signaturprüfung und
quellgebundenes Paket aus exaktb3aaaba gebaut. Bekannte WebKit-Warnung dokumentiert,
Compiler Exit0. Vollständige vorherige RC19-Installation/venv, App, Dienste,
Konfiguration, Zugangsdaten und konsistente SQLite-Sicherung vorab rückgeprüft.
Aktivierung durch vorhandenen transaktionalen Installer mit sichtbarer TTY-Prüfung
im eigenen Fenster5621/ttys002/Shell36619. Nur eigene KiraBridge-App/Console
kontrolliert ersetzt, keine fremden Agenten gestoppt.

Installiert: **0.8.0rc19 aus b3aaaba**, `~/Applications/KiraBridge.app` (PID36721),
CorePID36706; Dienstpfad
`~/.local/share/kirabridge/install/releases/0.8.0rc19-b3aaabaa5596/`.
Alle122 Pythondateien wheelgleich; Live-Quellhash
`22c2933b005b649fb3b4f6e7a16c998c9ba28ebdd9d3b94d39455c24f52ecf7f`.
Konfiguration und beide Zugangsdaten-Dateien **bytegleich**; Konfigurationshash
`0dc8eb5952fe4d986c152d38e1658e06de711d6b1f91ccc9745b184d1adb6370`.
ThreadDesk-Discovery bleibt aktiv mit34Tools. Keine Konfigurationsmigration nötig.

Eigene echte Codex-CLI0.165.0 wurde sichtbar als Kind der eigenen Shell gestartet,
`--no-daemon --no-alt-screen -s read-only -a never`, keine Modellüberschreibung.
Der beobachtete Update-Dialog wurde nur in dieser eigenen Sitzung mit Esc übersprungen;
kein Codex-Update und keine globale Trust-/Berechtigungsänderung. Ein Fehler im
privaten Starter vor jeglicher Übermittlung (Datenverzeichnis statt SQLite-Datei)
wurde korrigiert; danach Startertask completed/attempt1. Keine unsichere ID wiederholt.

**Vollständig erfolgreicher tatsächlicher ChatGPT-Nutzerlauf:**
`hello_codex_free_20261030_second`, Ziel5527/31668, Task UND Handoff completed,
Versuch1, authentifizierte Empfangsquittung und genau eine Abschlussantwort.
Der Nutzer bestätigte die vollständig eingefügte Übergabe ausdrücklich. Dies ist
ein vollständiger erfolgreicher Lauf, keine bloße Annahme oder Return-Behauptung.

Die zusätzliche Wiederholung wurde vor dem Senden gestoppt: aktuelle Viewport- UND
Bufferprüfung übereinstimmend scrolled/input_empty=true/ready=false. Kein neuer
Testauftrag angelegt, keine Schutzprüfung umgangen; der bereits vollständige Lauf
bleibt als Abnahme erhalten.

**Getrennter eigener Hilfstest:** `busy-owned-codex-20261030-v1` wurde einmal in
5621 eingefügt, Return einmal gesendet, authentifiziertes ACK empfangen. Der Nutzer
schloss die Sitzung vor ihrer Abschlussantwort. Diese alte ID bleibt UNKNOWN ohne
Replay; sie wird nicht mit dem vollständig erfolgreichen neuen Nutzerlauf verwechselt.

Nach Zwischenablage-Warnung sofort alle Live-Eingaben gestoppt, keine Zwischenablage
ausgelesen. Die einzig betroffene eigene Codex-Rolloutdatei belegt den empfangenen
Userturn **exakt1298Zeichen, SHA256
`12bcca01cf66a49f0f12b95c973785b11cd6a344982314ff87eb3f7e6ab66e36`**,
identisch zum vollständigen autorisierten Prompt, **0 zusätzliche Zeichen**.
Der erste andere Userturn ist nachweislich Fixture-/Umgebungskontext, kein Beleg
für alten Clipboardtext. Dieselbe eigene Rolloutdatei enthält Receive/ACK für die
exakte Nachricht und Quittung; nicht bloß gemeinsame principalcodex-Attribution.
Der Nutzer bestätigte anschließend ebenfalls erfolgreiche vollständige Einfügung.

Offline gefundene Grenzen einer reinen gefalteten Zeichenanzahlbeobachtung werden
separat festgehalten, beweisen aber keine falsche Clipboardzustellung in diesem
Lauf. Es wurde weder die Clipboardlesung wiederholt noch der Transport durch eine
funktional sperrende hypothetische Änderung erweitert. Der Volltextbeleg dieses
Laufs stammt aus dem tatsächlichen Rollout; nicht aus Zeichenanzahl allein.

### Erhalt und Rückweg

Alle **55** vorab geschützten UNKNOWN-Tasks, **24** unknown/blocked Messagejobs und
**7** UNKNOWN-Handoffs zeilenhashgleich. Alle drei ursprünglichen Terminalansichten
3033/5346/5527 und sechs Shell-/Codex-Prozessidentitäten unverändert. Das eigene
Fenster und seine beiden Prozesse wurden nach der Nutzer-Schließung unabhängig
abwesend bestätigt; kein weiteres Fenster geöffnet oder fremder Tab angesprochen.

Private Sicherung/Hashes/Artefakte, ursprünglicher DB-Snapshot, Code-/Testbelege:
`~/.local/share/kirabridge/backups/visible-busy-reservation-20261030/`.
Transaktionaler Rückweg zur vorherigen RC19-Quelle8538ec8:
`~/.local/share/kirabridge/install/backups/20261030-194109-1b8cad4f/`.
Diese vorherige RC19 versteht dieselbe Konfiguration; keine Flagänderung bei diesem
Update. Frühere RC18-/RC17-Rückwege bleiben erhalten. Kein produktiver Rollback und
keine Datenbankrestaurierung. Source-/App- und Config-Hashes unterscheiden tatsächliche
Installation eindeutig von anderen Builds mit gleicher RC19-Versionsnummer.

Strukturierte Belege im bestehenden JSON unter `visible_busy_reservation_20261030`.
Push erfolgt auf dem neuen isolierten Branch und nur bei unverändertem/abstammendem
Remote per Fast-forward im vorhandenen PR54-Branch; kein Forcepush oder main-Merge.

## Historische Stände vor der gezielten Busy-Reservierungskorrektur

## Neuester Stand: RC19 installiert, Terminal-Live-Gate fehlgeschlagen, kein Release

Der neue Teamauftrag verlangt gezielte Reparatur von Terminal und ThreadDesk-Discovery.
Der folgende ausdrückliche Auftrag beschränkt die Fortsetzung auf Build/Installation/
Live-Abnahme, ohne neue Entwicklungsrunde oder unnötige Wiederholungstests. Push und
Release sind an erfolgreiche Abnahme gebunden; bei Kernfehler soll kein fertiges Release
erscheinen. Daher **kein RC19-Release, kein neuer Download-/Installationsbefehl als
funktionierend ausgegeben und kein Push des Kandidaten**. Der vorhandene README-Befehl
bleibt beim tatsächlich veröffentlichten RC18. Neue lokale Quelle:
`8538ec80744de9f90821c9bbe763179d7a54fb75`, Branch
`fix/terminal-dynamic-tools-20261030`, Version `0.8.0rc19`.
Ein lokaler Commit vor dem Build war für den bestehenden quellgebundenen Builder nötig.

### Vorbereitete Fehlerkorrekturen und Prüfungen

Codex verwendet im laufenden Turn den Composer-Marker **» U+00BB**, während
abgeschickte alte Texte **› U+203A** behalten. Der bisherige Parser fand nur › und
klassifizierte damit alten Text als aktuelle Eingabe. Aktuelle Aufnahmen3033/3206
belegen das;3546 war im früheren Beobachtungszeitpunkt tatsächlich bereit.
Der neue Parser erkennt den aktuellen »-Composer. Leer während laufender Arbeit
bleibt **working und nicht ready**; vorhandener Text und widersprüchlicher Zustand
bleiben geschützt. Die Regex-Escape-Vermutung wurde durch direkte Prüfung widerlegt.

ThreadDesk war konfiguriert, aber `dynamic_read_proxy` fehlte, also Defaultfalse.
Zusätzlich konnten bisher nur explizit lesende Tools weitergereicht werden. Der neue
explizite `dynamic_tool_proxy` ermöglicht alle angebotenen und aktuell autorisierten
Tools mit frischer Schema-/Berechtigungsprüfung. Mutationen verlangen stabile IDs,
dauerhafte Tasks und Vertragsprüfung; verlorene/fehlerhafte Antworten nach möglichem
Effekt bleiben UNKNOWN ohne Replay. Eine erhaltene Antwort ist keine allgemeine
Effektbestätigung. Kein ThreadDesk-Nachbau und keine Änderung seiner Codex-Sitzung.
Die konfigurierte gepinnte ThreadDesk-MCP-Quelle770bbc9 bietet34 Tools an; dies ist
keine Behauptung über alle uncommitteten Funktionen des getrennten ThreadDesk-Projekts.
Research Monitor unter `/Users/landjunge/KiraBridge-Test-Monitor` liefert vorhandene
Ressourcenmessungen, keinen Beweis einer Terminal-/MCP-Ursache; kein neuer Messloop.

Code: `visible_readiness.py`, `threaddesk_dynamic.py`, Config/Modelle/Operations/
Bridge und MCP-Server/Proxy. Gezielte Regressionen liegen in den vorhandenen Tests
sowie `test_codex_queue_widget.py` und `test_threaddesk_dynamic_lifecycle.py`.
Codex-Verwandte151 bestanden; zusätzliche Route/Readiness54, davon52 überlappend.
Dynamic31 Unitfälle und6 eindeutige Lifecyclefälle bestanden; kein behaupteter
abschließender gemeinsamer37er-Lauf. MCP/Berechtigung/Readiness50 bestanden.
Ruff/Format403Dateien und Diffprüfung bestanden. **Keine Gesamtsuite wiederholt.**

### Tatsächlicher Build und kontrollierte Installation

Native Swift/Cocoa/WebKit-App und vollständiges vorhandenes Dienstpaket aus exakt
8538ec8 gebaut. x86_64-Mach-O, strenge ad-hoc-Signaturprüfung bestanden; bekannte
WebKit-Concurrency-Warnung, Compiler Exit0. Keine Notarisierung oder ARM-Abnahme.

| Artefakt | SHA256 |
| --- | --- |
| KiraBridge-macos.tar.gz | `e1ff2174924ffd04c3b609731db874b8a8865f9eb26c79877a358040b468ed0a` |
| kirabridge-0.8.0rc19-py3-none-any.whl | `1bbff209abbddc9444e51f9a4351032f3c943231d854dac774f5af507d7f931e` |
| App-Binärdatei | `dce17d25620a636006ec95e5ea3dc34cdabff8815dd3556821f54569689a74ad` |

Vorher vollständige aktuelle RC18-Laufzeit/venv, App, Konfiguration, Schlüssel,
Dienstdefinitionen und konsistente SQLite-Sicherung lokal erstellt und rückgeprüft.
Nur eindeutig eigene AppPID20022 und ConsolePID20033 kontrolliert beendet; keine
Eingabe oder Stop-Anweisung an andere Codex-Sitzungen. Der vorhandene transaktionale
Installer lief in eigenem bestätigten sichtbaren Terminal5358/ttys004/PID28934 mit
`--require-visible-terminal`. Erst RC19 mit originalkompatibler Konfiguration aktiviert,
danach ausschließlich die beiden Discovery-Flags unter Hash-/Inode-Prüfung ergänzt,
Core mit bestehenden Ownership-/Idle-Guards gestoppt und neu gestartet. Beide
Dienstdefinitionen und App stammen aus der neuen Runtime. Keine Sicherheitsrechte
umgangen; Zugangsdaten unverändert.

Installiert: **RC19-Kandidat**, `~/Applications/KiraBridge.app`, AppPID29090,
CorePID29067, ConsolePID29114. Dienstpfad:
`~/.local/share/kirabridge/install/releases/0.8.0rc19-8538ec80744d/`.
Alle122 Pythondateien entsprechen dem gebauten Wheel. Live-Quellhash
`31765b83324db2ac4276a037ffbee372c6e300bfcb25d2e957c3888d9ec16942`.
Konfiguration nach exakt den eigenen Flags:
`0dc8eb5952fe4d986c152d38e1658e06de711d6b1f91ccc9745b184d1adb6370`.
Ein kritischer Installationsfehler hätte den gesicherten Rückweg ausgelöst; produktiver
Rollback war nicht nötig. Die sichere Terminalablehnung ist kein Ausführungsbeleg.

### Echte Live-Abnahme: ein Gate bestanden, ein Gate nicht bestanden

**ThreadDesk PASS:** echte authentifizierte HTTP-MCP-Verbindung als chatgpt,67 Tools
am Bridge-Endpunkt. Dynamiccatalog enabled=true/modeauthorized_tools, **34 angebotene
Schemas vollständig mit der konfigurierten Quelle abgeglichen** (12 lesende/22
konservativ mutierende). Ein schema-validierter echter `get_thread(id188ce4729a62)`
lieferte erwartete ID, Titel, Revision439 und Status; unabhängig gegen Threaddatei
geprüft. Thread und aktive Threadzustandsdatei bytegleich, kein Umschalten.
Weiterer frischer Katalog identisch; Flags sind dauerhaft in der Konfiguration und
nach dem tatsächlichen RC19-Neustart geladen. Keine Live-Mutation aller22 Tools
behauptet; deren Wiederholungs-/Timeout-/Restart-Schutz ist gezielt regressionsgeprüft.
Katalogschemahash `cd6f3adf91d24a66a0547eb6632a26a30f3ed300f065a2b2912228cd02959336`.

**Terminal FAILED vor Dispatch:** nach reinem Fokusieren des eigenen bestätigten
Fensters verweigerte `prepare_shell_paste` mit `visible_input_not_empty`. Es wurde
kein Task `rc19-installed-e2e-20261030` angelegt, kein Text eingefügt, kein Return
und kein Testpayload ausgeführt. Keine Wiederholung oder Umgehung vorgenommen.
Reine anschließende Leseprüfung im selben eigenen Fenster belegt:

- `tab.contents()`:2014 Zeichen, älterer Installationsausschnitt, keine kontrollierte
  Promptzeile; endet in einer Abhängigkeitsausgabe. Predicatefalse.
- `tab.history()`:3434 Zeichen, endet in der aktuellen exakten leeren kontrollierten
  Promptzeile; Predicatetrue.

Dies ist ein belegter Unterschied der gelesenen Darstellungen/Ansichten. Der
bestehende Vorprüfpfad verwendet `contents()`, also wurde die tatsächliche sichtbare
Einfüge-/Return-/Ergebnisstrecke nicht abgenommen. Keine erfolgreiche Ausführung aus
Shell-Idle, Fokus oder leerer History abgeleitet. Kein weiterer Quellfix, kein neuer
Testloop und **kein fertiges Release gemäß ausdrücklicher Betreiberbedingung**.
Nächster eng begrenzter Entwicklungsbedarf wäre ein konsistenter aktueller
Ansichts-/Inputnachweis in Python UND nativer Transportprüfung; kein blindes Trimmen
oder bloßer History-Fallback. Dies wurde in diesem Abschlusslauf nicht implementiert.

### Erhalt, Rückweg und Git-Status

Eigenes Fenster nur nach erneut stabiler aktueller leerer History und bestätigter
Shell-only-/PID-/TTY-Identität geschlossen und unabhängig abwesend geprüft. Während
des Laufs verschwanden ursprüngliche fremde Ansichten5342/5344 samt Prozessen vor
unserem Close; Verursacher nicht belegt. Deshalb kein pauschaler Nachweis des gesamten
ursprünglichen Inventarerhalts. Die unmittelbar vor unserem Close vorhandenen
anderen Ansichten3033/5346 und ihre vier Prozessidentitäten blieben dabei erhalten.
Keine Aktion an verschwundene fremde Fenster gerichtet. **55unknownTasks,
24unknown/blockedJobs und7unknownHandoffs vollständig zeilenhashgleich.**

Private Sicherung/Artefakte/Installationssteuerung und getrennte Live-Belege:
`~/.local/share/kirabridge/backups/terminal-dynamic-tools-20261030/`.
Transaktionaler RC18-Rückweg:
`~/.local/share/kirabridge/install/backups/20261030-185924-0015dd2e/`.
Die alte RC18-Definition verwirft das neue Feld `dynamic_tool_proxy`: **vor Start
der alten Runtime ausschließlich die eigene Deltaänderung mit dem hashgebundenen
CONFIG_REVERT.py zurücknehmen**, dann den passenden vorhandenen Installer-Rollback
im bestätigten eigenen Terminal nutzen. Bei fremden Änderungen abbruch statt
Überschreiben; App/Console separat aus gesicherter eigener Definition zurückführen.
Keine Datenbank restaurieren. RC17-Rückweg bleibt vorhanden. Ein tatsächlicher
produktiver Rollback wurde nicht durchgeführt und nicht als bestanden ausgegeben.

Der Kandidat bleibt lokal installiert und geschützt ablehnend; ThreadDesk funktioniert.
Release-Link: **keiner**, RC19 nicht veröffentlicht. Neuer Ein-Befehl-Download nicht
als funktionierend ausgegeben. Lokale Build-/Belegcommits werden wegen fehlender
vollständiger Abnahme nicht als fertiger Stand nach GitHub gepusht. Kein main-Merge.
Strukturierter Nachtrag im bestehenden JSON unter `terminal_dynamic_rc19_20261030`.

## Historische Stände vor dem RC19-Abschlusslauf

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

### GitHub-CI auf dem tatsächlichen Produktcommit

[Verify41090776653](https://github.com/landjunge/KiraBridge/actions/runs/41090776653)
auf exakt4a2d32f: Linux3.11/3.13 jeweils **1889 bestanden, 24 übersprungen**,
Ruff/Format/Build grün. Gesamtstatus trotzdem **failure**: beide Hosted-Mac-Jobs
(Intel/ARM) starteten mit0Schritten wegen Kontozahlung/Ausgabenlimit nicht.
Kein manueller Hosted-Rerun, keine Billingänderung und kein bestandenes Plattformgate.
Der spätere reine Dokumentationsstand ändert die getestete/installierte Quelle nicht.

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
