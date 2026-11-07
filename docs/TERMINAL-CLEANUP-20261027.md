# Terminalsteuerung, Phase 2: nativer Prozess-Cleanup · 27.10.2026

## Historie: bestätigter Stand vor dem neuen Cleanup-Fix

PR45 wurde regulär integriert: `1cc3d2470d246713fb5f5cef96beb54fbddd8296`.
Das finale Paket wurde reproduzierbar gebaut; neun finale Assets liegen im
RC17-Release-Entwurf, gebunden an diesen Quellstand. Keine Veröffentlichung behauptet.
Die tatsächliche sichtbare Mac-Installation bestand, antwortender Dienst PID1527.
Konfiguration, Credentials und Modi blieben erhalten. Rollback-Backup:
`~/.local/share/kirabridge/install/backups/20261027-051744-87a205e4`.
Vorherige Belege: Root-Worktree `terminal-control-20261027/dist/terminal-install-20261027`.

Die tatsächliche **deployed Paste-Abnahme ist nicht bestanden**: Der einmalige eigene
Auftrag `kb-terminal-installed-1cc3d247-paste-20261027-01` blieb über15Minuten
`accepted`, `started=null`, ohne Input-attempt-Marker, Resultat oder Fehler.
Der Heartbeat lebt. Das ist weder ein Erfolg noch ein belegter Ausführungsstopp.
Keine erneute Zustellung, kein Return, keine manuelle Umklassifizierung des Tasks.
Vier Runtime-Codehashes entsprechen dem geprüften Stand; daraus folgt kein
vollständiger Nachweis des aktuellen Coroutine-Warteorts.

Der normale Worker ist blockiert. Der bestehende Aktivierungs-/Restartschutz
würde bei diesem aktiven Auftrag mit `service_busy` verweigern (`operations_service.py:326–334`, `435–444`). Eine
vorhandene gezielte Stop-API für diesen Wartezustand ist nicht belegt. Dieser Guard
wird nicht durch direkte SQL-Zustandsänderung oder erzwungenen Dienstneustart umgangen.

## Enger reproduzierter Cleanup-Fehler und Beweisgrenze

Ein eigener isolierter Intel-Mac-Prozess mit256KiBAusgabe reproduzierte einen
Pipe-Cleanup-Fehler: Nach Kill war der Returncode bereits-9, aber bei pausiertem
65536Byte-Pipepuffer blieb `wait()` ausstehend. Das Leeren der Pipe löste diesen
isolierten Wartezustand in0,0018s. Diese Reproduktion passt zur Beobachtung einer
Daemon-Pipe ohne Kindprozesse, beweist jedoch **nicht**, dass der produktive Task
genau an dieser Stelle hängt. Keine erfundene abschließende Ursachenzuordnung.

## Zuständigkeit, Plan und offene Abnahme

A entwickelt einen gezielten PID-only-/Drain-Cleanup-Fix im eigenen Worktree
`native-reap-worker-20261027`; Root integriert separat in
`terminal-native-cleanup-20261027`. Cleanup muss begrenzt bleiben, nur den eigenen
nativen Hilfsprozess betreffen und Pipes bis zum bestätigten Abschluss behandeln.
Keine fremden Prozesse, Prozessgruppen, Terminalfenster oder Rechte verändern.
14 gezielte Cleanup-/Cancellation-/Fehlerklassenfälle sind inzwischen auf dem Intel-Mac
bestanden; genaue Befehle und ursprüngliche Fixturekorrekturen stehen im strukturierten
Beleg. Ein unabhängiger Sicherheitsreview bestätigt, dass ausschließlich das übergebene
eigene Prozess-Handle beendet wird und kein Gruppensignal im neuen Pfad vorkommt.
Integrierte Paketabnahme und produktive Recovery bleiben **offen**. Kein Produktivpatch
oder Restart durch diese Dokumentation.
Nur unmittelbar notwendige Prüfungen ausführen; fehlgeschlagene oder nicht gestartete
Gates nicht als bestanden ausgeben. Ein späterer Fix braucht Commit/Push, Review und
reguläre Integrationskontrollen sowie konkrete Paket-/Runtimebelege.

