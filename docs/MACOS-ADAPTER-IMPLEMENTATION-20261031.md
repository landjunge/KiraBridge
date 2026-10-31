# Modulare macOS-Integration und getrennte Eingabewege

Stand 31.10.2026, Fortsetzung des Entwurfs `fa863a6` auf dem bestehenden
Branch `docs/macos-adapter-phases1-3-20261031`. Arbeitswhiteboard
`0ab8b95a7369`. Der Nutzer hat anschließend ausdrücklich Implementierung,
Fehlerkorrektur, Modultrennung und gemeinsame echte Integrationstests beauftragt.
Die frühere Begrenzung auf reine Analyse ist damit für diese Arbeiten aufgehoben.
Push, produktive Installation und Dienstneustart wurden nicht stillschweigend
freigegeben und in dieser Umsetzung nicht vorgenommen.

[Maschinenlesbare Quell-, Test- und Livebelege](evidence/macos-adapter-implementation-20261031.json).

## Tatsächlicher Ausgangsstand und Sicherung

Core weiterhin `ecb76cb2082a`, PID 15207, Start 11:25:14 UTC,
Startup-Quellhash `878e18a5970fc601a74bb67b32a6536151391d840e273d4335fc2d2d25cb6eb1`.
macOS 15.7.4/24G517, Intel iMac17,1. Vorhandene Return-/Installationsdokumentation
wurde wiederverwendet; der hier untersuchte neue Fehler wird von den früheren
Abnahmeergebnissen getrennt.

Private Ablage außerhalb des Worktrees:
`~/.local/share/kirabridge/backups/macos-implementation-20261031T121031Z/`.
Sie enthält `baseline-source.tar` von `fa863a6`, `failed-handoff.private.json`,
SHA256SUMS und RECOVERY.md. Historische Datenbank nur über SQLite `mode=ro`
gelesen. Rohprompts und Terminalbilder bleiben privat. Die ursprünglichen
produktiven Rollbackartefakte aus dem Entwurf bleiben erhalten.

## Drei unterschiedliche Fehlerklassen

### 1. Sichtbarer Paste, aber keine bestätigte Übergabe

`kb_macos_implementation_20261031` gehört dem Principal `chatgpt`; ein
Codex-`task_get` liefert deshalb erwartungsgemäß `not_found`. Die lokale
persistierte Folge lautet created → queued → accepted → running → unknown.
Error `visible_insert_unknown`, `return_sent=false`, `terminal_input_attempted=true`,
Attempt 1. Das ist weder eine Schemaabweisung noch ein Nachweis, dass Return
gesendet wurde. Der Folgeauftrag `kb_macos_continue_return_20261031` hat einen
eigenen Pasteversuch mit demselben Vergleichsproblem. Keiner wird erneut ausgeführt
oder nachträglich als erfolgreich umgeschrieben.

Die gespeicherte leere Voransicht `3a1d3b35032942cd86916a96896df269` vom Zeitpunkt
1793448221.299756 enthält unter der Modellzeile den Shortcut-Hinweis
`← for agents · ? for shortcuts`. Die Nachaufnahmen
`ff5297720bf3489dae9d0de3be3de74b` und `041a8dc6946040fbb6986a235a47b82b`
enthalten den passenden Pasteplatzhalter mit 1388 beziehungsweise 1022 Zeichen,
aber keinen Shortcut-Hinweis mehr. Der alte Verifier pinnt auch diese Zeile und
liefert für beide rekonstruierbaren Paare false; der korrigierte liefert true.

Beleggrenze: Die erste Voraufnahme liegt 58 Sekunden vor dem Task, die erste
Nachaufnahme etwa zehn Sekunden nach dem Fehler. Beim zweiten Task fehlt ein
eigenes leeres Vorbild. Das ist ein reproduzierter Vergleichsfehler an echten
Aufnahmen, keine Behauptung zeitgleicher interner Messung im alten Task.

