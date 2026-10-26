# RC17: Pager, Rückmeldungen und Diagnosebudget – 26.10.2026

## Tatsächlich geändert

Die vier bestehenden Fenster `terminal:47570:ttys000`, `terminal:50666:ttys003`,
`terminal:51079:ttys005` und `terminal:51447:ttys006` wurden frisch katalogisiert
und über KiraBridge gelesen. Jeweils genau ein `q` beendete ausschließlich den
bestätigten `less`-Pager. Vor jeder Eingabe wurden das genaue Fenster/Tab/TTY,
Shell-, Git- und Pager-PID einschließlich OS-Startidentität sowie die
Vordergrund-Prozessgruppe geprüft. Die native Terminalsteuerung prüfte den Fokus
erneut unmittelbar vor dem Zeichen. Kein Return, kein Signal, kein Git-Abbruch.
Alle vier Pager verschwanden; alle vier Shells blieben erhalten. Der anschließende
Bridge-Katalog meldete diese vier Fenster `busy=false`. Die vorhandenen drei
Codex-Prozesse 12657, 60136 und 45831 blieben erhalten; keine Sitzung wurde beendet.

Produktiv läuft weiterhin RC17 aus Quelle `012b592`; dieser Auftrag hat den Dienst
nicht ersetzt oder neu gestartet. Konfigurationshash blieb unverändert. Keine
Datei, Historie, Berechtigung oder Queue wurde gelöscht.

## Rückkanal: belegter Ablauf und Grenze

Native `action_request`/`task_request` benötigen kein Ereignisabo. Der tatsächlich
geladene ältere ChatGPT-Connector verlangt im Schema dagegen noch das Rootfeld
`completion_subscription`. Die Bridge akzeptiert dafür ausdrücklich `""` als
„kein Abo“. Der Live-Test über **diesen Connector als Identität chatgpt** bestand:

1. Eindeutiges `completion_target`, schreibfreier Testauftrag `agent.status`.
2. `task_request` mit `completion_subscription: ""`: angenommen/queued.
3. Tatsächliche Ausführung `completed`, separate Task-Rücklesung.
4. `completion_receive` lieferte die passende dauerhafte Notice.
5. Erst nach Verarbeitung `completion_ack` mit passender Quittung.

Auch der native Codex-Zugang bestand. Ein zusätzlicher tatsächlicher Loopback-MCP-
Test über dieselbe Client-Verbindung mit parallelem wartendem Consumer lieferte
Submission nach 0,281 s und die vollständige Rückmeldung nach 3,766 s. Nach Lesen
und Quittieren war dieser eigene Posteingang leer. Kein allgemeiner Bridge-Lock
für Longpolls ist damit nachgewiesen. Beim ersten Versuch über den Host-Tooltransport
kam die 20-s-Abfrage leer zurück, danach konnte die Notice gelesen werden; das
lokale Starten eines Promise beweist keine vorherige Registrierung beim Server.
Host-/Connector-Serialisierung bleibt eine mögliche, nicht bestätigte Ursache.

`subscription_states: {}` / `delivery_states: {}` beschreiben den **optionalen
Webhook-Kanal**, nicht die Funktionsfähigkeit des Completion-Posteingangs. Für ein
echtes `kirabridge.task.completed`-Hostabo sind eine vom aktuellen ChatGPT-Host
bereitgestellte Registrierung und ein verifizierter Callback notwendig. Diese
Werkzeuge/Callbackdaten sind dieser Codex-Sitzung nicht verfügbar; keine URL,
Subscription oder UI-Quittung wurde erfunden. `chat_ui_receipt_independently_verified`
bleibt **false**. Ein Toolresultat/Consumer-Ack beweist kein spontanes Aufwecken
eines inaktiven Chats. Für die aktuelle Sitzung einen eigenen stabilen Completion-
Target und einen Consumer verwenden; historische Default-Notices nicht pauschal
quittieren. Connector-Metadaten müssen im tatsächlichen ChatGPT-Client aktualisiert
werden; eine Serveränderung allein bestätigt keinen Client-Refresh.

## Warteschlangen: Fehler repariert, Unknown nicht umgedeutet

Der produktive Aufruf `queue_catalog` scheiterte tatsächlich mit `internal_error`.
Gezielte lesende Eingrenzung fand `team-work`: Dessen `result` ist laut Schema
nativer Text. Die allgemeine Queue-Ansicht versuchte ihn als JSON zu lesen. Das
blockierte bei Klartext sogar den Katalog anderer Queues und wandelte JSON-ähnlichen
Text unzulässig um. Der Patch in `queue_management/views.py` dekodiert nur die echten
JSON-Spalten und erhält Ergebnistext exakt. Fünf neue isolierte Fälle (Unicode,
leer, JSON-/zahlähnlich, abgeschlossene Historie) belegen Katalog, Paging/SHA,
Eigentumsprüfung und unveränderte Datenbank/Auditdaten. Alle fünf schlugen vor dem
Patch fehl und bestanden danach. **Noch nicht produktiv aktiviert.**

