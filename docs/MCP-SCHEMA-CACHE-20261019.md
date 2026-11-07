# Korrigierte Events-Anbindung: aktiviert, echter Chatempfang offen

Stand 19.10.2026. Die korrigierte optionale Events-Fassade wurde erneut kontrolliert
aktiviert. Der Auftrag ist bezüglich tatsächlichem Empfang im ursprünglichen Chat
**nicht erfüllt**.

## Änderungen und Betrieb

Die Fassade reicht die bestehenden Schemas von `task_request` und `task_submit`
unverändert weiter. Normale Aufträge benötigen kein Abonnement. Für expliziten
Chat-Push wird das bestehende Feld `completion_target=push:<echte-subscription-id>`
verwendet; Eigentümer, Task und bestätigtes Abonnement werden vor Einreichung
geprüft. Keine Subscription-ID wird lokal erfunden.

Der Sender prüft beim Start ausschließlich die Backend-Bereitschaft mit höchstens
sechs Versuchen innerhalb 25 Sekunden. Aufträge werden dabei nie wiederholt.
Die erste SQLite-Initialisierung ist zwischen Sender und Fassaden durch eine
auf fünf Sekunden begrenzte lokale Sperre geschützt.

Aktivierung unter `BEGIN IMMEDIATE`: 0 aktive Tasks, 0 Empfängerjobs. Bestehende
Tabellen und Auditpräfix unverändert. Hauptdienst PID 90003 wurde nicht neu gestartet;
Rechtekonfiguration blieb bytegleich. Die eigene Tunnel-Runtime wurde kontrolliert
neu verbunden; Sender PID 91516 läuft. Produktions-Discovery und echter App-Aufruf
`bridge_health` erfolgreich. Ein eigener Discovery-Probe beweist keinen Host-Rescan.

Privates Backup samt RECONNECT.txt und rollback.py:
`~/.config/kirabridge/chat-events-prepared-20261019/activation-20261019-02/`.
Rollback ausschließlich nach erneuter Leerlaufprüfung; keine Datenbank zurückspielen.

## Nachweise und Grenze

33 gezielte Tests bestanden (0,90 s). Schema-Gleichheit und normale Einreichungen
beider Task-Werkzeuge ohne Zusatzfeld sind lokal geprüft. Der dort verwendete
Host-Callback ist ausdrücklich Simulation und kein ChatGPT-Empfang.
[Maschinenlesbarer Stand](../examples/chat-events/cache-contract-20261019-01/validation.json),
[Produktions-Discovery](../examples/chat-events/cache-contract-20261019-01/production-discovery.json),
[Produktionskanal](../examples/chat-events/cache-contract-20261019-01/production-channel-status.json).

Tatsächlich weiterhin: **0 echte Subscriptions, 0 Zustellungen, 0 Chatquittierungen**.
Die verfügbaren Werkzeuge dieser Sitzung bieten weder Plugin-Rescan noch
Host-Subscription. Ein laufender Sender behebt diese Plattformgrenze nicht.

Im ursprünglichen Chat Work/Cloud beibehalten. Unter
[ChatGPT Plugins](https://chatgpt.com/plugins) → KiraBridge → Refresh / Rescan MCP server
muss der Host die aktualisierten Events-Metadaten erkennen. Danach im ursprünglichen
Chat anweisen:

> Abonniere kirabridge.task.completed für chat-events-receipt-20261019-01 in diesem Chat.
> Starte den vorbereiteten Test erst nach erfolgreicher Subscription und melde seinen
> Abschluss schriftlich hier. Verwende completion_target=push:<tatsächliche Subscription-ID>.

Falls `callback_host_not_allowed:<hostname>` erscheint, nur diesen tatsächlichen
Hostnamen zurückmelden. Der Host wird gezielt geprüft und zugelassen; weder URL
noch Signierschlüssel werden geraten. Der vorbereitete Terminaltest wurde nicht
vor einer echten Subscription gestartet.

## Separates Cacheproblem

Die bisherige ChatGPT-Werkzeugbindung fordert noch das alte Pflichtfeld
`completion_subscription`, obwohl das aktuelle Serverschema es nicht enthält.
Die Ursache im Adapter ist korrigiert und durch Regressionstests geschützt.
Das Leeren des Plattformcaches ist damit nicht nachgewiesen.
Die [offizielle Refresh-Anleitung](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata)
verlangt nach Refresh auch eine neue Unterhaltung für Werkzeugtests. Ein solcher
Test dient ausschließlich der Schemaprüfung und ersetzt niemals den Empfang im
ursprünglichen Chat. Keine globale Rechteänderung, Veröffentlichung oder Grok-Aufrufe.
