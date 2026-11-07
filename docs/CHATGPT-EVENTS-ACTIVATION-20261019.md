# Kontrollierte Aktivierung des ChatGPT-Ereignisanschlusses

**Aktueller Stand:** [Korrigierte Events-Anbindung erneut aktiviert; echter Empfang im ursprünglichen Chat weiterhin offen](MCP-SCHEMA-CACHE-20261019.md). Die nachfolgenden Betriebsstände sind historische Nachweise.

**Aktueller Vorrang:** [Events-Fassade zurückgerollt; ursprünglicher Anschluss wiederhergestellt](CHATGPT-EVENTS-RECOVERY-20261019.md).
Die nachfolgenden Aktivierungsangaben sind historisch. Vor erneuter Aktivierung
müssen Pflicht-Subscription für normale Aufträge und Sender-Startbereitschaft
korrigiert werden. Die App benötigt jetzt Refresh/Rescan der alten Werkzeugdefinition.

Stand 19.10.2026: **Der Produktionsanschluss ist aktiviert. Echter schriftlicher
Empfang im ursprünglichen Chat bleibt offen.** Kein simulierter Host wurde in
diesem Aktivierungsabschnitt verwendet. Keine Sprachausgabe, Veröffentlichung,
kostenpflichtige Dienstanlage oder Modell-/Grok-Ausführung.

## Tatsächlich ausgeführt

Projektregeln, [Ausbaudokument](CHATGPT-EVENTS-20261019.md), private Kandidaten und
laufende Aufträge wurden zuerst geprüft. Bestehende Änderungen und andere Projekte
blieben erhalten. Keine fremde Agentensitzung wurde übernommen oder beendet.

Die Umschaltung erfolgte unter `BEGIN IMMEDIATE` auf der bestehenden Datenbank:
**0 aktive Tasks und 0 queued/running Empfängerjobs**. Damit konnten während des
Profilwechsels keine neuen Tasks oder Nachrichtenjobs eingereiht werden. Die zwei
vorhandenen Tasks mit unbekanntem Ausgang und historischen Nachrichtenjobs wurden
weder neu gestartet noch umgedeutet.

Vor dem Wechsel wurden das originale private Profil, die Konfiguration und ein
konsistenter SQLite-Backup gesichert. Eine Wiederverbindungsanleitung wurde vor dem
Stop sichtbar ausgegeben und privat gespeichert. Nur die bestehende eigene native
Tunnel-Runtime wurde gestoppt und am gleichen Tunnel mit der vorbereiteten
Produktions-Fassade verbunden: PID **75523 → 84404**. Kein neuer Tunnel wurde
angelegt. Der Bridge-Hauptdienst blieb mit PID **80569** und derselben Instance-ID
in Betrieb; keine Bridge-/Agentenneustarts oder Änderungen an Rechten/Schlüsseln.

Der eigene dauerhafte LaunchAgent `com.kirabridge.chat-events` läuft mit PID
**84409**, bisher ohne Neustart und mit leerem stderr. Die Fassade nutzt
`serve.py --external-sender`, der separate Sender `serve.py --sender-only`.
Der Testadapter `check_protocol.py` steht in keiner Produktionsdefinition.

Elf Bestandsdatentabellen wurden unter der Schreibsperre vor/nach der Umschaltung
per Hash verglichen: alle identisch. Alter Auditpräfix und Konfigurationshash
blieben ebenfalls unverändert. [Aktivierungsbeleg](../examples/chat-events/activation-20261019-01/activation.json).

## Getrennte Abnahmestufen

| Stufe | Nachweis/Stand |
| --- | --- |
| Implementiert | Bereits zuvor gezielt geprüft; keine Wiederholung der Vollsuite |
| Aktiviert | Eigene native Runtime healthy/ready, neuer Sender läuft, Bestandsdaten erhalten |
| Produktions-Discovery | Echter aktivierter Produktionsbefehl beantwortet `server/discover`, `events/list`, `tools/list`; kein Callback und keine Ausführung |
| Host erkennt Anschluss | Tatsächlicher App-Statusaufruf funktioniert; native Same-Child-Metadaten nennen `KiraBridge Chat Events`, bislang Legacy-Initialisierung `2025-11-25` |
| Host erkennt Events-Katalog | **Noch nicht nachgewiesen**; privater Refresh/Rescan erforderlich |
| Echt abonniert | **Nein: 0 Subscriptions** beim dokumentierten Prüfzeitpunkt |
| Webhook zugestellt | **Nein** |
| Im ursprünglichen Chat schriftlich verarbeitet | **Nein** |

Der Operator-Discovery-Probe ist ausdrücklich gekennzeichnet. Seine zwei
Journalbeobachtungen `rpc_server_discover` und `rpc_events_list` werden nicht als
ChatGPT-Rescan ausgegeben. Die tatsächliche App-Verbindung konnte nach Umschaltung
weiter `bridge_health` lesen; ihre geladenen Werkzeugdefinitionen sind damit noch
nicht automatisch aktualisiert. Der weitergereichte Backend-Healthtext beschreibt
weiter den alten Completion-Consumer und ist keine neue Events-Zustellattestierung.

- [Aktive Produktions-Discovery](../examples/chat-events/activation-20261019-01/production-discovery.json)
- [Stufenprotokoll](../examples/chat-events/activation-20261019-01/stages.json)
- [Vorbereiteter kurzer Auftrag](../examples/chat-events/activation-20261019-01/final-task.request.json)
- [Ausstehende Plattformaktion zum Kopieren](../examples/chat-events/activation-20261019-01/HOST-ACTION.txt)

