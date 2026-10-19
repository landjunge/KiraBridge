# Agentenkanal ab 0.5.0

Die vorhandenen authentifizierten Zugänge `codex` und `grok` können dauerhaft adressierte Nachrichten austauschen. Der Transport verwendet SQLite und eigene MCP-Werkzeuge, keinen gemeinsamen Dateiordner. Beide behalten `approval_mode="automatic"`; Nachrichten erfordern keinen Nutzerklick und kein Kopieren zwischen Chats.

## Tatsächliche Empfänger

Der automatische Dispatcher verwendet die vorhandenen Codex-/Grok-CLI-Anmeldungen und startet **separate verwaltete Arbeitssitzungen**. Er hängt sich nicht an bestehende interaktive Terminal-Sitzungen oder fremde Aufträge an. Ihre Arbeitsverzeichnisse sind `~/workspace/KiraBridge/kanal-agenten/codex` und `grok`. Der Hilfezentrum-Auftrag `auftraege/grok-restpunkte-20261017-2103/` wird weder gestartet noch beendet oder als Kanalempfänger verwendet.

Eine Codex-Frage startet einen begrenzten Grok-Turn. Dessen Antwort wird über einen wirklich als `grok` authentifizierten MCP-Aufruf an Codex gesendet. Ein separater Codex-Turn nimmt die Antwort entgegen und quittiert sie. Die Gegenrichtung funktioniert genauso. Bis zu vier verknüpfte Vorgängernachrichten werden automatisch als Kontext übergeben, insgesamt höchstens 32 KiB.

Bestehende Adaptergrenzen gelten weiter: Codex arbeitet lesend; Grok erhält keine freie Shell-/Datei-/MCP-Ausführung. Analyse-/Leseaufträge sind als `work` möglich, Ergebnisse als `result`. Nachrichtentext gelangt als Prompt über stdin beziehungsweise ACP zum Adapter und wird niemals zu einem Shellbefehl zusammengesetzt. Der Dispatcher bestimmt Antwortadresse und Ende der automatischen Verarbeitung.

## MCP-Werkzeuge

| Werkzeug | Funktion |
|---|---|
| `message_send(message)` | Adressiert senden; Absender ausschließlich aus authentifiziertem Zugang |
| `message_receive(after=0, limit=20, conversation_id=null, wait_seconds=0)` | Eigene unquittierte Nachrichten geordnet empfangen; optional höchstens 20 Sekunden warten |
| `message_ack(message_id, receipt)` | Empfang idempotent quittieren; nur der adressierte Empfänger |
| `message_get(message_id)` | Nachricht, Quittung und tatsächlichen Verarbeitungsbeleg lesen |
| `conversation_get(conversation_id, after=0, limit=50)` | Eigenen Gesprächsverlauf abrufen |
| `message_events(message_id, after=0)` | Geordnete Zustellungs-, Verarbeitungs- und Quittungsereignisse |
| `message_channel_status()` | Eigene Gegenstellen, Grenzen und tatsächlichen Empfängerstatus prüfen |

`message_send` beispielsweise unter dem Zugang `codex`:

```json
{
  "message": {
    "recipient": "grok",
    "conversation_id": "abstimmung-001",
    "idempotency_key": "frage-001",
    "kind": "question",
    "body": "Bestätige bitte den Empfang dieser Testfrage.",
    "dispatch": true
  }
}
```

Typen: `question`, `answer`, `work`, `result`, `note`. Fragen und Arbeitsaufträge erwarten standardmäßig eine Antwort. Automatische Antworten erhalten dieselbe `conversation_id`, `reply_to` mit der Ursprungs-ID und gegebenenfalls dieselbe `task_id`. Antworten/Ergebnisse dürfen keine automatische Folgeantwort verlangen. `request_reply=false` unterdrückt eine Antwort; `dispatch=false` stellt nur ins Postfach, ohne einen Agenten aufzurufen.

Eine optionale `task_id` muss beim ursprünglichen Senden dem Absender gehören. Ihr Bezug wird bewusst mit dem Empfänger geteilt und von Antworten geerbt; allgemeiner Zugriff auf fremde Bridge-Aufträge entsteht dadurch nicht. Die Bridge vergibt eine UUID als `message_id`, sofern keine eindeutige ID angegeben wird. Die Empfängerausführung erhält zusätzlich eine eigene `processing.run_id` und wird nicht mit einem bestehenden Auftrag verwechselt.

## Terminalbedienung

Die CLI verwendet dieselben authentifizierten MCP-Schnittstellen. Zugangsdaten bleiben in der privaten Ablage:

