# Queue- und Terminalstabilisierung · 29. Oktober 2026

Neuer ausdrücklicher Nutzerauftrag: Priorität 1 vor Masterplan und ThreadDesk-Aufräumen.
Ausgang `36a7c5c452eee8b94454ac78833f37855a9b3477`; Reparatur ausschließlich im
isolierten Worktree `queue-direct-admission-20261029`. Der laufende RC17 importiert
weiter aus `managed-message-route-20261028`, nicht aus diesem Reparaturworktree.
Kein produktiver Neustart, Restore, Merge, Release oder Deployment dieses Auftrags.

## Gesicherter tatsächlicher Zustand

Privates lokales Backup vor Änderungen:
`~/.local/share/kirabridge/backups/queue-priority1-20261029-201843`.
SQLite Online Backup, Quellarchiv, Git-Bundle, Index-/Worktreepatches, Untrackedarchiv
und private Konfigurations-/Credentialkopien. Manifest unabhängig zurückgelesen und
alle Hashes verglichen; SQLite `integrity_check=ok`, Git-Bundle verifiziert.
Kein produktiver Restore; Originaldaten und Dateirechte erhalten.

[Minimierter Zustandsbeleg](evidence/queue-priority1-20261029.json) enthält keine
Nachrichteninhalte, Tokens oder Credentials. Der konsistente Gesamtsnapshot enthält:

| Familie | Zustand |
| --- | --- |
| Tasks | 6.487 insgesamt; 5.971 completed, 463 failed, 46 unknown, 7 cancelled |
| Receiver-Jobs | 89 insgesamt; 50 completed, 14 failed, 14 unknown, 8 cancelled, 3 blocked; **0 queued/running** |
| Sichtbare Handoffs | 62 insgesamt; 54 completed, 3 interrupted, 3 unknown, 2 confirmed |

Die normale authentifizierte Codex-Ansicht ist enger: aktiv 1 unbekannter Task,
28 Nachrichten, 2 Handoffs und 90 Completionbenachrichtigungen. Teamarbeit,
Teamnachrichten, Sprachpuffer und Session-Input-Puffer sind dort leer.
Eine ungelesene Ergebnisnachricht oder Completion ist keine wartende Ausführung.
Separate Provider-/Webhook-Stores gehören nicht zu diesem Bridge-Store; passende
Event-Queue-Werkzeuge waren in diesem Toolkatalog nicht verfügbar. Kein behaupteter
Gesamtzustand fremder Providerqueues.

Bestätigte Terminalbindungen: Codex `terminal:3033:ttys001`, Shell70676/Agent71896;
Grok `terminal:2767:ttys000`, Shell45159/Agent45186. Zusätzlich existiert eine weitere
Codex-Sitzung `terminal:3206:ttys002`, Shell90001/Agent90216 mit eigener bestätigter
Übergabe `thread-cleanup-home-20261029-01`. Diese wurde weder übernommen noch gestört.
Read-only-Beobachtung: erster Codex tatsächlich working; Grok und zusätzlicher Codex
leerer aktueller Composer. Das ist OS-/UI-Beobachtung, keine kryptografische Identität
und keine Freigabe einer ungelösten früheren Reservierung.

## Ursache mit Belegen

1. `visible_target_busy` ist eine ungelöste Handoffreservierung für das Ziel,
   einschließlich geschützter unbekannter Eingaben. Das ist kein CWD-Fehler.
2. `session_selection_changed` bedeutet: kein exakt passendes aktuelles Pane-/PID-Paar.
   Beispiel `codex-thread-cleanup-manual-tab-20261029` verwendete ein inzwischen
   anderes Ziel. Das ist ein Schutz gegen Eingabe in eine falsche Sitzung.
3. `session_busy` verweigert den generischen Shellpfad ohne bestätigten Leerlauf.
   Ein laufendes Agentenprogramm darf nicht wie eine leere Shell behandelt werden.
4. Der bisherige MessageReceiver speichert bei `WAIT_REASONS` nur einen Wartegrund,
   lässt den Auftrag ohne Deadline queued und prüft alle zwei Sekunden erneut.
   Je Empfänger wird nur der älteste queued Auftrag gewählt. Andere Selectionfehler
   werden zunächst übergangen und erst nach unnötigem Claim im Ausführungspfad gemeldet.
5. `message_send` bestätigte nur Persistenz, ohne den Zustellversuch zu beobachten.
6. Ein normaler Taskworker wartet während einer sichtbaren Übergabe bis zur Antwort.
   Audit `codex-masterplan-answers-20261029-01`: created1793301148.632567,
   accepted1793301195.9721909, anschließend failed/visible_target_busy ohne started.
   Rund47s Queuewartezeit sind belegt; ein Arbeitsverzeichnisfehler ist nicht belegt.

Ein zusätzlicher statischer Readinessbefund bleibt getrennt: ungepinnte Codex-Turns
können durch historische Aktivitätswörter unknown werden. Das wurde hier nicht als
Ursache eines bestimmten Livefehlers ausgegeben und nicht durch schwächere Guards
umgangen.

## Was bereinigt wurde und was geschützt bleibt

