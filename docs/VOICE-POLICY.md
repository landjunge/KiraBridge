# Daniels Voice- und Terminal-Policy

Stand 20. Oktober 2026: Daniel hat die zusätzliche `go-go-go`-Freigabepflicht
für Kira und Eve ausdrücklich aufgehoben. Neue normale Nutzeraufträge benötigen
kein Sondertoken. Frühere Puffer- und Terminalbelege werden nicht umgeschrieben.

| Modellfamilie | Voice | Terminal | Authentifizierte Principals |
| --- | --- | --- | --- |
| Grok | Eve | Grok Build | `grok_app`, `grok` |
| ChatGPT | Kira | Codex | `chatgpt`, `codex` |

Eve übermittelt Daniels ausdrücklichen Auftrag ohne eigene Ergänzungen.
Eine zusätzliche Versandfreigabe durch ein Sondertoken ist nicht erforderlich.
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

`message_send` und `team_message_send` übermitteln neue ausdrückliche Aufträge
für Kira (`chatgpt`), Eve (`grok_app`), Codex und Grok ohne Sondertoken.
Capabilities, gegenseitige Peer-Freigaben, Team-Zugehörigkeit, Inhaltsgrenzen,
Idempotenz und feste Rückkanäle bleiben wirksam. Texte werden unverändert
übernommen; auch ein wörtlich enthaltenes `go-go-go` wird nicht mehr entfernt.

```toml
[voice_messaging]
release_required = false
# Nur für vorhandene historische Puffer; keine neue Versandwartezeit.
timeout_seconds = 60
```

`release_required` akzeptiert ausschließlich `false`. Ein Update kann es nicht
versehentlich auf `true` stellen. Die Einstellung wird in der tatsächlich
verwendeten Konfiguration gespeichert und im geladenen Profil geprüft.
`voice_message_gate` ist für alle vier Absender `false`.

Historische wartende oder abgelaufene Einträge bleiben unter ihrer ursprünglichen
ID und Frist erhalten. Ein erneuter Aufruf mit demselben Schlüssel liefert den
alten Zustand, ohne die Nachricht neu zu versenden. Die alte explizite
`message_release`-Schnittstelle bleibt ausschließlich für noch gültige Altbelege
kompatibel; neue Nachrichten benötigen sie nicht. Ein Ablauf oder Neustart
stellt alte Nachrichten niemals nachträglich zu.

## Sichtbare Übergabe an CLI-Agenten

Für neue Agentenübergaben ist das eindeutig gebundene bestehende sichtbare
Terminal der Standard. Kira und Eve werden dabei anhand ihrer authentifizierten
Voice-Identitäten behandelt, nicht mit einem CLI-Fenster verwechselt.
Die Regel gilt ebenfalls für Codex und Grok. Keine Absender-Ausnahme erlaubt
einen stillen Hintergrundersatz. Fehlende oder geänderte Fenster-/TTY-/PID-
Zuordnung blockiert die Übergabe.

Einfügen, Return, beobachtete Übernahme des Eingabefelds, authentifizierte
Empfangsbestätigung und abschließende Antwort sind getrennte Belege.
Ein Transporterfolg allein bestätigt keinen Agentenempfang. Unklare Ausgänge
werden vor einem weiteren Zugriff abgeglichen und niemals blind wiederholt.

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
