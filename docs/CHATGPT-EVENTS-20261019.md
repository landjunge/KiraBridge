# ChatGPT-Abschlussereignisse: lokal vorbereitet, Zielchat-Abnahme offen

**Aktueller Stand:** [Korrigierte Events-Anbindung erneut aktiviert; echter Empfang im ursprünglichen Chat weiterhin offen](MCP-SCHEMA-CACHE-20261019.md). Die nachfolgenden Betriebsstände sind historische Nachweise.

**Aktueller Vorrang:** [Events-Fassade zurückgerollt; ursprünglicher Anschluss wiederhergestellt](CHATGPT-EVENTS-RECOVERY-20261019.md).
Die nachfolgenden Aktivierungsangaben sind historisch. Vor erneuter Aktivierung
müssen Pflicht-Subscription für normale Aufträge und Sender-Startbereitschaft
korrigiert werden. Die App benötigt jetzt Refresh/Rescan der alten Werkzeugdefinition.

**Aktueller Betriebsstand:** [Kontrolliert aktiviert](CHATGPT-EVENTS-ACTIVATION-20261019.md).
Die nachfolgenden Angaben zur noch inaktiven Vorbereitung beschreiben den vorigen
Ausbauabschnitt. Sender und Produktionsprofil sind jetzt aktiv; echter Chatempfang
ist weiterhin nicht nachgewiesen.

Stand 19.10.2026. **Der Auftrag ist hinsichtlich tatsächlichem Chatempfang noch nicht
abgenommen.** Der bestehende aktive Completion-Consumer bleibt in Betrieb. Der neue
optionale Events-Anschluss ist implementiert und lokal geprüft, aber weder der
Produktions-Tunnel noch die App wurden umgestellt. Es gab keinen Dienstneustart,
keine Veröffentlichung und keinen Modell-/Grok-Aufruf in diesem Ausbauabschnitt.

## Ausgangsstand und verifizierter Plattformweg

Zuerst wurden Projektregeln, vorhandene Änderungen und
[COMPLETION-CHANNEL-20261019.md](COMPLETION-CHANNEL-20261019.md) geprüft.
Es gibt keine zusätzliche projektweite AGENTS.md; die vorhandenen AGENTS-Dateien
gehören ausschließlich zu früheren Demo-Arbeitsordnern. Bestehende Änderungen und
fremde Auftragsdokumente bleiben erhalten. Keine parallele Agentenbearbeitung.

