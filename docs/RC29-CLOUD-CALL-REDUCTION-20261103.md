# RC29: weniger Cloud-Roundtrips statt zusätzlicher Statusketten

Ausgangspunkt ist das installierte RC28 (`6b70116`), dessen belegte äußere
Handshakekosten und Tastensequenzen weiterverwendet werden. Dieser Folgeauftrag
reduziert weitere vermeidbare Aufrufe; keine Wiederholung der RC28-Untersuchung.
Der Kira-Workflow und drei native Team-Agenten decken Implementierung,
unabhängigen Review, Sicherung und Releasevorbereitung ab.

## Nachgewiesene zusätzliche Aufrufketten

RC28 wartete bei `task_request` nur für acht Operationen auf Fertigstellung;
`task_submit` und die beiden direkten Clipboard-Werkzeuge gaben grundsätzlich
keinen allgemeinen Inlineabschluss zurück. ChatGPTs `task_get` las sofort.
Das erzeugt auch dann einen zweiten Cloud-Roundtrip, wenn die eigentliche
Dateiaktion bereits sehr schnell erledigt ist.

Drei echte RC28-Dateischreibtests in einem eigenen temporären Ordner lieferten
jeweils zunächst `queued`. Ein nachfolgender Statusaufruf bestätigte completed.
Keine UI-, Clipboard- oder Nutzerdateieingabe. Die jeweils 26 Dateibytes wurden
unabhängig lokal geprüft. Zusätzlich dieselben abgeschlossenen RC28-Testtasks,
Health und Clipboard-Fähigkeitsmetadaten ohne Clipboardinhalt:

| RC28-Workload, jeweils drei Gruppen | Cloud-RPCs je Gruppe | Gesamt ms | P50/P95 ms |
| --- | ---: | ---: | ---: |
| Health + Clipboardinfo + ein Taskstatus | 3 | 26965 | 8753 / 9469 |
| Ein Taskstatus + seine Ereignisse | 2 | 16901 | 6210 / 6503 |
| Datei schreiben + Abschluss lesen | 2 | 16976 | 5607 / 5900 |

P50 ist Median, P95 Nearest Rank; bei n=3 entspricht P95 dem Maximum.
Gemessen von unmittelbar vor dem ersten bis nach dem letzten vollständigen
Toolresultat, ohne dazwischenliegende Modell-/Voiceplanung. Zeitlich getrennte
Vorher-/Nachhergruppen sind keine kontrollierte Messung kleiner Cloudschwankungen.
[Einzelzeiten und Datenbelege](evidence/rc29-cloud-before-20261103.json).

## Implementiert

- `read_tools(calls=[{tool,arguments},…])` bündelt 1–8 bestehende Lesewerkzeuge
  in einem äußeren RPC. Bereits gecachte Clients verwenden denselben Pfad über
  `read_query({operation:tool.batch,calls:[…]})`. Eine exakte Whitelist ersetzt
  kein Recht: jeder Aufruf durchläuft den normalen registrierten MCP-Handler
  mit aktuellem HTTP-/Stdio-Kontext, Argumentvalidierung und Autorisierung.
  Alle Namen und Argumentschemas werden vor dem ersten Read geprüft.
- Keine generischen Dispatch-/Write-Tools, fremden Annotationen oder rekursiven
  Batches. JSON-only: Bilder/Audio/Ressourcen erfordern das ursprüngliche Tool;
  der Batch stoppt dabei ausdrücklich mit `read_executed`/`result_omitted`.
  Globale kooperative Deadline 12 s, Argumente zusammen 64 KiB, kompakte
  MCP-Antwortabschätzung maximal 2 MiB. Zeit-/Mengengrenzen geben Teilresultate
  und Fortsetzungscursor zurück, keinen erfundenen Gesamterfolg.
- `read_query({operation:task.observe,task_id,wait_seconds:0..18,events_after})`
  liefert frischen eigenen Task und paginierte Ereignisse zusammen. Leichtes
  Zustandslesen statt wiederholter vollständiger Ergebnisauflösung; kurzer
  read-only SQLite-Snapshot für konsistente Task-/Eventgrenzen. Approval- und
  Unknown-Zustände kehren sofort zurück. Kein Start, Retry, Reconcile oder ACK.
