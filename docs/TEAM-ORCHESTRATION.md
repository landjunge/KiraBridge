# Zusammenarbeit in KiraBridge

KiraBridge stellt einen dauerhaften Teamraum für ausdrücklich eingerichtete
Zugänge bereit. Aktive Koordinatoren, Bearbeiter und Prüfer können jedem anderen
aktiven bearbeitenden Mitglied Nachrichten senden und Aufträge erteilen.
Alle aktiven Mitglieder sehen die gemeinsamen Aufträge, Ergebnisse und
Teamereignisse. Beobachter lesen ausschließlich. Private Einzelaufträge und
private Gespräche werden dadurch nicht automatisch geteilt.

## Im Browser bedienen

Auf dem Betreiber-Mac `kirabridge approvals` öffnen. In derselben angemeldeten
lokalen Oberfläche **Team** wählen; die Adresse ist
`http://127.0.0.1:8766/team`. Ein nackter Link ersetzt die Anmeldung über den
lokalen Starter nicht. Die Konsole bleibt auf den lokalen Rechner begrenzt.

1. Ein Team auswählen oder mit einer eindeutigen Teamkennung anlegen.
   Als Mitglieder stehen ausschließlich die lokal eingerichteten Teilnehmer
   zur Verfügung. Der Ersteller bleibt Eigentümer des Teams.
2. Unter **Koordinator wählen** beispielsweise `chatgpt`, `codex` oder `grok`
   auswählen. Der bisherige Koordinator wird atomar zum Bearbeiter. Der
   Eigentümer behält die Kontrolle. Änderungen an Rollen prüfen die zuletzt
   gelesene Revision; gleichzeitige Änderungen werden nicht überschrieben.
3. Mit **Nachricht senden** einen adressierten Beitrag ins Team-Postfach legen.
   Der Absender ist der angemeldete lokale Zugang; er ist kein Eingabefeld.
   Eine Nachricht startet keinen Modellaufruf. Empfangsquittungen bestätigen
   ausschließlich den tatsächlichen Empfang.
4. Unter **Auftrag vergeben** das verantwortliche Mitglied auswählen und den
   Auftrag beschreiben. Ein automatischer Empfänger erhält einen separaten,
   begrenzten Agentendurchgang. Ein externer Empfänger nimmt den Auftrag
   ausdrücklich über seine authentifizierten MCP-Werkzeuge an.
5. Unter **Gemeinsame Aufträge und Ergebnisse** den belegten Zustand, Ergebnis,
   Fehler und technische Belege ansehen. **Durchgang beendet** bedeutet nicht,
   dass ein Gesamtprojekt fachlich abgenommen ist.

Die sichtbare Seite kann alle fünf Sekunden lesend aktualisieren; diese Option
ist abschaltbar und pausiert in ausgeblendeten Tabs sowie während der Eingabe.
Nachrichten und Aufträge sind mit jeweils 50 Einträgen seitenweise abrufbar.
**Weitere laden** schaltet die automatische Aktualisierung aus, damit ein
gelesener älterer Verlauf sichtbar bleibt. **Aktualisieren** liest die erste
Seite erneut; die automatische Aktualisierung lässt sich wieder einschalten.
Ein Verbindungsabbruch sendet keine Schreibanfrage automatisch erneut. Bei einer
verlorenen Antwort zuerst aktualisieren. Der Browser behält den Idempotenzschlüssel
der unbestätigten Aktion, auch über das Neuladen desselben Tabs hinweg. Eine
bewusst erneut abgesendete identische Aktion bleibt dadurch derselbe Auftrag;
geänderte Inhalte unter diesem Schlüssel werden abgewiesen.

## ChatGPT oder einen anderen Zugang zum Koordinator machen

Die Koordinatorrolle ist unabhängig vom Anbieter. ChatGPT benötigt seinen
vorhandenen authentifizierten MCP-Zugang und die Team-Werkzeuge. In einem
aktiven Chat kann es seine Teams und Nachrichten lesen, vorhandene Ergebnisse
prüfen, Aufträge verteilen und Rollen ändern, wenn es Koordinator ist. Die
Bridge kann keinen geschlossenen Chat wecken und übernimmt keine bestehende
interaktive Agentensitzung. Die Rolle allein startet keinen Hintergrundauftrag.