Die zugänglichen ChatGPT-Task-/Handoff-/Nachrichten-Queues wurden über ihre eigenen
APIs ausgelesen. Der konkrete Alttask `codex_threaddesk_sync_20261021_01` gehört zu
`chatgpt`; unter `codex` war er korrekt nicht sichtbar. Der authentifizierte
ChatGPT-Zugang zeigt RC11-Ursprung, `unknown`/`visible_reply_unknown` und bereits
`agent_confirmed=true`, letzte Beobachtung `confirmed`, aber keinen abschließenden
Ausführungsbeleg. Sein altes Fenster 22104/PID94023 ist nicht aktuell. Das beweist
keine unterbliebene Ausführung: **nicht erneut senden, löschen oder als beendet
markieren**. Auch der alte aktive Unknown-Handoff und wartende Nachrichten wurden
erhalten; eindeutige Verwaisung ist nicht belegt. Neue Diagnoseaufträge konnten
trotz dieser Historie tatsächlich ausgeführt werden. Keine pauschale Aussage,
dass alle historischen Agent-Zustellungen dadurch frei wären.

Aktuelle Codex-Fenster sind lesbar; die persistent konfigurierten Codex-/Grok-
Zielbindungen verweisen auf alte Fenster/PIDs. Im Katalog und OS-Prozessbild war
kein aktuelles sichtbares Grok-Terminal nachweisbar. „Executable vorhanden“ und
„Receiver konfiguriert“ sind kein erfolgreicher Agent-Handshake. Keine fremde
Codex-Sitzung wurde stellvertretend als Grok ausgewählt. Für neue Agent-Handoffs
sind tatsächlich gestartete, vom Operator zugeordnete aktuelle Fenster nötig.

## Auditlimit und notwendige Tests

Die 2.000/Tag betreffen optionale `diagnostic.*`-Traces; Kern-Audit und Task-/
Completion-Ereignisse bleiben getrennt erhalten. Allerdings kann fehlende Diagnose-
Aufzeichnung die entsprechende Readiness-Auskunft verschlechtern. Sekündliche
interne Proxy-Healthpolls erzeugten je zwei Diagnoseereignisse: ungefähr 2.000 in
16 Minuten 40 Sekunden je Proxy. Der begrenzte Patch in `mcp_gateway/client.py`
und `proxy.py` fasst nur unverändert erfolgreiche **interne** Polls zusammen.
Erster Erfolg, Verbindungs-/Versions-/Revisionswechsel, Fehler und explizite
Aufrufe bleiben erhalten. Kein Retry, kein Budgetanstieg, keine Historylöschung.
Details und die bewusst nachträgliche Klassifizierung solcher Routinepaare:
[Auditbericht](AUDIT-HEALTH-NOISE-20261026.md).

15 neue gezielte Fälle und vier direkt betroffene bestehende Regressionen bestanden;
hinzu kommen die fünf Queuefälle. Root prüfte beide Patches vor Integration und
Ruff/Format der fünf betroffenen Python-Dateien. Keine vorsorgliche lokale
Gesamtsuite, kein neues Installationspaket: getestet wurden die tatsächlichen
Änderungen und ihre Sicherheits-/Rückmeldeeffekte. Pflicht-CI bleibt bestehen.
Die Limits 2.000/Tag und 20.000 gesamt bleiben; bereits verlorene optionale Traces
werden nicht rekonstruiert. Dauerhafte Kapazitätsplanung braucht zusätzlich
autorisierten Export/Archivierung ohne Löschen der vorhandenen Historie.

## Offen und nächster Schritt

Quellcodefixes separat committen/pushen und PR-Prüfungen auswerten; kein Merge oder
Release ohne vereinbarte Gates. Danach geprüften integrierten Paketstand freigeben,
erst dann produktiv aktivieren. Intel-Runner-Konto und ARM-/GitHub-Billing-Hürden
aus PR39 bleiben eigenständig offen. Für vollständige Agent-Kommunikation zusätzlich
ein tatsächliches Grok-Fenster zuordnen und den ChatGPT-Hosttransport aktualisieren.

[Maschinenlesbare Live-Nachweise](evidence/rc17-live-diagnostics-20261026.json)
enthalten nur nötige Metadaten, keine Credentials, Originalauftragsinhalte oder
Rückmelde-Receipt-Tokens.