- Gemeinsamer Beobachter für beide Task-/Action-Submitnamen und beide
  Clipboard-Werkzeuge. Kurzarbeit wartet bis 2 s auf das Ergebnis, native
  Desktop-/Keyboardoperationen bis 13 s, bestehende Sessionqueries 9 s und
  potenziell lange Terminal-/Agentenarbeit nur 1 s. Ein gemeinsames 18-s-Budget
  begrenzt Native-Admission-Beobachtung, Inlinewait und optionalen Grok-Wait.
  Die eigentliche Ausführung und der vorhandene native Watchdog bleiben separat.
- ChatGPTs vorhandenes `task_get` wartet bei laufender Arbeit bis 2 s auf
  denselben Task. Ein Timeout beendet ausschließlich den Beobachter. Task-ID,
  Idempotenz und Unknown-Schutz bleiben erhalten; niemand tippt unter neuer ID.
- `operation_catalog(operations=[…])` erzeugt nur Schemas von 1–32 ausdrücklich
  gewählten Operationen, weiterhin unter aktueller Berechtigungs-/Plattformprüfung.
  Ohne Auswahl bleibt der vollständige bisherige Katalog verfügbar.
- Server-/Proxyhinweise empfehlen direkte Ausführung bekannter Schemas, gezielte
  Katalogabfragen und vorhandene Batches. Ein fertiges Inlineergebnis braucht
  keine pauschale zusätzliche Status-/Event-/Completionabfrage.

Submit-Endpunkte verlangen nun ausdrücklich `task.read` **vor** der Aufnahme.
Identitäten ohne dieses Recht erhalten forbidden, ohne dass ein Auftrag entsteht.
Die produktiven Rechte werden nicht geändert. Falls ein Recht erst nach Aufnahme
entzogen wird, bleibt die bekannte Task-ID mit `observation_failed` erhalten;
die Arbeit wird nicht erneut eingereicht. Das ist eine dokumentierte zusätzliche
Vorbedingung für bisherige reine Write-only-Clients.

## Prüfung und Auslieferung

Gezielte Integrationsrunde: 149 Prüfungen bestanden; ein bisheriges
`queued`-Erwartungsassert des Aliasvertrags wurde an den gewünschten direkten
`completed`-Rücklauf angepasst und separat erfolgreich geprüft. 70 Prüfungen für
den betroffenen Alias, NativeAdmission, Zustellung und Proxycache bestanden in
4,31 s; acht zusätzliche Clipboard-HTTP-Prüfungen verwenden ausschließlich
Fakeausführung, keine echte Zwischenablage. Der betroffene Read-/Katalogsatz
bestand danach nochmals 20 Prüfungen in 2,45 s. Unabhängige Reviews ohne Blocker.
Ruff/Format für alle geänderten Pythondateien sowie Lock- und Diffprüfung.

RC28 bleibt bis zur tatsächlichen Installation der produktive Stand. Ein lokales
Intel-Release, verfügbarer GitHub-Download, Sicherungs-/Installationsnachweis,
identische Apps-Nachmessungen und Abschluss-Whiteboard werden nach tatsächlicher
Verifikation ergänzt. Keine GitHub Actions oder ARM-Builds.

## Grenzen

Die drei externen Protokollschritte pro **verbleibendem** Cloud-RPC werden durch
Serverbündelung nicht abgeschafft. Innerhalb eines Bündels bleiben Reads seriell,
frisch autorisiert und nicht atomar. Ein synchroner OS-Aufruf oder große
Ergebnisserialisierung kann die kooperative Deadline überziehen. Bilder bleiben
auf dem ursprünglichen MCP-Bildpfad. Schreiboperationen werden nicht generisch
zusammengeworfen; die bereits geprüfte echte Tastensequenz bleibt verfügbar.
Voice-/Modellzeiten bleiben ohne Cloudtrace nicht weiter auflösbar. Der ältere
Terminal-„working“-Fehler ist weiterhin ein gesondertes Thema.