Ein Beispiel für die Anweisung an einen verbundenen ChatGPT-Koordinator:

> Lies `team_list` und `team_get`. Prüfe `team_work_list` und `team_messages`,
> bestätige an dich adressierte Nachrichten und verteile die Teilaufgaben über
> `team_work_create`. Werte die belegten Ergebnisse aus. Starte keinen unklar
> beendeten Auftrag erneut.

Jeder Aufruf handelt ausschließlich als authentifizierter Zugang. Der Browser
handelt als `local`; ChatGPT handelt als `chatgpt`. Der Koordinator kann nicht
als Grok oder Codex auftreten. Die Rolle erlaubt keine zusätzlichen Datei-,
Shell-, Administrations- oder Anbieterrechte.

## MCP-Aufrufe

Alle Werkzeuge verwenden API-Version 1 und die bestehenden Authentifizierungswege.
Nach dem Update muss ein Client die neue Werkzeugliste gegebenenfalls neu laden.

| Werkzeug | Zweck |
| --- | --- |
| `team_create(request)` | Team innerhalb der lokalen Teilnehmerliste anlegen |
| `team_list()` / `team_get(team_id)` | Eigene Teams, Mitglieder, Rollen und Revision lesen |
| `team_context(team_id)` | Aktuelle Ergebnisse und bevorzugt eigene offene Nachrichten begrenzt lesen |
| `team_set_role(request)` | Rolle oder Aktivität mit erwarteter Revision ändern |
| `team_message_send(request)` | Adressierte Nachricht dauerhaft speichern |
| `team_messages(team_id, after, limit)` | Geordneten gemeinsamen Verlauf lesen |
| `team_message_ack(team_id, message_id)` | Als tatsächlicher Empfänger quittieren |
| `team_work_create(request)` | Mitglied beauftragen, optional als echten Unterauftrag |
| `team_work_list(...)` / `team_work_get(...)` | Gemeinsame Arbeit und Ergebnisbelege lesen |
| `team_work_claim(request)` | Eigenen externen Auftrag ausdrücklich annehmen |
| `team_work_complete(request)` | Eigenes externes Ergebnis melden |
| `team_work_reprocess(request)` | Als Besitzer/Koordinator ein bestätigtes vorhandenes Core-Ergebnis erneut verarbeiten, mit Core-ID und Ergebnis-Hash |
| `team_events(team_id, after, limit)` | Dauerhaften Ereignisverlauf lesen |

Ein Auftrag, beispielsweise durch den Zugang `chatgpt`:

```json
{
  "request": {
    "team_id": "kirabridge-team",
    "assignee": "opencode",
    "title": "Formulierung prüfen",
    "body": "Schlage eine kürzere Formulierung für: Der Vorgang wurde beendet.",
    "idempotency_key": "formulierung-001"
  }
}
```

Den zurückgegebenen Teamauftrag mit `team_work_get` lesen. Der teamweite
`work_id` und der darunterliegende `core_task_id` sind verschiedene Kennungen.
Ein vergebener Auftrag ist noch keine bestätigte Ausführung. Den gleichen
Idempotenzschlüssel ausschließlich mit demselben Inhalt verwenden.

Ein externes Mitglied nimmt den eigenen Auftrag mit `team_work_claim` an und
meldet sein Ergebnis mit `team_work_complete`:

```json
{
  "request": {
    "team_id": "kirabridge-team",
    "work_id": "ZURUECKGEGEBENE_WORK_ID",
    "idempotency_key": "annahme-001"
  }
}
```

```json
{
  "request": {
    "team_id": "kirabridge-team",
    "work_id": "ZURUECKGEGEBENE_WORK_ID",
    "result": "Die Formulierung ist geprüft.",
    "success": true,
    "idempotency_key": "ergebnis-001"
  }
}
```

Ein so gemeldetes Ergebnis ist als Bericht des Bearbeiters gekennzeichnet,
nicht als Beweis einer durch die Bridge beobachteten Programmausführung.

## Automatische Zusammenarbeit der Arbeitsagenten