```sh
kirabridge --principal codex message status
kirabridge --principal grok message status
kirabridge --principal codex message send grok 'Bestätige bitte den Empfang.' --conversation abstimmung-001 --key frage-001
kirabridge --principal codex message conversation abstimmung-001
kirabridge --principal grok message receive --wait 10
kirabridge --principal grok message ack MESSAGE_ID --receipt RECEIPT
```

Für die Gegenrichtung `--principal grok` und Empfänger `codex` verwenden. Nach erfolgreichem automatischem Turn ist eine Nachricht bereits quittiert und erscheint nicht erneut unter `receive`; der Verlauf bleibt über `conversation` und `get` erhalten. Nach Verbindungsabbruch mit `after=0` erneut empfangen: Unquittierte Nachrichten behalten ID und Quittung. Ein größerer Cursor überspringt bewusst ältere Nachrichten. Neue MCP-Werkzeuge müssen gegebenenfalls vom jeweiligen Client neu eingelesen werden; bestehende Sitzungen werden dafür nicht zwangsweise neu gestartet. CLI und automatische Empfängeranbindung stehen unmittelbar bereit.

## Dauerhaftigkeit und Grenzen

- Idempotenz ist an Absender und kompletten Anfrageinhalt gebunden; geänderte Inhalte unter demselben Schlüssel werden abgewiesen. `seq` ist ein dauerhafter Cursor, `position` die Reihenfolge im Gespräch. Zustellung ist bis zur Quittierung mit derselben ID/Quittung wiederholbar.
- Höchstens ein automatischer Turn läuft gleichzeitig. Wartende Jobs überleben Neustarts. Bereits beanspruchte Turns werden bei Unterbrechung mit letztem Beleg als `unknown` markiert und nicht blind wiederholt. Dies ist keine Exactly-once-Garantie eines externen Modells. Fehlgeschlagene oder unklare Turns müssen bewusst untersucht werden.
- Aktuelle Grenzen: 16 KiB Text, 100 unquittierte Nachrichten je Empfänger, 10.000 archivierte Nachrichten, 16 Nachrichten je Gespräch, Antworttiefe acht, vier Agenten-Turns je Gespräch und 24 pro Stunde insgesamt. Ein Modellturn ist auf 90 Sekunden begrenzt; MCP-Aufrufe haben eigene Zeitlimits. Erreichte Budgets ergeben `blocked`, ohne spätere stille Modellwiederholungen. Es gibt keine periodischen Modellaufrufe und keine automatischen Antwortketten auf Antworten.
- Inhalte und Belege liegen in SQLite mit Modus 0600. Das Audit enthält IDs, Quittungen und Hashes statt Nachrichtentexten oder Tokens. Nur Gesprächspartner dürfen Inhalte lesen, nur der Empfänger quittieren. `chatgpt` und `local` erhalten keinen Nachrichtenzugriff.
- Rechte `message.send`, `message.read`, `message.ack`, gegenseitige `message_peers` und `messaging.receivers` werden ausschließlich lokal konfiguriert. Im manuellen Freigabemodus ist direktes Senden nicht freigeschaltet. Bestehende Datei-, Programm-, Netzwerk- und Adaptergrenzen gelten weiter.

Die private Konfiguration und Datenbank wurden vorher gesichert. Schema 1 wird atomar auf Schema 2 erweitert, auch bei parallelem Öffnen; bestehende Aufgaben werden nicht umgeschrieben. Vor geplanten Neustarts müssen normale Bridge-Aufträge und Empfänger-Turns beendet sein.

Der [Live-Nachweis](evidence/agent-channel-2026-10-17.json) dokumentiert den echten Austausch mit beiden CLI-Adaptern, einen tatsächlichen Dienstneustart, Idempotenz, Quittungen, Fremdzugriff und die erhaltene Hilfezentrum-Arbeit.

## Existing macOS terminals

`session_catalog` lists existing Terminal.app tabs as well as tmux panes. Use its
exact `pane_id` and `expected_pid` with `session_read` or the queued `session.input`
operation. `session_open` queues a new visible window using `task_id`,
`idempotency_key`, `cwd` and optional `argv`. It requires `session.open` plus
`terminal.execute`; enable only for authorized principals. Existing windows are
never stopped or replaced. Terminal.app input submits a line; `submit=false` is
rejected. An input receipt does not prove agent processing; read back output.

macOS automation uses explicit JavaScript (`osascript -l JavaScript`). Automation
denial is reported rather than treated as an empty terminal list. Private tmux
sockets remain isolated from native Terminal.app discovery.

Health reports the bridge receiver dispatcher; channel status reports the caller's
inbox and separately its peer receivers. A caller without its own automatic
receiver can still address configured peers and use interactive session tools.