**Keine historischen produktiven Einträge bereinigt.** Im Snapshot existiert kein
queued Receiver-Job. Die vorhandenen aktiv sichtbaren Einträge sind überwiegend
Inbox-Ergebnisse/Hinweise oder bereits begonnene/unklare Ausführungen. Es wurde kein
konkreter nie gestarteter aktiver Ausführungsblocker nachgewiesen, den zu entfernen
die Sicherheitssperre rechtfertigen würde. Kein SQL-Update produktiver Queues, kein
clear/restore/retire/withdraw/resume_unsent auf Verdacht.

Insbesondere bleiben `61ccf5a9-3f5c-46f4-8bb6-b5930e168a0d` unknown sowie
`ed182f06-b5cc-4841-8b8c-5ef5829a137e` und
`013a112e-b9fc-4271-b9ff-ebd19f279ac7` blocked/conversation_run_limit erhalten.
Die beiden blockierten Jobs sind bereits terminal und wurden nicht freigegeben.
Der historische Bibliotheksauftrag `dc52c315-b9d5-48c5-8de6-3fdf69970b9b` ist extern
quittiert/completed ohne Receiverclaim/start; daraus folgt kein Importbeleg und keine
Erlaubnis einer Wiederholung.

## Reparaturvertrag

- Neue sichtbare Nachrichten erhalten genau einen runtime-eigenen Zulassungsversuch.
  Der Sendeaufruf beobachtet erste belegte Zustellung oder den konkreten Fehler.
  Vorprüfung, Verbindung und erste Zustellung sind auf30s begrenzt; danach bleibt
  Antwortbeobachtung ein eigener bestehender Vorgang.
- Zielbindung wird mit den vorhandenen sicheren Refresh-/Abwesenheitsprüfungen
  ermittelt, kopiert und für diesen Versuch gepinnt. Kein Retarget auf beliebige
  lebende Codex-Tabs, keine Zielwahl nach CWD, kein unsichtbarer Ersatz.
- Empfänger-/Panebesitz verhindert Warteschlangen hinter einem laufenden Turn.
  Die vorhandenen Handoff-/Native-Identitäts-/Widgetprüfungen bleiben die letzte
  gemeinsame Eingabegrenze zwischen Message-, Task- und explizitem Pastepfad.
- Sicher vor Eingabe abgelehnte **neue eigene** Nachrichten erhalten atomar failed
  plus vorhandenen Zustell-Hold. Inhalt, Fehler und Idempotenzbeleg bleiben lesbar;
  vorhandene Holds werden nicht überschrieben. Unklare/gestartete Nachrichten
  erhalten dadurch keinen Hold und keine vermeintliche Stopbestätigung.
- Native Tasks werden nach Autorisierung exakt geclaimt und mit dem vorhandenen
  Executor/Preflight/Heartbeat ausgeführt. Lange Antwortwartezeit belegt keinen
  normalen Worker. Gleiches Ziel wird klar abgewiesen; verschiedene Ziele bleiben
  unabhängig. Der ChatGPT-Legacypfad terminal.execute wird ebenfalls berücksichtigt.
- Ein begrenzter Beobachter nimmt frische externe CLI-Freigaben aus demselben Store
  auf: nur neue Ereignisse nach dem aktuellen Runtimestart. Alte queued Einträge
  bleiben inert. Exactclaim prüft Felder, Ereignisse, Holds, Withdrawals und Handoffs.
- Gleicher Idempotenzschlüssel liest den Originalzustand, auch nach späterer
  Bereitschaft. Keine neue Zustellung durch Lesen, Reconnect oder Restart.
- Eingabeversuch, bestätigte Zustellung, ACK und fachlicher Abschluss sind getrennt.
  Nach möglicher Wirkung bleibt der Ausgang unknown; automatische Wiederholung und
  pauschales safe_to_retry sind für neue native Zulassung ausgeschaltet.
- Shutdown beendet nur eigene Beobachter. Sent-/confirmed-Handoffs bleiben bei
  abgebrochener Antwortbeobachtung erhalten. Bestehende ACK-/Late-Reply-Recovery
  kann nach Restart denselben Beleg abschließen, ohne Paste/Return zu wiederholen.
  Sehr früher Stop und abgebrochene Stopaufrufe hinterlassen keine unbesessenen
  Slots oder dauerhaft ungesetzten Warteereignisse; Restart öffnet nicht während Cleanup.
- Nach neuen MCP-Wartephasen werden Leserecht und Ownership frisch geprüft.

## Prüfung und verbleibende Gates

Gezielte private Tests benutzen synthetische Daten, ersetzte Terminaltransporte und
echtes Loopback-MCP. Keine Testeingabe in produktive Codex-/Grok-Sitzungen.
JUnit-Protokolle liegen beim privaten Backup; Läufe überlappen und werden nicht addiert.
Der unabhängige Review fand drei korrigierte Randfälle: Antwortwaiter-Cancellation,
Stop vor Coroutineeintritt und erneute Inboxsichtbarkeit abgelehnter Nachrichten.
Zusätzliche Raceprüfungen decken fremde Claims, Zielpinning, gemischte Message-/Task-
Handoffs, Callerabbruch, spätes ACK/Resultat und Rechteentzug während MCP-Wait ab.

Abschließende Testzahlen, Prüfhashes, Nachsicherung und Commit-/CI-Status werden im
bestehenden Arbeitsbericht ergänzt. Keine produktive Wirksamkeit dieses Kandidaten
behaupten: Installation und Neustart benötigen die ausdrücklich neue Freigabe.
Masterplan und ThreadDesk-Aufräumen bleiben bis dahin nachgeordnet.