Der Dispatcher übergibt einem automatischen Empfänger seinen Auftrag,
Teammitglieder/Rollen und begrenzten gemeinsamen Kontext. Der Agent kann ein
gewöhnliches Textergebnis liefern oder genau folgendes JSON-Format verwenden.
Der Standard `response_framing="strict_json"` erkennt Aktionen ausschließlich in
einem vollständigen JSON-Objekt der gesamten Antwort. JSON innerhalb von Prosa,
Markdown-Codeblöcken oder anderen Daten löst keine Aktionen aus.

```json
{
  "kirabridge_team": "1",
  "result": "Mein Teil ist erledigt; ich lasse die Formulierung prüfen.",
  "actions": [
    {
      "type": "task",
      "assignee": "grok",
      "title": "Formulierung prüfen",
      "body": "Prüfe diese Formulierung: Der Vorgang ist beendet."
    },
    {
      "type": "message",
      "recipient": "chatgpt",
      "kind": "note",
      "body": "Die Prüfung wurde an Grok delegiert."
    }
  ]
}
```

Die Bridge prüft das Ergebnisformat und führt höchstens vier zulässige Aktionen
über die authentifizierten Team-MCP-Werkzeuge des tatsächlichen Bearbeiters aus.
Unteraufträge erhalten den echten aktuellen Auftrag als Elternreferenz. Ein
Agent kann im Ergebnis keine Rolle, Absenderidentität, Shellbefehle oder
beliebigen Programmeinstellungen einschleusen. Ein Text in einer Nachricht ist
kein Shellcode und startet keinen automatischen Antwortkreislauf.

Ein CLI-Koordinator arbeitet in begrenzten Durchgängen. Die Koordinatorrolle
startet keine unbegrenzte Überwachung. Für eine automatische Rückfrage oder
Rückgabe kann ein Bearbeiter ausdrücklich einen begrenzten Folgeauftrag an
den Koordinator erzeugen; auch dieser bleibt Teil derselben Delegationskette.
Ergebnisnachrichten allein starten keinen weiteren Modellturn.

Automatische Empfänger erhalten aktuelle Arbeitsstände und bevorzugt ihre
offenen Nachrichten im begrenzten Kontext. Quittiert wird der Empfang dieses
Kontexteintrags, bei gekennzeichneter Kürzung auch nur des Auszugs; das beweist
weder ein vollständiges inhaltliches Lesen noch eine erledigte Aufgabe.
Vollständige gemeinsam geteilte Inhalte sind weiter über die Team-Lesewerkzeuge
abrufbar. Für lokale strukturierte OpenCode-Antworten kann der Betreiber
`agents.opencode.local_output_tokens = 512` konfigurieren.

### Optionaler fester Antwortvorspann

Einige kleine lokale Modelle setzen einen wiederkehrenden Vorspann vor ihre
JSON-Antwort. Der Betreiber kann ausschließlich für den betroffenen Empfänger
in dessen bestehendem Konfigurationsabschnitt ergänzen:

```toml
[team.workers.opencode]
agent = "opencode"
cwd = "/ABSOLUTER/FREIGEGEBENER/ORDNER"
timeout = 120
response_framing = "work_reply_header"
```

Dieses bewusste Opt-in berücksichtigt exakt den folgenden Vorspann, gefolgt
von einem Zeilenumbruch und genau einem gültigen Team-JSON-Objekt:

```text
Here is the work reply:
{"kirabridge_team":"1","result":"Geprüft.","actions":[]}
```

Die feste Kopfzeile muss am Anfang stehen; Leerzeichen oder Tabs an ihrem Ende
und LF/CRLF als Zeilenumbruch sind zulässig. Zwischen Vorspann und JSON sowie
nach dem JSON ist ausschließlich Whitespace zulässig. Freie Einleitungen,
Nachsätze und eingebettete JSON-Ausschnitte werden
nicht nach Aktionen durchsucht. Der Standard bleibt `strict_json`; dieses
Empfängerprofil erweitert weder die erlaubten Aktionen noch Identitäten,
Dateirechte oder Delegationsbudgets. Fehlerhaftes JSON wird nicht repariert.
Ein kleineres Modell kann weiterhin das geforderte Format verfehlen. Das ist
kein Nachweis einer erfolgreichen Delegation.