Das frühere eigene Fenster67312 wurde inzwischen durch externe zsh/grep-Arbeit
belegt und unangetastet gelassen. Das einmalige neue Installationsfenster68805 mit
eigener Shell1114 war frisch sichtbar bestätigt. Root beendet diesen eigenen
Zielkontext ausschließlich nach erneuter Eigentums-/Idle-/Identitätsprüfung, um
eine verspätete Zustellung dorthin zu verhindern. Das eigene Installationsfenster wurde nach dieser Prüfung geschlossen und seine
Abwesenheit unabhängig bestätigt; das alte beschäftigte Fenster67312 blieb erhalten.
Damit existiert kein gültiges ursprüngliches Eingabeziel des Prüfauftrags mehr.
Der Taskzustand wurde nicht verändert: Ein geschlossenes Ziel ist kein Beleg für
einen beendeten Dispatcher-Task.

## Arbeitsgedächtnis ohne neue Queuebelastung

Kanonisch bleibt Whiteboard188ce4729a62. Während der normale Worker bekannt blockiert
ist, keinen neuen gequeueten Whiteboard-Lese- oder Schreibauftrag einreichen.
Der vorhandene dynamische ThreadDesk-Zugang ist ausdrücklich read-only; er stellt
keine Manage-Freigabe oder Schreibschnittstelle bereit. Kein Erfassen fremder Tokens,
kein Aktivieren neuer Zugänge und kein Umgehen der Queue durch einen erfundenen
REST-/Direktpfad. Falls kein bestehender autorisierter Direkt-Schreibweg verfügbar
ist, den konkreten Speicherblocker lokal dauerhaft sichern und nach sicherer
Wiederherstellung des regulären Zugangs revisionsgebunden nachtragen.

Reader-/Hostzugang, Bibliotheksaufträge und ThreadDesk/Codex2/3-Entwicklung werden
nicht erneut gestartet. Historie, produktive Daten und bestehende Schutzprüfungen
bleiben erhalten.

## Historical English summary before recovery

PR45/main1cc3d247 was built reproducibly and installed visibly; RC17 remains a
release draft. The single deployed paste probe is stuck `accepted` without a start
or input-attempt marker. Deployed paste acceptance remains **unproven**. Do not
replay it, send Return, rewrite its state or bypass the `service_busy` guard.

A separate Intel-Mac subprocess reproduction proves a bounded-pipe cleanup deadlock
resolved by draining output. It does not establish the productive coroutine's exact
wait location. The narrow owned-process cleanup fix passed14 targeted Intel cases and an independent
security review; recovery and subsequent package acceptance remain pending. Do not enqueue further Whiteboard
jobs while the worker is blocked; preserve the checkpoint locally if no existing
authorized direct write interface is available.

## Umgesetzter interner Vertrag

`platform_adapters.reap_process(process, process_group=False)` beendet ausschließlich
sein zuvor selbst gestartetes Kindprozess-Handle, leert dessen stdout/stderr und wartet
innerhalb einer begrenzten Bereinigung. Auch ein bereits gesetzter Exitcode ersetzt
nicht die EOF-/Pipe-Bereinigung. Wiederholte Cancellation wartet diese begrenzte
Bereinigung ab und bleibt danach Cancellation. Der vorhandene Gruppenmodus ist
unverändert Standard; native macOS-Helfer wechseln weder Prozesssession noch TCC-Kontext.

Terminal.app, Desktopprobe, native PID-/TTY-Abfragen und tmux-Clientaufrufe verwenden
diesen Pfad. Lesefehler bleiben Fehler ohne erfundenen Eingabeversuch; möglicherweise
bereits mutierende Transporte bleiben ungewiss. Ein gesperrter/inaktiver Desktop wird
bei zusätzlichem Cleanupfehler nicht als verfügbar ausgegeben. Es werden weder fremde
Prozesse noch Terminal- oder Agentensitzungen signalisiert.

Testumfang: genau die betroffenen 14 Fälle, darunter ein einzelner eigener echter
Kindprozess mit höchstens256KiB, geteiltem Eltern-PGID und ausdrücklich verbotenem
`killpg`. Kein GUI-/Reader-Belastungstest und keine Wiederholung der47/21-Fälle aus
Phase1. Die obligatorischen GitHub-Prüfungen bleiben eigene Gates.


## Aktueller Abschlussstand: fde installiert, Fensterschluss offen

