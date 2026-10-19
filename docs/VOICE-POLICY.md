# Daniels Voice- und Terminal-Policy

Diese Policy ersetzt für Daniels Installation die allgemeine Terminal-Pufferregel.
Die bestehende rc2-Version bleibt erhalten.

| Modellfamilie | Voice | Terminal | Authentifizierte Principals |
| --- | --- | --- | --- |
| Grok | Eve | Grok Build | `grok_app`, `grok` |
| ChatGPT | Kira | Codex | `chatgpt`, `codex` |

Eve übermittelt ausschließlich Daniels Diktat. Keine eigenen Ergänzungen,
kein eigenständiges Hinzufügen der Versandfreigabe, kein vorzeitiges Abschicken.
Die Bridge-Instruktionen und das Identitätsprofil geben diese Vorgabe aus;
die Herkunft eines Textes aus gesprochenem Diktat kann der Server selbst
nicht beweisen. Die Namen bezeichnen Rollen, keine vier getrennten Modellfamilien.

## Terminaleingaben

`principals.grok_app.automatic_operations = ["session.input"]` ist Daniels
dauerhafte Freigabe für Eve. Sie gilt auch bei ansonsten manueller Freigabe
oder `permission_level = "ask"` nur für diese Operation. Das Capability-Recht
`session.input`, ein gültiges Katalogziel und die Prüfung von `expected_pid`
bleiben erforderlich. Andere Operationen erhalten dadurch keine Freigabe.
Für neue Eingaben gibt es weder Marker noch Puffer noch manuelle Einzelbestätigung.
Bestehende alte Puffer werden nicht nachträglich ausgeführt.

`session_input_policy.enabled = false` schaltet die frühere Terminalregel aus.
Für besondere Altinstallationen ist sie weiterhin mit einer expliziten Liste
`session_input_policy.principals` verfügbar; die Standardliste ist leer.

## Ausgehende Bridge-Nachrichten

Nur `grok_app` und `chatgpt` benötigen `go-go-go` für `message_send` und
`team_message_send`. Direktnachrichten zwischen `grok` und `codex` sowie
anderen Terminal-Principals gehen ohne diese Freigabe durch. Ihr Inhalt wird
nicht nach Markern verändert.

Ein abschließendes, exakt kleingeschriebenes `go-go-go` gibt eine Voice-Nachricht
sofort frei. Abschließender Leerraum ist erlaubt. Nur der Marker und der direkt
davor liegende Leerraum werden entfernt. Ein alleinstehender Marker ohne
Nachrichteninhalt wird abgelehnt.

Ohne Marker liefert der Aufruf `message_buffer.state = "waiting"` und eine
feste `id` sowie `expires`. Es gibt noch keinen Eintrag im zugestellten Verlauf,
keine Zustellquittung und keinen Empfängerjob. Der gleiche authentifizierte
Absender kann vor Ablauf nachreichen:

```json
{"message_id": "DIE-ZURÜCKGEGEBENE-ID", "token": "go-go-go"}
```

Dafür dient `message_release`; alternativ:

```sh
kirabridge --principal grok_app message release DIE-ID --token go-go-go
```

Der Token ist Daniels Versandmarker, kein allgemeiner Berechtigungs-Token.
Er ist an die ausgewählte gepufferte Nachricht gebunden. Inhalt, Empfänger,
Idempotenzschlüssel, Rückkanal und ursprüngliche Frist bleiben fest.
Wiederholungen stellen dieselbe Nachricht nicht erneut zu.
Nach `voice_messaging.timeout_seconds` (Standard 60 Sekunden) wird der Puffer
`expired`; ein späterer Token kann ihn auch nach Neustart nicht reaktivieren.
Freigabe, Ablauf und Zustellung sind transaktional und werden protokolliert.
Die Sequenz im Verlauf entsteht erst bei tatsächlicher Freigabe, sodass
später freigegebene Nachrichten keine bereits gelesenen Cursor unterschreiten.

## Gemeinsamer Voice-Verlauf

`eve-kira-shared` ist ein Gespräch mit dauerhaft gespeicherter Teilnehmerliste,
nicht nur eine frei benannte Zweier-Konversation. Mitglieder sind Eve
(`grok_app`), Kira (`chatgpt`) und Daniel (lokaler Operator `local`). Daniel kann
mit `conversation_get` mitlesen, ohne Empfangsquittungen abgeben zu müssen.
Alle neuen Eve-Kira-Nachrichten werden unabhängig von der angefragten
conversation_id dorthin geleitet, auch aus dem Team-Nachrichtenweg.
Verwaltete Terminal-Empfänger werden für dieses Gespräch nicht gestartet.

Jeder zugestellte Eintrag besitzt globale `seq`, Gesprächsposition `position`,
Zeitstempel `created` und authentifizierten `sender`. Der Verlauf bleibt nach
Quittierung erhalten, ist paginiert und unterliegt nicht dem kurzen Limit
für normale Zweiergespräche. Das globale Speicherlimit stoppt neue Einträge,
ohne alte zu löschen. Datenbank-Trigger verbieten Änderungen und Löschungen
der gemeinsamen Nachrichteninhalte; Zustell- und Quittungsmetadaten bleiben
aktualisierbar. Eine spätere Konfigurationsänderung löscht keine Mitgliedschaft.

Grok Build und Codex können den Verlauf über Nachrichten-, Gesprächs-,
Ereignis- oder Empfangswerkzeuge weder lesen noch beschreiben.
Die Mitgliederprüfung gilt auch bei bekannter Nachrichten-ID.
Bestehende allgemeine Team-Verläufe werden nicht rückwirkend umgeschrieben.

Diese Grenze ist eine API-Zugriffskontrolle. Uneingeschränkter Shell- und
Dateizugriff unter demselben macOS-Benutzer kann die Datenbank oder fremde
Zugangsdaten erreichen. Vollständige Isolation gegenüber solchen Terminal-
Agenten benötigt eine getrennte Betriebssystem-Identität beziehungsweise
einen getrennten Speicherdienst. Diese Änderung behauptet keine solche Isolation.

`bridge_health`, `operation_catalog` und `policy.inspect` zeigen Identität,
Voice-Gate, Timeout und dauerhafte Operationsfreigaben. Die additive
Beispielkonfiguration steht in `examples/voice-policy.toml`.