### Vorhandenes Ergebnis gezielt nachverarbeiten

Wenn ein Modellturn bereits nachweislich abgeschlossen ist, sein Team-Ergebnis
aber beispielsweise wegen eines ungeeigneten Antwortformats nicht wie erwartet
verarbeitet wurde, darf der Besitzer oder aktuelle Koordinator bewusst
`team_work_reprocess` verwenden. Dabei wird **derselbe gespeicherte native
Ergebnistext** erneut geprüft. Der ursprüngliche Modellturn wird weder neu
eingereicht noch wiederholt. Fehlende oder unklar beendete Core-Aufträge sind
keine Grundlage für diese Nachverarbeitung. Auch der Teamauftrag muss bereits
`completed` sein und ausdrücklich null bisherige Aktionen belegen
(`evidence.actions=[]`). Der native Core-Auftrag muss einen erfolgreichen
Abschluss nachweisen. Dies ist keine allgemeine Wiederaufnahme fehlgeschlagener
Aufträge oder bereits angewandter Aktionen.

1. Den vorhandenen Teamauftrag mit `team_work_get` lesen und den ursprünglichen
   Ausführungsnachweis prüfen. Die gebundene `core_task_id` und
   `evidence.core_result_sha256` aus genau diesem Auftrag übernehmen.
2. Das tatsächlich geladene Antwortprofil des betroffenen Empfängers prüfen.
   Eine Änderung an der lokalen Konfigurationsdatei belegt noch nicht, dass der
   laufende Dienst diese Einstellung geladen hat.
3. Als Besitzer oder aktueller Koordinator einmalig nachverarbeiten und einen
   stabilen Idempotenzschlüssel verwenden. Beispiel mit ausdrücklich zu
   ersetzenden Belegwerten:

   ```sh
   kirabridge --principal local team reprocess TEAM_ID WORK_ID --core-task CORE_ID --result-sha256 SHA256 --key nachverarbeitung-001
   ```

   Das entsprechende MCP-Werkzeug heißt `team_work_reprocess(request)`. Seine
   Anfrage enthält exakt `team_id`, `work_id`, `core_task_id`,
   `expected_result_sha256` und `idempotency_key`.
4. Den Teamauftrag und `team_events` erneut lesen. Die Nachverarbeitung ist
   ein eigener protokollierter Vorgang. Ein weiterhin ungültiges Ergebnis wird
   dadurch nicht als Erfolg ausgewiesen.

Der Hash bezieht sich auf die unveränderten UTF-8-Bytes von
`result.get("text", result.get("final_message", ""))` im ursprünglichen
Core-Ergebnis: SHA-256 ohne zusätzliche Zeilenumbrüche und ohne kanonische
JSON-Kodierung. Ein gekürzter Teamkontext oder ein bereits extrahiertes
Textergebnis kann einen anderen Hash haben. Bei älteren Aufträgen kann das
geteilte Hashfeld fehlen; dann ist zuerst eine autorisierte lokale Prüfung des
vollständigen Originalbelegs nötig. Private Aufträge werden dafür nicht
pauschal anderen Mitgliedern zugänglich gemacht.

Core-ID, Ergebnis-Hash, aktuelle Rolle und Bindung an den Teamauftrag werden
geprüft. Die neu ausgewerteten Aktionen verwenden die deterministischen
Idempotenzschlüssel desselben Teamauftrags. Je Teamauftrag ist höchstens eine
solche Nachverarbeitung möglich. Wiederholte identische Anfragen mit demselben
Schlüssel lesen den bestehenden Vorgang; ein anderer Schlüssel eröffnet keine
zweite Nachverarbeitung.
Zulässige, bisher nicht angelegte Unteraufträge können bei der Nachverarbeitung
entstehen und anschließend eigene begrenzte Modellturns starten. Deshalb ist
dies keine allgemeine Zusage, dass keinerlei Folgearbeit ausgelöst wird.

## Voraussetzungen und wirkliche Grenzen