## Jetzt erforderliche Nutzeraktion im vorhandenen Anschluss

Für direkt verbundene private MCPs dokumentiert OpenAI:
[ChatGPT Plugins öffnen → Verbindung öffnen → Refresh](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata).
Die [Events-Dokumentation](https://developers.openai.com/plugins/build/mcp-events#test-in-chatgpt)
verlangt zusätzlich eine echte Subscription aus einem unterstützten Work-Chat und
den beobachteten Empfang des späteren Ereignisses.

1. **https://chatgpt.com/plugins → bestehende KiraBridge-Verbindung → Refresh**.
   Zeigt die Detailseite „Rescan MCP server“, diese Funktion verwenden. Keine neue
   App anlegen, keine Veröffentlichung und keine Schlüssel neu setzen. Anschließend
   prüfen, dass `kirabridge.task.completed` als Ereignis erscheint. Falls der Knopf
   fehlt oder der Scan scheitert, den tatsächlichen UI-Fehler zurückmelden.
2. Im **ursprünglichen auftraggebenden Chat** Work/Cloud verwenden, sofern dort
   angeboten, und für `task_id=chat-events-receipt-20261019-01` abonnieren lassen.
   Das Abonnement muss vom Host stammen. Der lokale Adapter erfindet weder dessen
   Callback noch Secret, Subscription-ID oder Chat-ID. Ein Ersatzchat wäre kein
   Nachweis für dieselbe ursprüngliche Unterhaltung.
3. Die Host-Callback-Allowlist ist weiterhin leer. Bei der ersten echten Anfrage
   wird `callback_host_not_allowed:<host>` zurückgegeben. Nur den Hostnamen
   zurückmelden; keine vollständige Callback-URL oder Signierschlüssel posten.
   Nach Prüfung dieses echten Hostwerts kann er in Sender und Fassade gezielt
   freigeschaltet und der Adapter im Leerlauf neu geladen werden. Danach muss die
   echte Challenge-Verifikation erfolgreich sein.
4. Erst mit verifizierter Subscription den vorbereiteten Auftrag einreichen;
   `completion_subscription` muss die echte ID enthalten. Der erlaubte vorhandene
   Python-Interpreter gibt ausschließlich
   `KIRABRIDGE_REAL_CHAT_RECEIPT_20261019_01` aus, Timeout fünf Sekunden, keine
   Datenleseoperation und kein Modellauftrag. Task und Idempotenzschlüssel sind
   `chat-events-receipt-20261019-01`. Der Auftrag ist bislang **nicht eingereicht**.
5. Assistententurn enden lassen. Die wirkliche spätere schriftliche Chatantwort
   anhand Task-ID, Event-/Subscription-ID und Inhalt abgleichen. Nur einen wirklich
   empfangenen Event-Token quittieren. Erst diese Stufe erfüllt die Gesamtabnahme.

Die verfügbaren verbundenen Plattformwerkzeuge wurden konkret durchsucht: Sie
bieten App-Berechtigungen lesen/ändern, Suche/Vorschläge und Deinstallation,
aber keinen Refresh/Rescan, keinen Host-Subscribe-Aufruf und keine Aktion zum
Starten eines Turns im Zielchat. Diese Funktionen werden nicht durch erfundene
API-Endpunkte oder Browser-Chat-Injektion ersetzt. Der Nutzer wurde bereits mit
dem konkreten vorhandenen UI-Pfad um den Plattformschritt gebeten.

## Wiederverbindung und Rückrollweg

Private Sicherung einschließlich ursprünglichem Profil:
`~/.config/kirabridge/chat-events-prepared-20261019/activation-20261019-01/`.
Dort liegen `RECONNECT.txt`, `rollback.py`, `tunnel-profile.before.json`,
`config.before.toml`, `bridge-before.sqlite3` und private Native-CLI-Protokolle.
Zugangsdaten werden nicht ausgegeben oder ins Repository kopiert.

```sh
tunnel-client runtimes status kirabridge --json
```

Bei erforderlichem Rückrollen ausschließlich im erneut geprüften Leerlauf:

```sh
/Users/landjunge/KiraBridge/.venv/bin/python \
  /Users/landjunge/.config/kirabridge/chat-events-prepared-20261019/activation-20261019-01/rollback.py
```

Das Rückrollskript prüft aktive Tasks/Empfängerjobs unter SQLite-Schreibsperre,
stoppt nur den eigenen Events-Sender und die eigene native Route und stellt den
alten Anschluss wieder her. Die Sender-LaunchAgent-Datei wird zur Sicherung
verschoben, damit sie beim nächsten Login nicht erneut startet. Das Ereignisjournal
bleibt erhalten. **Der Datenbank-Backup wird nicht in den laufenden Bestand
zurückgeschrieben**: spätere Arbeit darf nicht verworfen werden. Dieses Skript
wurde syntaktisch geprüft, nicht durch einen unnötigen zweiten Live-Wechsel getestet.

Die drei neuen Betriebs-/Prüfskripte bestanden Ruff, Format- und Syntaxprüfung;
`git diff --check` bestand. Der frühere lokale Simulationsumfang wurde nicht erneut
ausgeführt und zählt nicht als Beleg für diese noch offene Empfangsstufe.