Die aktuellen [offiziellen OpenAI-Unterlagen](https://developers.openai.com/plugins/build/mcp-events)
bestätigen MCP Events für Work auf Web bzw. Desktop mit Cloud und verlangen
Protokoll `2026-07-28`. Der Host abonniert im Zielchat und liefert Callback samt
Signierschlüssel. Ein HTTP-2xx bestätigt nur den Webhookempfang; der spätere
Chatturn benötigt eine gesonderte Beobachtung. Rescan und Subscription sind echte
Plattformschritte, kein gewöhnlicher Toolaufruf an einen erfundenen Chat-Endpunkt.

Die installierte App funktioniert, nutzt jedoch weiter SDK `mcp 1.30.0` und den
vorhandenen Stdio-Proxy mit Protokoll `2025-11-25`. Ihre geladene Toolbindung hat
keine Events-/Rescan-/Chat-Wake-up-Methode. Die read-only geprüfte App-Einstellung
lautet bereits **Allow all actions**. Das beweist weder Events-Verfügbarkeit im
konkreten Chat noch die Freigabe ereignisgesteuerter Tasks im Workspace.
Keine Rechte wurden geändert. Es liegt kein echter Host-Callback und keine
Zielchat-Subscription vor; diese Codex-Sitzung besitzt keinen API-Zugriff, um sie
im ursprünglichen ChatGPT-Chat anzulegen oder dessen App zu rescannen.

Der vorhandene `tunnel-client 0.0.16+5f99da…` kann die benötigten Methoden tatsächlich
weiterleiten: getestet mit seinem lokalen `dev proxy`, In-Memory-Control-Plane,
dem neuen Adapter und einem isolierten echten Bridge-HTTP-Backend. Kein neuer
gehosteter Tunnel und kein bezahlter Dienst wurden erstellt.
[Umgebungsbeleg](../examples/chat-events/run-20261019-01/environment.json).

## Konkrete Implementierung

- [event_push.py](../src/kirabridge/event_push.py): SDK-unabhängiger Zusteller über
  das vorhandene unveränderliche Completion-Archiv; eigene private SQLite-Datei.
  Der bisherige Consumer wird nicht ausgehebelt oder vorzeitig quittiert.
- [serve.py](../integrations/chat-events/serve.py): isolierte MCP-2-Fassade mit
  Discovery, Events-Katalog, Subscribe/Refresh/Unsubscribe und vorhandenen Tools.
  Der Hauptdienst behält seine bisherigen Abhängigkeiten und Rechte.
- [Separates gesperrtes Abhängigkeitsprojekt](../integrations/chat-events/pyproject.toml)
  mit SDK `2.3.0`; ein SDK-1-Gesamtupgrade ist nicht nötig.
- [prepare.py](../integrations/chat-events/prepare.py): erzeugt private Kandidaten
  für vorhandenes Tunnelprofil und separaten LaunchAgent. Aktiviert nichts und
  verändert keine Quelldatei des installierten Profils.

Ein Chat abonniert `kirabridge.task.completed` mit genau einer vorher gewählten
`task_id`. Vor der Ausführung verlangt die Fassade die explizite verifizierte
`completion_subscription`; sie setzt `completion_target=push:<subscription-id>`.
Die bestehende Bridge speichert dieses Ziel atomar mit dem Auftrag. Deshalb kann
auch ein schneller Abschluss nicht zwischen Einreichung und Registrierung
verlorengehen. Eine andere Subscription oder ein anderer Task bekommt die Meldung
nicht. Wiederholte Einreichungen behalten die feste Route und starten keinen
zweiten Prozess. Die Zuordnung gilt für `task_request`/`task_submit`, einschließlich
`agent.run`. Dispatch-Nachrichten über `message_send` behalten bislang den bereits
bestehenden Consumerkanal; für sie wird hier keine neue Chat-Push-Abnahme behauptet.

Die Host-URL ist die einzige Chat-Zieladresse. Keine Chat-ID wird geraten. Im
bestehenden privaten Einzelbenutzer-Tunnel authentifiziert der fest konfigurierte
Principal den Anschluss; dies ist keine neue Mehrbenutzer-/OAuth-Identitätsgrenze.
Geteilte Principal-Zugangsdaten berechtigen weiterhin zur gleichen Bridge-Identität.

Vor Aktivierung prüft der Adapter einen frischen signierten Challenge-Echo. Der
Callback muss HTTPS und einen explizit zugelassenen Hostnamen benutzen. Alle DNS-
Antworten werden beim Verbindungsaufbau auf öffentliche Adressen geprüft; TCP wird
an eine geprüfte IP gebunden, TLS prüft weiterhin den ursprünglichen Hostnamen.
Keine Redirects, zehn Sekunden Gesamtlimit einschließlich DNS, begrenzte Antworten.
Der Operator muss den tatsächlich vom Host gelieferten Callback-Host freischalten;
die vorbereitete Liste ist absichtlich leer und enthält keine erfundene Adresse.

Subscription-ID, Filter, Ablauf, Schlüsselrotation und Eventkörper bleiben über
Neustarts erhalten. Standard Webhooks signiert exakt die gespeicherten Bytes;
Event-ID und Körper bleiben bei Wiederholung gleich. Maximal drei Zustellversuche
mit Backoff; keine Wiederholung bei 410/413. Nach drei unbestätigten Berechtigungs-
prüfungen stoppt dieser Auftrag mit `authorization_unknown`, ohne Daten zu senden.
Drei aufeinanderfolgende interne Senderfehler stoppen den Worker. Der vorbereitete
LaunchAgent erzwingt keine automatische Absturzschleife. Erneute Inbetriebnahme
setzt Ursachenprüfung voraus. Subscription-TTL höchstens 24 Stunden; ein stehender
Host muss rechtzeitig erneuern. Nach Ablauf, Stop oder Rechteentzug wird nicht
weiter gesendet. Ein schon laufender HTTPS-Request lässt sich nicht zurückholen.

Für den Betrieb werden zwei Prozesse verwendet: `--external-sender` als MCP-
Fassade und ein eigener, exklusiv gesperrter `--sender-only`-Prozess. Der Sender
läuft unabhängig vom Assistententurn und der Lebensdauer einer MCP-Verbindung.
Dauerhafte Meldungen werden nach einem Senderneustart wieder aufgenommen;
Ausführungsaufträge werden dabei niemals erneut eingereicht.

`completion_event_status` liefert lokale Zähler, keine Zustellfiktion.
`completion_chat_receipt` prüft einen nur im zugestellten Event enthaltenen
zufälligen Beleg gegen Task, Subscription und Event. Das Ergebnis heißt bewusst
`authenticated_payload_possession`, mit
`chat_ui_receipt_independently_verified=false`. Selbst diese Quittierung beweist
allein keine Anzeige in genau dem ursprünglichen Chat. Dafür ist die tatsächliche
Chatantwort samt Zuordnung unabhängig zu beobachten.

## Gezielte Abnahme

[Maschinenlesbarer Protokollbeleg](../examples/chat-events/run-20261019-01/evidence.json):
realer vorhandener nativer Tunnel im lokalen Testmodus → SDK-2-Stdio →
authentifiziertes Bridge-HTTP → drei echte lokale Terminalprozesse → dauerhafte
Abschlussereignisse. Ausschließlich der Host-/Chat-Callback ist **SIMULATION**.

Geprüft: schneller Abschluss, Exitcode 7, feste Routen vor Einreichung, falsche
Subscription ohne Auftragsanlage, idempotente Einreichung ohne zweiten Prozess,
Stop, Refresh und Wiederverbindung. Beim längeren Auftrag wurde die MCP-Fassade
beendet. Der separate Sender nahm den Abschluss nachweisbar **vor** dem erneuten
Start der Fassade an. Dies prüft die lokale Laufzeitunabhängigkeit, keinen echten
ChatGPT-Wake-up.

[Vollständiger Prüfbeleg](../examples/chat-events/run-20261019-01/validation.json):
**211 Tests bestanden in 81,70 Sekunden**, Ruff und Formatprüfung für 81 Dateien
sowie `git diff --check` bestanden.

26 zusätzliche Tests prüfen unter anderem Challenge, Rotation, Eigentümergrenzen,
Ablauf/Stop/Entzug, maximales Retry-Budget, unbekannten Transportausgang,
Autorisierungsausfall, unveränderte Event-ID/-Bytes, bestehende Consumer-Acks,
private/mischte DNS-Antworten und IP-Pinning mit korrektem TLS-Hostnamen. Fehlende
Session-/Freigabedaten in ersten Testfixtures sowie fehlende MCP-2-Cachefelder
wurden während des Aufbaus erkannt und korrigiert. Fehlgeschlagene Zwischenläufe
werden nicht als Abnahmebelege verwendet.

Reproduktion in neuen isolierten Ordnern, ohne installiertes Konto:

```sh
uv sync --project integrations/chat-events --locked
.venv/bin/pytest -q tests/test_event_push.py
.venv/bin/python scripts/accept_chat_events.py \
  --adapter-python integrations/chat-events/.venv/bin/python \
  --tunnel-client /Users/landjunge/.local/bin/tunnel-client \
  --output /private/tmp/kirabridge-events-NEW
```

Der Testadapter `check_protocol.py` wird niemals in einem Produktionsprofil
referenziert. Er nennt sich SIMULATED-HOST und sendet keine Netzwerknachricht an
ChatGPT. Die Produktionsdatei `serve.py` besitzt keinen simulierten Erfolgsmodus.

## Präzise fehlende Voraussetzung und nächste Nutzeraktion

Private, noch inaktive Dateien liegen auf diesem Mac unter
`~/.config/kirabridge/chat-events-prepared-20261019/`:
`tunnel-profile.candidate.json`, `com.kirabridge.chat-events.candidate.plist` und
`preparation.json`. Das Originalprofil ist per Hash unverändert. Die Kandidaten
enthalten private vorhandene Profilreferenzen und gehören nicht ins Repository.

1. Im **ursprünglichen auftraggebenden Chat** prüfen: Work mit Cloud bzw. Work-Web,
   private KiraBridge-Plugin-Einstellungen mit „Rescan MCP server“ und erlaubte
   ereignisgesteuerte Tasks. Ist der alte Chat kein unterstützter Work-Chat, ist
   seine automatische Zustellung damit noch nicht als möglich belegt; ein anderer
   neuer Chat erfüllt nicht die Forderung nach demselben ursprünglichen Chat.
2. Danach den vorbereiteten Anschluss kontrolliert im Leerlauf aktivieren:
   Task-/Empfänger-/Agentenaktivität prüfen, Einreichungen während der Umstellung
   sperren, Originalprofil sichern, eigenen persistenten Sender laden und nur die
   eigene bestehende Tunnel-Runtime umstellen. Keine Bridge-/Agentenneustarts sind
   dafür erforderlich. Diese Umstellung wurde hier nicht vorgenommen, weil
   Host-Subscription, Callback-Host und der Plattform-Rescan noch nicht vorliegen.
   Die neuen Task-Tools verlangen eine Subscription; ein ungeprüfter Wechsel würde
   bisherige zwischengespeicherte Einreichungen ohne Subscription zurückweisen.
3. KiraBridge privat rescannen. Auf der Pluginseite muss
   `kirabridge.task.completed` neben den Werkzeugen erscheinen. Im ursprünglichen
   Chat etwa anweisen: „Wähle eine neue Task-ID. Abonniere deren KiraBridge-Abschluss
   in diesem Chat, bevor du den Auftrag einreichst. Melde nach meinem Auftragende
   Endstatus, Ergebnis und Belege hier. Quittiere nur einen wirklich empfangenen
   Event-Token.“ Kein manuelles Kopieren einer erfundenen Callback-URL.
4. Die erste Subscription bei leerer Allowlist wird sicher mit
   `callback_host_not_allowed:<tatsächlicher-host>` zurückgewiesen. Genau diesen
   Host anhand der echten Hostanfrage prüfen, in beiden vorbereiteten
   Prozesskonfigurationen ergänzen und nur eigene Adapter im Leerlauf neu laden.
   Anschließend den Host erneut abonnieren lassen; Challenge muss erfolgreich sein.
5. Einen harmlosen, eindeutig korrelierten Auftrag über die Fassade einreichen.
   Assistententurn enden lassen. Danach Webhook-Annahme **und den tatsächlich im
   ursprünglichen Chat eingetroffenen neuen Turn** unabhängig prüfen. Task-ID,
   Subscription-ID, Event-ID und Tokenquittierung vergleichen. Erst dann ist der
   verlangte Abschluss erfüllt. Abschließend Stop/Unsubscribe prüfen.

Hier fehlen somit konkrete Host-/App-Konfigurationsschritte außerhalb der
verfügbaren Werkzeuge und die unabhängige Chatbeobachtung. Es wird weder eine
generelle Unmöglichkeit der dokumentierten Plattformfunktion noch ein bereits
erfolgter Chatempfang behauptet. Ohne diese Schritte sind weitere lokale
Wiederholungen kein Ersatznachweis.