Korrektur in `literal_session_input.py`: Ausschließlich die letzte exakte,
vorher vorhandene Hintzeile direkt unter der Modellzeile darf verschwinden.
Es werden keine Payloadzeilen und keine neuen Nachher-Footerzeilen abgeschnitten.
Die unveränderte und diese eng begrenzte Vorher-Variante durchlaufen denselben
strikten Vergleich und denselben bereits vorhandenen identitätsgebundenen
CWD-Beweis. Dadurch bleiben Warnbadge-/CWD-Elision und Hint-Ausblendung auch
gemeinsam unterstützt. Geänderter Modellname, fremde Footer, abweichende Payload,
falsche CWD und unbekannte UI bleiben gesperrt.

Neue bounded Task-Progressbelege enthalten Verifierversion, Vergleichsgrund,
Vorher-/Nachher-/Payload-SHA256 und Zeichenzahl. Bei Fehlschlag:
`insertion_unverified`, `return_sent=false`; keine Rohtexte und kein Replay.

### 2. Separater leerer Return-Aufruf: invalid_arguments

Der genaue historische Fehlaufruf ist nicht als Task oder Auditrecord vorhanden;
er wird nicht aus einem der beiden Unknown-Tasks erfunden. Das bisherige Schema
unterscheidet bereits explizit:

- Textmodus: nichtleerer `text`, optional `submit=false` für reines Einfügen.
- Returnmodus: `key="enter"`, leeres `text`, `submit=true`, frischer
  `expected_cursor` und die beobachtete Agentidentität.

Ein leerer Text ohne Modus oder `key="enter"` ohne Cursor ist ungültig und darf
keine Eingabe auslösen. Der neue sichtbare MCP-Einstieg `session_enter` nimmt
`task_id`, `idempotency_key`, `pane_id`, `expected_pid`, `expected_cursor` sowie
bei einem Agenten `expected_agent_pid` entgegen. Cursor und Agent-PID stammen
aus einem frischen `session_read`; der Server prüft das aktuelle Ziel erneut.
Der Einstieg erzeugt ausschließlich den vorhandenen `session.input`-Task mit
`key="enter"`. Es gibt weder eine zweite Enterimplementierung noch eine
automatische Umdeutung beliebiger leerer Texte. Die Fehlerantwort verweist nun
auf diesen eindeutigen Einstieg. Beide ungültigen Varianten werden getrennt
mit null Persistenz und null Eingabe geprüft.

### 3. Bereits vorbereiteter Approval-Task blieb created

Der neue echte isolierte HTTP-Test deckte einen unabhängigen Fehler auf:
`action_request(file.write)` → created → vertrauenswürdiger lokaler exakter
Grant → `task_submit(token)` ließ den Task unverändert in created.
`TaskManager.enqueue` behandelte im vorhandenen Taskzweig nur wartende
Sessioninput-Puffer als freigebbar.

Der bestehende Transaktionspfad konsumiert jetzt bei einem created-Task entweder
den bisherigen Input-Puffergrant oder den exakten normalen Securitygrant und
führt anschließend dieselbe Approvaltransition aus. Principal, Task-ID,
Requesthash, Completionroute und Accepting-Gate bleiben geprüft. Tokenloses
Duplikat bleibt wartend; ungültiges oder abgelaufenes Token verändert nichts;
queued/completed/unknown wird nicht neu ausgeführt. Keine Approvalentscheidung
wurde in Text-, Slash- oder Menülogik verschoben.

### 4. Im gemeinsamen Test entdeckter Slash-Rendererfall

