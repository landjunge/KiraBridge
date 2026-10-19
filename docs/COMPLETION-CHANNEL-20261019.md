# Abschlussmeldungen und tatsächliche Empfangsgrenzen

**Aktueller Vorrang:** [Events-Fassade zurückgerollt; ursprünglicher Anschluss wiederhergestellt](CHATGPT-EVENTS-RECOVERY-20261019.md).
Die nachfolgenden Aktivierungsangaben sind historisch. Vor erneuter Aktivierung
müssen Pflicht-Subscription für normale Aufträge und Sender-Startbereitschaft
korrigiert werden. Die App benötigt jetzt Refresh/Rescan der alten Werkzeugdefinition.

**Aktueller Stand:** [Produktions-Events-Anschluss kontrolliert aktiviert](CHATGPT-EVENTS-ACTIVATION-20261019.md).
Der bisherige Consumer bleibt erhalten. Host-Rescan, echte Subscription und
schriftlicher Empfang im ursprünglichen Chat sind weiterhin offen.

**Nachfolgender Ausbau:** [MCP Events und private Vorbereitung](CHATGPT-EVENTS-20261019.md)
implementiert und lokal geprüft. Der bestehende aktive Consumer bleibt unverändert;
Host-Subscription, Produktionsumstellung und echter Zielchat-Empfang sind weiterhin offen.

Stand 19.10.2026: Der Quellstand erzeugt für jeden neu beobachteten Task-Endzustand
und für automatische Nachrichten-Empfänger eine dauerhafte, zugeordnete Abschlussmeldung.
Ein stehender MCP-Empfänger erhält sie ohne Task-Statusabfragen und verarbeitet sie
vor der Quittierung. **Der getestete Stand ist im installierten Dienst aktiv**;
ein echter über die verbundene App eingereichter Terminalauftrag wurde dort bis
zum empfangenen und quittierten Abschluss geprüft. Ein inaktiver ChatGPT-Chat wird
über den bestehenden Anschluss weiterhin nicht autonom aufgeweckt.

## Zuerst geprüft: Kann die vorhandene ChatGPT-Verbindung den Assistenten aufwecken?

Die echte Verbindung mit Principal `chatgpt` wurde read-only initialisiert und ihre
Serverfähigkeiten und Werkzeugliste abgerufen. Advertisiert werden Tools/Prompts,
`resources.subscribe=false`, keine MCP Events; beim ersten Probezeitpunkt fehlten
die neu entwickelten Completion-Tools noch im geladenen Dienst. Nach kontrollierter
Aktivierung sind sie in der Werkzeugliste des Servers vorhanden. Die in dieser
Unterhaltung bereits gebundenen App-Tools werden dadurch nicht automatisch erweitert. Der verwendete Python-SDK-Stand ist `mcp 1.30.0`, dessen
neueste Protokollversion `2025-11-25` ist. Der vorhandene Server nutzt stateless HTTP
mit JSON-Antworten; der Stdio-Proxy leitet Tools weiter und besitzt keinen
Ereignis-Webhook oder bestätigten Assistenten-Wake-up-Kanal.

