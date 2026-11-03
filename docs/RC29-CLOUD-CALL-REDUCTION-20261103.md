# RC29: weniger Cloud-Roundtrips statt zusätzlicher Statusketten

RC29 ist als Sourcepin `279afcc` veröffentlicht, installiert und über den echten
Apps-Anschluss geprüft. Ausgangspunkt war RC28 (`6b70116`), dessen belegte äußere
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
  `complete`/`all_succeeded` beziehen sich auf die Leseaufrufe; für beobachtete
  Arbeit bleibt `task.state` mit etwaigem Unknown-/Pending-Hinweis maßgeblich.
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

## Tatsächlicher Apps-Nachlauf und Anzahl

Dieselben drei Workloads und unveränderten Datenparameter auf installiertem RC29,
jeweils drei Gruppen. Die beiden bisherigen `action_request`- und
`action_submit`-Namen wurden beibehalten; neue Lesewege nutzen das bereits
gecachte `read_query`, benötigen also keine neuen Toolnamen in ChatGPT.

| Gleicher Workload | Cloud-RPCs je Gruppe vorher → nachher | RC28 P50/P95 ms | RC29 P50/P95 ms |
| --- | ---: | ---: | ---: |
| Health + Clipboardinfo + ein Taskstatus | 3 → 1 | 8753 / 9469 | 4787 / 9106 |
| Ein Taskstatus + seine Ereignisse | 2 → 1 | 6210 / 6503 | 3210 / 3899 |
| Datei schreiben + Abschluss lesen | 2 → 1 | 5607 / 5900 | 1990 / 2285 |

Für alle neun Vergleichsgruppen zusammen: **21 → 9 äußere Cloud-RPCs (−57,1 %)**,
60842 → 32915 ms summierte Gruppenzeit. Die Mediane sanken um 45,3 %, 48,3 %
und 64,5 %. Die inneren drei Reads bleiben im Daemon drei frisch autorisierte
Toolausführungen, lösen aber nur einen äußeren Tunnel-/MCP-Aufruf aus.
Ein zusätzlicher abgeschlossener Idempotenzprobeaufruf und eine gezielte
Katalog-Diagnose sind außerhalb dieser neun Workload-RPCs ausdrücklich gezählt.

Alle neun Gruppen waren vollständig erfolgreich. Clipboard-Fähigkeitsantwort
und persistierter Vergleichstask stimmen vollständig mit RC28 überein.
Alle 37 historischen Ereignisse wurden bytegleich in derselben JSON-Struktur
zurückgeliefert. Alle drei RC29-Dateiaufträge lieferten direkt `completed`,
keiner benötigte einen Statuspoll. Sämtliche sechs Vorher-/Nachherdateien enthielten
exakt dieselben 26 Bytes samt SHA256. Der abgeschlossene Doppelaufruf verwendete
dieselbe ID/Idempotenz mit `overwrite=false` und behielt Created/Finished bei;
die Datei wurde nicht neu ausgeführt oder überschrieben. Die sechs eigenen
temporären Dateien wurden anschließend gezielt geprüft und entfernt.
[Einzelwerte, Teilzeiten und Gleichheitsbelege](evidence/rc29-cloud-after-20261103.json).

Der erste vollständige RC29-Bündelcall dauerte **9106 ms** und wurde nicht als
Warm-up weggelassen. Die drei lokalen Childhandler benötigten darin zusammen
etwa 153 ms, in den zwei weiteren Gruppen etwa 27/35 ms. Der Rest liegt außerhalb
dieser Childhandler einschließlich äußerer Serialisierung/Proxy/Transport/Host;
er ist ohne zusätzliche Spans keine reine Cloud- oder Modellzeit. Die größere
Streuung und kleine Stichprobe erlauben keine Garantie eines festen Speedups.
P95 des Mischbündels bleibt bei rund neun Sekunden.

Auch `operation_catalog(operations=["file.read","file.write"])` funktionierte
über den bestehenden gecachten Apps-Toolnamen und gab genau diese Schemas zurück:
ein Diagnosecall 4175 ms, Exportlänge 43788 UTF-16-Einheiten des in V8 erneut
serialisierten Wrapperresultats. Das sind keine Netzwerkbytes und kein isolierter
Kausalbeweis für eine Geschwindigkeitsverbesserung.
[Selektorbeleg](evidence/rc29-selected-catalog-20261103.json).