Die lokale Konfiguration in [examples/team.toml](../examples/team.toml) ist ein
additives Beispiel. Bestehende Principals, Agentenkonfigurationen und Freigaben
erhalten; keine produktive Konfiguration durch die Beispieldatei ersetzen.
`team.workers` ist die vom Betreiber eingerichtete Liste zulässiger Identitäten
und automatischer Empfänger. Rollen können keine zusätzliche Identität freischalten.

- Ein automatischer Empfänger benötigt eine eigene authentifizierte Identität,
  `agent.execute`, den eigenen konfigurierten Agenten, einen festen erlaubten
  Arbeitsordner und den automatischen Freigabemodus. Die Bridge verwendet die
  bereits konfigurierte Anmeldung; sie erstellt und kauft keine Konten.
- Ein konfigurierter oder installierter Adapter bestätigt keine erfolgreiche
  Anmeldung, Modellverfügbarkeit, Dateibearbeitung oder kostenfreie Nutzung.
  Die [CLI-Anbieter](providers/README.md) behalten ihre tatsächlichen Grenzen.
  Insbesondere sind die zusätzlichen OpenCode-/Claude-/Gemini-/Copilot-Adapter
  auf isolierte Textaufträge begrenzt. Codex/Grok behalten ihre eigenen Rechte.
- ChatGPT und weitere Teilnehmer ohne automatischen Agenten bleiben externe
  Mitglieder. Sie können in ihrer aktiven Sitzung Aufträge annehmen, bearbeiten
  und Ergebnisse melden. Ein Koordinator ohne laufenden Chat arbeitet nicht
  von selbst weiter.
- Unklare oder unterbrochene Ausgänge werden nicht blind erneut ausgeführt.
  Bekannte Aufträge werden nach einem Neustart anhand ihrer dauerhaften
  Referenz beobachtet. Grenzen für Tiefe, Unteraufträge, Stundenbudget, Queue,
  Nachrichtengröße und Ergebnisgröße begrenzen automatische Arbeit.
- Ein entzogenes Teamrecht wird erneut vor der Ausführung geprüft. Ein bereits
  begonnenes externes Programm lässt sich durch eine Rollenänderung nicht
  rückwirkend ungeschehen machen. Bestehende unabhängige Sitzungen bleiben erhalten.
- Gemeinsame Teamdaten sind für alle aktiven Teammitglieder bestimmt. Keine
  Zugangsdaten oder privaten Inhalte in Auftragstexte oder Nachrichten schreiben.
  Audit-Protokolle enthalten IDs und Hashes statt dieser Texte.

## English quick start

Open `kirabridge approvals` on the operator's Mac and choose **Team**. Create a
team from the operator-approved roster, select its coordinator and assign work
to an active worker, reviewer or coordinator. The owner retains control;
observers only read. All active members can inspect intentionally shared work
and results, while private tasks remain private.

ChatGPT uses its existing authenticated MCP connection. Read `team_list`,
`team_get`, `team_messages` and `team_work_list`; assign work using
`team_work_create`. External assignees explicitly use `team_work_claim` and
`team_work_complete`. Automatic workers run separate bounded turns and may
return the JSON action envelope above. The bridge does not attach to an existing
interactive session or wake a closed ChatGPT chat.

The default `strict_json` response framing does not extract actions from prose
or code fences. The operator can explicitly select `response_framing="work_reply_header"`
for one worker to accept the exact `Here is the work reply:` header, a newline,
and one complete team JSON object. Arbitrary leading/trailing prose is not allowed.

Only the owner/current coordinator may explicitly reprocess an already completed
native turn through `team_work_reprocess` or `kirabridge team reprocess`. The
shared work must already be completed with explicit evidence of zero prior
actions. At most one such reprocessing is permitted per work item; repeating
the same idempotency key reads the existing operation. Pin the
original `core_task_id` and `evidence.core_result_sha256`; the hash covers the
unchanged native UTF-8 response text. This never retries the original model turn.
Valid actions may create new bounded child assignments, so follow-up work remains
possible. Historical records without the shared hash require authorized local
evidence review first.

Messages never trigger implicit model replies. Unknown outcomes are not retried
automatically. Roles do not widen operating-system or provider permissions;
installed CLIs still need working accounts/models. A reported result is distinct
from independently observed execution evidence. After a missing browser response,
refresh first; the pending operation retains its idempotency key.