Run06 belegte nach erfolgreichem Longprompt, echter Antwort und explizitem Enter
einen weiteren getrennten Vergleichsfehler bei `/resume`: Codex zeigt einen
einzelnen bekannten Vorschlagsrow und ergänzt nach der vollständigen CWD einen
Threadtitel. Diese Ansicht darf nicht durch eine pauschale Lockerung des normalen
Textverifiers freigegeben werden. Die Slashdomäne besitzt jetzt einen eigenen eng
gebundenen Verifier auf dem gemeinsamen Literaltransport; frische gleiche CWD vor
und nach Paste und tatsächlicher Titel des gebundenen Threads sind erforderlich.
Ein neues lesendes Blatt `platform_adapters/codex_metadata.py` liest ausschließlich
den Titel des bereits gebundenen Threads aus dem begrenzten, regulären,
eigentümergeprüften, stabilen JSONL-Index ohne Symlinkfolge. Genau eine bekannte
Vorschlagszeile und der unveränderte historische Bildschirmtext werden geprüft.
Der normale Textverifier erhält keine solche Lockerung. Die ursprüngliche
Unknown-Slashübergabe wird nicht wiederholt.

## Architektur und Zuständigkeiten

| Zuständigkeit | Modul / Wirkung |
| --- | --- |
| Plattformfakten | `platform_adapters/macos/capabilities.py`: OS-Version/Build/Architektur und vorhandene technische Blätter; passive Snapshotabfrage ohne GUI oder Rechteanforderung |
| OS-Berechtigungsbeobachtung | `macos/permissions.py`: explizite öffentliche Corechecks, normalisierte Zustände und Rohbefund, Prozess-/Zielbindung, Alterungsgrenze, threadsicherer Cache; keine Übertragung auf Helper |
| Provider / Registry / Dispatch | `macos/provider.py`: vorhandene Fachobjekte injizieren; `eligible_for_submission` getrennt von Approvalbedarf und OS-Zielprüfung; vor/nach wartender Revalidierung prüfen, vorhandenen Handler exakt einmal aufrufen |
| Zentrale Ausführung | `Bridge.execute` selektiert den Provider, `_execute_operation` bleibt der bisherige Fachdispatch mit Policy/Taskzuständen; native Terminalaufrufe besitzen zusätzlich denselben Providerguard |
| Tooldiscovery | vorhandenes MCP-/Operationsregister, Providerrevision in Discovery und Toolmetadaten; `macos_status`, generisches `platform.status` und gecachtes `read_query` erklären Fähigkeiten |
| Inputklassifikation | `session_input_router.py`: Text/Slash/observed Return routen; keine I/O oder Freigabeentscheidung |
| Textpaste + Submit | `literal_session_input.py`: bestehender gemeinsamer Paste-/Beobachtungs-/Returnpfad |
| Slash-Befehle | `slash_commands.py`: klassifizieren und denselben Literalexecutor nutzen; Folge-UI nicht automatisch bestätigen |
| Codex-Menüs | `codex_menu.py`: nur bekannte vollständig erkannte Resume-Menüs; getrennte Readiness; kein universelles Yes/Approval |
| Return ohne Paste | `session_return.py`: bestehende Cursor-/PID-/Bildbindung; Menübestätigung separat als `menu_confirmation`, normaler Return als `observed_return` |
| Approvals | bestehender Securitymanager, TaskManager, SessionInputPolicy und Operatoractions bleiben zuständig |

Dateien, Prozesse, Terminal, Desktopprobe und Clipboardlease wurden angebunden,
nicht kopiert. Die generischen Sessionwerkzeuge bleiben für tmux sichtbar,
wenn nur das native Terminalblatt fehlt; native Ziele werden bei Ausführung
geprüft. Inhaltsfreie Statuswerkzeuge bleiben erreichbar. Neue Capture-, Fenster-,
Notifications- und Preferencesprovider sind ausdrücklich nicht implementiert
und deaktiviert. Keine zusätzlichen Transportfallbacks, Queue oder Approvaldatenbank.

## macOS-Kompatibilität und Berechtigungen