## Release, tatsächliche Installation und Schutz bestehender Arbeit

Sourcecommit **279afccc693e2b8d3d7d1787828ad44679d1bba2** ist gepusht.
Genau ein lokaler Intel-Build; der isolierte Installer-/Daemon-Smoke bestand
einschließlich Korruptionsablehnung und Config-/Credentialerhalt. Installer-App
prüft 537 gepackte Dateien, Intelarchitektur und Ad-hoc-Signatur.
[GitHub-Prerelease v0.8.0rc29](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc29)
enthält sieben verfügbare Assets mit geprüften Digests. Installer-Zip erneut
heruntergeladen: 3286207 Bytes, SHA256
`31870192887f1802e28b6512558fcb8403232d9fda80045c32fc84a13ff041c1`.
Keine GitHub Actions oder ARM-Builds.

Ein einziger Installationslauf im eigenen bestätigten physischen Terminalfenster
1913, TTY `ttys000`: Beginn 03.11.2026 01:27:06 UTC, Ende 01:27:27 UTC, Exit 0.
Die vorbereitende Layoutprüfung stoppte zunächst vor Installation; nach genau
einem gezielten Detach des bereits identifizierten eigenen Tabs wurde dessen
physische Trennung über CG/AX und das kanonische logische TTY-Inventar bestätigt.
Ein roher Inventarvergleich meldete nach erfolgreichem Detach zunächst nur die
geänderte Reihenfolge; unabhängige normalisierte Prüfung klärte dies ohne
erneuten Detach oder neue Fensteröffnung. Vor dem Installationsstart war ein
eigener physischer Tab bestätigt. Danach wurde ausschließlich Fenster 1913
geschlossen und dessen Abwesenheit zweimal geprüft; 1548/1604 blieben erhalten.

Laufender Daemon **56714**, Instanz `032377e6a8b043738187c88619ef084d`, Version
`0.8.0rc29`; alle **164** installierten Pythondateien bytegleich mit Wheel und
gepacktem Source. Alle drei nativen Release-/Desktopdateien stimmen in Hash und
Modus mit dem Manifest überein, Desktop-Sourcepin korrekt. Tunnelruntime meldet
process_running/healthy/ready true; die tatsächlichen Apps-Nachläufe bestätigen
zusätzlich die aktuelle externe Verbindung.

Unabhängiger Nachinstallationssnapshot: sieben geschützte Dateien in SHA/Modus/
Größe unverändert, DB-Schema gleich, alle **15474** alten Zeilen in elf Inventaren
unverändert. Die ursprünglichen Agenten 1728/1749/1825/35046 und Shell 34884
behalten PID/Start/Parent. Nur Backend, Tunnel und Connector wurden erwartbar
ersetzt. RC28-Rollback mit Installerbackup
`~/.local/share/kirabridge/install/backups/20261103-022710-8909943e` vorhanden.
[Minimierter Release-/Installations-/Erhaltbeleg](evidence/rc29-installed-release-20261103.json).

Abschluss im bestehenden ThreadDesk-Whiteboard `188ce4729a62` nach gelesener
Threadrevision 490: Beitrag `8e3877bcd0cf`, Ordinal 130, stabile Operation
`rc29-cloud-reduction-installed-20261103-279afcc`. Separater Readback bestätigte
den vollständigen Inhalt exakt; bestehende Beiträge wurden nicht ersetzt.

## Grenzen

Die drei externen Protokollschritte pro **verbleibendem** Cloud-RPC werden durch
Serverbündelung nicht abgeschafft. Innerhalb eines Bündels bleiben Reads seriell,
frisch autorisiert und nicht atomar. Ein synchroner OS-Aufruf oder große
Ergebnisserialisierung kann die kooperative Deadline überziehen. Bilder bleiben
auf dem ursprünglichen MCP-Bildpfad. Schreiboperationen werden nicht generisch
zusammengeworfen; die bereits geprüfte echte Tastensequenz bleibt verfügbar.
Voice-/Modellzeiten bleiben ohne Cloudtrace nicht weiter auflösbar. Der ältere
Terminal-„working“-Fehler ist weiterhin ein gesondertes Thema.