Die aktuellen [offiziellen OpenAI Docs zu MCP Events](https://developers.openai.com/plugins/build/mcp-events)
beschreiben einen Host-abonnierten Webhookweg mit MCP 2.0 (`2026-07-28`). Ein solcher
Host-Callback samt Abonnement ist hier nicht vorhanden. Ein Upgrade des gesamten
Protokoll-/Pluginanschlusses und die echte Zielchat-Abnahme wären dafür zusätzlich nötig.
Eine gewöhnliche MCP-Notification oder HTTP-Annahme wird nicht zu einem nachgewiesenen
neuen Assistententurn erklärt. Es wurden keine erfundenen Callback-Adressen verwendet.

**Ergebnis:** Proaktives Aufwecken eines inaktiven ChatGPT-Chats ist über den
bestehenden Anschluss nicht verfügbar/nicht nachgewiesen. Der implementierte
zulässige Rückkanal funktioniert mit einem aktiv wartenden Empfänger. Seine
Toolantwort kann der auftraggebende Assistent während seines laufenden Turns
empfangen; sie startet keinen neuen Turn in einem bereits beendeten Chat.

## Atomare Zuordnung, auch bei sofortigem Abschluss

`task_request` und `task_submit` nehmen zusätzlich zum unveränderten TaskRequest
optional `completion_target` entgegen: ein stabiler, opaker Zielname der
auftraggebenden Assistentensitzung, etwa `assistant-<uuid>`. Der Targetname wird
mit dem Task in derselben SQLite-Transaktion gespeichert, bevor ein Worker ihn
sehen kann. Idempotente Einreichungen behalten die erste Route; ein nachträglicher
expliziter Zielwechsel wird zurückgewiesen. Kind-/Retry-Tasks erben ohne explizites
neues Ziel die Rückadresse ihres ursprünglichen Auftrags. Bestehende Request-Hashes bleiben unverändert.

Für alle Taskoperationen legt `Store.transition` die Abschlussmeldung zusammen mit
Endstatus und dauerhaftem Ereignis atomar an. Erfasst werden `completed`, `failed`,
`cancelled`, `unknown` und `blocked`, auch Vorabprüfungsfehler, lokale Ablehnung,
Dispatcher-Wiederherstellung und spätere manuelle Klärung eines unbekannten Ausgangs.
Eine Klärung ist eine neue Meldung mit `supersedes`; der frühere unbekannte Ausgang
wird nicht rückwirkend zu einem bewiesenen Ausführungserfolg umgeschrieben.
Die Herkunft einer lokalen Betreiberattestierung bleibt kenntlich.

Auch `message_send(..., completion_target=...)` bindet eine Route bei `dispatch=true`.
`MessageReceiver` erzeugt bei Erfolg, Fehler, Unterbrechung oder Blockierung eine
Abschlussmeldung an den authentifizierten ursprünglichen Absender, unabhängig von
`request_reply`. Eine reine Inbox-Nachricht mit `dispatch=false` startet keinen
Agenten und erzeugt deshalb keinen fingierten Agentenabschluss. Extern vorab
quittierte Nachrichten werden als `not_executed` statt als Modellerfolg ausgewiesen.

Die additive Speicherung verwendet vorhandene Tasks, Ereignisse, Nachrichten und
Auditkette. Historische abgeschlossene Tasks werden nicht als angeblich neu
zugestellte Meldungen nacherzeugt. Es gibt keinen TTL-Verfall ausstehender Meldungen.
Ein Abschluss vor der ersten Empfangsverbindung bleibt in der Inbox erhalten.

## Inhalt und belastbare Fehlerunterscheidung

Jede Meldung trägt eine dauerhafte ID, Ereignisreferenz, Target, Empfangsbeleg,
Task-ID, vorhandene Session-/Prozess-ID, Endstatus, kurze Ergebniszusammenfassung
und Verweise auf die vollständigen Belege. Bei Empfängerjobs kommen Message-ID,
Gesprächs-ID, Run-ID und vorhandene Antwort-ID hinzu.

`state` erhält den tatsächlichen Taskzustand. `outcome` präzisiert ihn:

| outcome | Nachweis |
| --- | --- |
| `success` | Nachgewiesener Abschluss; bei Klärung ausdrücklich Betreiberattestierung |
| `error` | Fehlgeschlagener Auftrag, etwa Exitcode 7 oder Vorabprüfungsfehler |
| `cancelled` | Stornierung oder belegte Beendigung des eigenen Prozesses |
| `timeout` | Gemessener Prozess-Timeout oder Adaptercode `agent_timeout` |
| `unknown` | Externer Ausgang nicht bestätigt, etwa Dispatcher-Abbruch |
| `provider_error` | Beobachteter strukturierter Providerfehler oder HTTP-Ablehnung |
| `blocked` | Ausführung durch vorhandene Grenzprüfung blockiert |
| `not_executed` | Nachricht vor Empfängerausführung anderweitig quittiert |

Ein Agenten-Timeout kann zugleich `state=unknown` und
`execution_outcome_unknown=true` haben. Die Zeitüberschreitung beweist dann nicht,
dass beim externen Provider keine Wirkung eingetreten ist.

Bei gezielt beendetem Codex-Prozess ohne abschließendes Agentenereignis gilt
`outcome=cancelled` bei `state=unknown`: Der Prozessabbruch ist belegt, der externe
Agentenausgang bleibt unbestätigt. Die letzte Prozessbeobachtung und Session-ID
werden deshalb vor dem Fehler gespeichert.

Der Codex-Adapter übernimmt ausschließlich bekannte explizite strukturierte
Fehlercodes aus JSONL-Fehlerereignissen samt Quellenangabe und Ereignis-Hash.
Kontingentbelege setzen `quota_diagnosis=evidenced`; ohne solche Belege lautet es
`not_established`. Weder normaler stdout/stderr-Text noch das Wort „quota“ in einer
Modellantwort lösen eine Kontingentdiagnose aus. Die API-Ablehnung bewahrt den
HTTP-Status: 429 wird als Rate-Limit behandelt, nicht als erschöpftes Kontingent;
auch 402 beweist hier kein bestimmtes Kontoproblem. Providerfehler ohne sicheren
Abschluss lassen den unbekannten Ausführungszustand bestehen.
Alle Grok-/Kontingentfehler der Tests sind Simulationen über CLI-/HTTP-/ACP-Schnittstellen.
Es wurde kein echter Grok-Auftrag ausgelöst.

## Funktionierender Rückkanal

`completion_receive(target, wait_seconds=20)` wartet serverseitig auf ausstehende
Meldungen. Der mitgelieferte `CompletionClient` hält den Empfänger aktiv und erneuert
leere begrenzte Wartefenster automatisch. Er fragt dabei keine Taskzustände ab.
Standardmäßig hat der Listener keine Gesamtlaufzeitgrenze; Auftrags- und einzelne
Transport-Zeitlimits bleiben wirksam. Eine explizite Listener-Deadline beendet nur
den Empfänger, nicht die Speicherung des späteren Abschlusses.

```python
from kirabridge.completion_client import CompletionClient

# endpoint ist der vorhandene authentifizierte Peer; target ist die stabile
# Sitzungszuordnung, die schon bei task_request mitgeschickt wurde.
async with CompletionClient(endpoint) as receiver:
    await receiver.listen(target, process_completion, once=True)
# Erst nachdem process_completion erfolgreich zurückkehrt, wird quittiert.
```

Sichtbare Terminalausgabe desselben Empfängers nach Aktivierung einer neuen Runtime:

```sh
kirabridge --config DEMO-POLICY --principal ASSISTANT watch --target assistant-SESSION
```

`--once` verarbeitet eine Meldung; `--timeout SEKUNDEN` setzt optional eine
Gesamtwartefrist. Die tatsächliche Ausführung bleibt im vorhandenen Terminal-/
Agentenadapter; keine animierten Fortschritte ersetzen Ausführungsbelege.

Die unveränderte Legacy-Route heißt `default` und gehört zum Principal, nicht zu
einem automatisch erkannten Chat. Teilen mehrere Assistentensitzungen denselben
Principal, müssen sie unterschiedliche stabile Targets verwenden. Ein Target ist
keine neue Authentifizierungsgrenze; die bestehende Principal-Grenze gilt weiter.
Der Empfänger benötigt die vorhandenen Rechte `task.read` bzw. `message.read`.
Es werden keine globalen Fähigkeiten oder Zugangsdaten erweitert.

## Wiederverbindung und ehrliche Empfangsbegriffe

Die Zustellung ist **mindestens einmal**: Bis zur passenden Quittierung werden
ID und Empfangsbeleg unverändert wieder angeboten. Der Client quittiert erst nach
erfolgreichem Callback. Verarbeitung mit externen Nebenwirkungen muss die Notice-ID
selbst als dauerhaften Idempotenzschlüssel verwenden; exakt einmal über einen
Consumer-Absturz hinweg wird nicht behauptet.

Der Client versucht höchstens drei Wiederverbindungen für die idempotenten
Empfangs-/Ack-Aufrufe. Ausführungsaufträge werden dabei nie neu eingereicht.
Ein verlorenes Ack darf mit derselben ID und demselben Beleg wiederholt werden.
Ein Callbackfehler lässt die Meldung unquittiert für einen späteren Empfänger.

`returned_at` und das Auditereignis `completion.returned_to_client` besagen nur,
dass die Meldung in eine Toolantwort genommen wurde. `completion_ack` belegt die
Quittierung durch den Consumer, nicht einen ChatGPT-Chatturn oder menschliches Lesen.
Darum bleiben `chatgpt_chat_delivery=unverified` und die Aussage über eigenständiges
Aufwecken getrennt. Gespeicherte Ereignisse, SDK-Notifications, Terminalausgaben und
Desktopmeldungen werden nicht als Ersatznachweis für eine schlafende ChatGPT-Sitzung verwendet.

## Sichtbare Abnahme und Erhaltungsgrenzen

[Originaler Abnahmelauf](../examples/completion-demo/run-20261019-01/evidence.json),
reproduzierbar mit `scripts/accept_completion_channel.py` in einem neuen Demoordner:
sechs echte lokale MCP-Abschlussmeldungen, jeweils verarbeitet und quittiert;
sofortiger Abschluss vor Listenerstart, längerer Auftrag, Exitcodefehler, Timeout,
ein echter Codex-Turn und Wiederverbindung. Der Konsument verwendete keine
`task_get`-Abfragen. Auditkette gültig, 57 Einträge. Echte Codex-Session:
`01a15179-2165-7523-9b6e-1a5fdaf602d6`; Rückmeldung `CODEX_COMPLETION_CONFIRMED`.
Die Ausgaben wurden in dieser laufenden Codex-Sitzung tatsächlich als Toolergebnis
empfangen. Das ist kein behaupteter autonomer ChatGPT-Wake-up.

Getestet werden ferner atomarer Rollback, feste Routen, Besitzergrenzen,
Stornierung, Beendigung eigener Testprozesse, Fehler ohne Kontingentspekulation,
belegte simulierte Providerfehler, Neustart/Redelivery und eine Laufzeit über ein
volles Transport-Wartefenster hinaus. Die vollständige Suite bestand mit **184 Tests in 80,09 Sekunden**. Nach der
abschließenden Ergänzung zur Codex-Abbruchbeobachtung bestanden zusätzlich **69
gezielte Tests in 40,40 Sekunden**, einschließlich
eines 21-Sekunden-Terminalauftrags über die 20-Sekunden-Transportwartefrist hinaus.
Ruff und Formatprüfung für `src scripts tests` bestanden (74 Dateien); ebenso
`git diff --check`. Eine veraltete Whitelist-Testerwartung war auch im unveränderten
Git-Ausgangsstand `13f1cb1` reproduzierbar und wurde um das bereits vorhandene
`local_tools_available=false` ergänzt, ohne die Rechteimplementierung zu ändern.
[Baseline-Prüfbeleg](../examples/completion-demo/run-20261019-01/baseline-test-check.json).

## Kontrollierte Aktivierung und wirklicher App-Rückweg

Nach erfolgreicher Vollsuite wurde der installierte eigene Bridge-Dienst
kontrolliert neu geladen. Die anschließend gezielt geprüfte letzte Ergänzung zum
Codex-Abbruch wurde in einem zweiten kontrollierten Schritt aktiviert. Die letzte Prüfung erfolgte unter SQLite-Schreibsperre:
**0** Tasks in created/queued/accepted/running und **0** queued/running Empfängerjobs.
Nur der genau über launchd und Runtime-PID identifizierte eigene Bridge-Dienst
erhielt SIGTERM; keine Agentensitzung wurde beendet. Bestehende Daten aller acht
Task-/Ereignis-/Freigabe-/Nachrichtentabellen wurden per Hash verglichen, ebenso der
vollständige alte Auditpräfix. Alle identisch; Konfigurations- und effektiver
Policy-Hash ebenfalls unverändert. Die neue Runtime advertisiert beide Completion-Tools.
[Erste Aktivierung](../examples/completion-demo/run-20261019-01/activation.json).
Der [abschließende Aktivierungsbeleg](../examples/completion-demo/run-20261019-01/activation-2.json)
prüft zusätzlich die drei neuen Rückkanaltabellen einschließlich bereits quittierter
Abschlussmeldungen: alle elf verglichenen Tabellen, der alte Auditpräfix und die
Konfigurations-/Policy-Hashes bleiben unverändert. Beide Schritte fanden nur nach
atomarer Leerprüfung statt; keine laufenden Aufträge wurden unterbrochen.

Anschließend wurde über das **wirklich verbundene KiraBridge-App-Werkzeug** ein neuer
harmloser Terminalauftrag unter `chatgpt` eingereicht:
`completion-installed-echo-20261019-01`. Der bereits wartende Consumer empfing die
zugehörige Meldung `completion-task-2126`, Zustand completed, Exitcode 0,
`INSTALLED_COMPLETION_RETURN_CHANNEL_OK`, Prozess-ID 80200. Keine `task_get`-Abfrage
war zum Empfangen nötig. Die Quittierung wurde zusätzlich anhand genau dieser
bekannten ID im Serverbestand geprüft.

- [Tatsächliche App-Einreichung](../examples/completion-demo/run-20261019-01/installed-submission.json)
- [Tatsächlicher Callback in der aktiven Terminal-/Codex-Sitzung](../examples/completion-demo/run-20261019-01/installed-delivery.json)
- [Serverseitige Ack-Prüfung](../examples/completion-demo/run-20261019-01/installed-ack-verification.json)
- [Abnahmezusammenfassung](../examples/completion-demo/run-20261019-01/acceptance-summary.json)

Der funktionierende Rückweg verwendet den wartenden lokalen MCP-Consumer. Er
behauptet weder eine gewöhnliche Notification als Assistentenempfang noch einen
autonomen ChatGPT-Wake-up. Ein ChatGPT-Host, der einen Turn bereits beendet hat,
braucht weiterhin den gesonderten Event-/Webhookanschluss samt Zielchat-Abnahme.

Keine Veröffentlichung, globale Rechteänderung, echte Grok-Ausführung oder
Übernahme fremder Agentensitzungen. Vorherige Demoarbeiten und fremde unversionierte
Auftragsdokumente bleiben erhalten.