Die Capabilitytests decken technische Varianten 12, 15 und neuere OS-Versionen
über injizierte Fakten ab; nur 15.7.4 ist hier real getestet. Mindestversion
der bestehenden Blätter ist im Provider als 12.0 modelliert, kein Nachweis einer
realen 12-/ARM-/26-/27-Abnahme. Bestehende Installerplattformgrenzen werden
nicht erweitert. Apples Hardwarefreigabe des iMac17,1 bleibt wie im Entwurf
von dem tatsächlich laufenden Sequoia getrennt.

Die expliziten Statuschecks verwenden ausschließlich
[AXIsProcessTrusted](https://developer.apple.com/documentation/applicationservices/1460720-axisprocesstrusted)
und [CGPreflightScreenCaptureAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess()).
Die öffentlichen lokalen macOS-12.1-SDK-Header bestätigen Current-process-Semantik,
AX-Verfügbarkeit ab 10.4 und CG-Preflight ab 10.15 sowie die Trennung von Request.
Keine TCC-Datenbank, keine Prompt-/Requestfunktion. Ein negativer AX-Boolwert
wird nicht als sicher unterscheidbarer denied/not_determined-Zustand erfunden.
Corefreigaben gelten nicht automatisch für osascript, pbpaste oder die App.
Vorhandene native Ziel-/Busy-/Fokus-/Clipboardguards bleiben erforderlich.

## Prüfung und reale Abnahme

Gemeinsamer Lauf der 21 unmittelbar betroffenen Testsuiten vor dem letzten Slashfix:
**426 passed in 25.22s**. Enthalten sind Provider-/Discovery-/HTTP-,
Literal-/CWD-/Return-/Menü-/Router-, Pending-Approval-, Security-/Permissions-,
Session-/Port-/Clipboard-/Readquery- und MCP-Regressionen. Keine Gesamtsuite
und keine zusätzlichen Wiederholungsschleifen nach unverändertem Erfolg.
Nach dem zusätzlich im echten Run06 gefundenen Slashfall bestand der abschließende
gemeinsame Lauf der neun davon berührten Suiten **230 passed in 8.58s**;
23 neue Slash-/Metadatenfälle sowie deren direkte Inputregressionen sind enthalten.
Die vorherigen 426 Fälle werden nicht als Lauf nach dieser letzten Korrektur
ausgegeben. Nach der letzten echten breiten Archiv-Menüvariante bestand der
gemeinsame Return-/Picker-/Routerlauf **84 passed in 2.90s**. Ruff und
Formatcheck der Änderungen sind grün; unabhängiges finales Review ohne neue
wesentliche Befunde. Testzahlen werden wegen überlappender Fälle nicht addiert.

Private reale Abnahme: `scripts/accept_macos_adapter_intel.py`, genau ein
gleichzeitig eigenes sichtbares Fenster, separate authentifizierte HTTP-Bridge
und Datenbank. Der Harness startet darin einen eigenen begrenzten Busyprozess
und einen eigenen Codex, erhält fremde Fenster/Prozesse und prüft Approval,
Schemafehler, stale PID, Prompt/Return, Completion, echte Antwort, Slash-Menü
und explizites Enter. Vor-/Nachbilder innerhalb des Tasks bleiben privat.
Maschinenlesbare Endergebnisse werden in der zugehörigen Evidence-Datei erfasst.

**Vollständige fachliche Kette inkrementell real bestätigt:** Run07 belegt
den 1694-Zeichen-Prompt, einmaligen Paste und Return, konsumierte Completion,
genau ein User-/Antwort-Item im eigenen Codex-Rollout plus sichtbare Antwort,
expliziten leeren Return ohne Paste und anschließend `/resume` mit
`input_kind=slash_command` und bestätigtem Return. Die tatsächliche breite
Archiv-Menüvariante wurde zunächst korrekt nicht bestätigt; der Run bleibt
deshalb als Gesamtversuch fehlgeschlagen erhalten.

Nach ihrem gezielten Parserfix wurde **im selben eigenen Fenster** fortgesetzt:
neue private HTTP-Instanz auf demselben Testzustand, frisch gelesener Cursor,
passende eigene Thread-/Titel-/CWD-/Prozessbelege und genau eine native
Menübestätigung (`menu_confirmation`, Return=true, Paste=false, Attempt1).
Die eigene gespeicherte Sitzung wurde wieder angezeigt. Kein Promptreplay.
Danach eigene Codex-/Shellprozesse beendet und Fensterabsenz sowie Erhalt der
anderen Fenster und aktuell belegten Prozessidentitäten unabhängig geprüft.
`native-e2e-07/menu-continuation-summary.json` weist dafür `acceptance=passed` aus.
Der letzte tatsächlich getestete Paketquellhash lautet
`e790665737fa910d99730f6f2a0a7ca5dec9511beebb3e1832d5a7e6e19077db`
für 132 Pythondateien und stimmt mit dem finalen Worktreequellstand überein.

Die exakte ursprüngliche Hintausblendung wurde im neuen einfachen Codex nicht
angezeigt (`old_verifier=true` und `new_verifier=true` für dessen Longprompt).
Dafür werden ausschließlich die historischen echten Frames mit false→true-
Replay und die Regressionstests als Nachweis angegeben. Der neue Slashfehler
wurde dagegen innerhalb des tatsächlichen Run06 direkt erfasst und behoben.

Frühe Harnessfehler bleiben als fehlgeschlagene Versuche erhalten: Run01
interpretierte `error:null` fälschlich als Fehler und stoppte vor jeder UIaktion.
Run02 behandelte die erwartete persistierte Busyabweisung fälschlich als
unzulässige Admissionresponse; sein eigenes Fenster wurde danach nachweislich
geschlossen. Run03 stellte Prompt und Return tatsächlich zu, wartete aber auf
veraltete `user_message/agent_message`-Rollouttypen; die aktuelle CLI schreibt
`item_completed` mit UserMessage/AgentMessage. Die echte Antwort war bereits im
Screen und im eigenen gebundenen Rollout vorhanden. Der Harness wird auf diese
strukturierten aktuellen Belege korrigiert; ein solcher Prüferfehler ist kein
nachträglicher positiver Gesamtabschluss des Runs.

## Offene Grenzen und nächste Freigabe

Die beiden ursprünglichen Bibliothekspläne und die Desktop-Commander-Recherche
bleiben fehlende Quellen; auf ausdrückliche Nutzersteuerung wurde deshalb keine
neue Architekturschleife begonnen. Clipboard-Symbole neuer SDKs und Ersatz für
die gekennzeichnete ioreg-Lockheuristik bleiben eigenständige optionale Arbeit.
Keine allgemeine Codex-Approvaldialogbedienung; unbekannte Dialoge bleiben gesperrt.
Kurze nicht kollabierte, visuell umgebrochene Mehrzeilentexte können weiterhin
als `visible_paste_unconfirmed` ohne Return enden. Run04 hat diese bestehende
Sicherheitsgrenze mit einem eigenen Setupdraft tatsächlich belegt; der Draft
wurde ausschließlich nach ausdrücklichem eigenem Cleanup, Identitäts- und
Bildprüfung verworfen. Kein Erfolg und kein Replay wird dafür behauptet.
Run05 erzeugte einen echten eigenen Testunteragenten, fand nach dessen Abschluss/
Schließen aber keine Agenten-Hintzeile. Er stoppte deshalb vor dem Hauptprompt.
Die exakte Hintausblendung ist mit historischen echten Frames belegt, nicht
als neu reproduzierte Liveanzeige ausgegeben.
Nach lokalem Commit und Paketprüfung ist eine produktive Installation mit
unterstütztem Upgrade/Rollback und nötigem Core-Neustart gesondert freizugeben.
Ohne diese Freigabe bleibt der produktive Core auf dem dokumentierten alten Stand.