Dieser Abschnitt aktualisiert die oben erhaltene Historie; der1cc-Auftrag ist nicht
mehr `accepted`, sondern nach ausdrücklich beauftragter dienstbegrenzter Recovery
`unknown`/dispatcher_restart. Kein Replay, kein nachträglich erfundener Abschluss.
Die frühere35sHealthfrist blieb erfolglos; spätere unabhängige Reconciliation belegte
die Wiederherstellung und reguläres Abarbeiten wartender Aufgaben. Der normale
Whiteboardzugang war wieder nutzbar. Keine manuelle Task-/Queue-Zustandsänderung.

PR46 wurde regulär gemergt: `fde9d87a36ed6c0bdab4456c3c8812d0378d7fcd`.
Pflicht-Debian-CI auf PR und main: Python3.11/3.13 jeweils1683bestanden/16übersprungen;
Hosted-Mac-Jobs starteten wegen Billing nicht. Zwei finale Paketbuilds reproduzierbar,
375Manifestdateien verifiziert. macOS-Archiv-SHA256:
`f6907e87f4a7c388bfed99ecf7cbe22db186bdc0f61599653413fc2ac08ff890`.
Eigener tatsächlicher Intel-Warmtest1cc→fde→1cc mit Datenerhalt bestanden. Der finale
Einzeiler wurde zuvor isoliert geprüft; maßgeblicher Kopierbefehl steht in der README.

Finale Quellefde wurde im SELBEN eigenen sichtbaren Fenster69741/ttys003/Shell26485
installiert. Tatsächlich antwortender Dienst PID28646/RC17/fde, Config/Credentials
bewahrt. Backup `~/.local/share/kirabridge/install/backups/20261027-071536-a5943013`.
[Sanitierter Originalbeleg](evidence/native-cleanup-installed-fde9d87-20261027.json).

**Neue deployed Paste-Abnahme bestanden, begrenzter Umfang:**
`kb-terminal-installed-fde9d87-paste-20261027-01` completed einmal mit submit=false,
return_sent=false und execution_confirmed=false. Aktive Eingabezeile unabhängig exakt
1x zurückgelesen, keine Receiptdatei vor Return. Ein separater ausdrücklich ausgelöster
Return ergab16exakteBytes/SHA256
`bc5e5a02a36ccb902bfd4c5f914689332de26f0d13ee2948a9ece79a3b6e3a48`.
Eine Whole-screen-Harnessassertion und eine zu frühe Fileexists-Assertion scheiterten;
beide erhalten, vorhandenes Ergebnis anschließend nur lesend abgeglichen. Kein
zweites Einfügen oder Return. Kein Eingabenachweis in fremden Agentensitzungen oder
einer tatsächlichen ChatGPT-Sprachhost-Sitzung.

**Fenster erhalten / Entscheidung offen:** Nach der Quittung erschien der fremde
ungesendete Befehl `printf KIRABRIDGE_TEST_OK` am Prompt. `visible_input_not_empty`
blockiert korrekt das Schließen. Root fragte den Operator nach Erhalten (Standard)
oder ausschließlichem Schließen dieses Testfensters; keine Antwort als Zustimmung
behandeln. Keine Eingabe löschen/ausführen, kein Fenster-close-/Dienst-nach-diesem-
Fensterschluss-Pass behaupten. Der generelle launchd-Vertrag bleibt unabhängig von
Terminalfenstern; dieser konkrete Abschlussnachweis ist noch offen.

RC17 bleibt Release-Entwurf; keine Veröffentlichung. Keine ARM-/Hosted-Mac-Abnahme,
keine erneute Reader-/Hostdiagnose, keine fremde Queue-/Agenten-/Rechteänderung.

### Current outcome · English

Merged mainfde is actually installed, with reproducible final package, isolated
upgrade/rollback, preserved credentials/configuration and independently read runtime.
The new once-only deployed operator-MCP paste-only task completed with exact active-line
readback. Separate authorized Return produced the exact16-byte receipt; retained harness
failures were reconciled without repeating input. The historical1cc task remains unknown.

Own window69741 remains open because unrelated unsent input appeared after the receipt.
The guard refused closure; operator choice is pending. Neither window closure nor a
service-after-this-window-close result is claimed. RC17 is still a draft; ARM, hosted
Mac and actual voice-Host input are not accepted by this evidence.
