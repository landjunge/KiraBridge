# Vorabprüfung und Diagnose · 0.5.2 · 18.10.2026

Auftrag nach der lokalen Reparatur: konkrete Voraussetzungen vor Arbeitsbeginn
und nachvollziehbare Fehler anhand der **bestehenden** Task-/Event-/Auditdaten.
Keine zweite Logdatei, keine neue Taskzustandsmaschine, keine neuen Rechte oder
externen Gegenstellen. Die bestätigte ChatGPT-Dateiabnahme
`chatgpt-file-verification-20261018-1311` bleibt unverändert erhalten und wird
nicht erneut ausgeführt. Repository weiterhin privat; Lizenz/Veröffentlichung
sind ausdrücklich unentschieden.

## Vor Beginn eines Arbeitsablaufs

Bestehendes MCP-Tool **`bridge_readiness`** mit den tatsächlich benötigten
`read_paths`, `executables`, `operations` und einer eigenen `workflow_id` aufrufen.
Operationsrechte werden gegen genau den authentifizierten Principal geprüft;
Clipboard-Lesung/-Schreiben prüft nur die Backend-Voraussetzung, keinen Inhalt.
Die Auswahl ist der Vertrag der Prüfung: Nicht angegebene Ressourcen oder die
Funktion eines fremden Diensts werden daraus nicht abgeleitet. Lokaler Weg:

```sh
kirabridge --principal chatgpt readiness \
  --workflow-id project-review-20261018 \
  --read-path /Users/landjunge/KiraBridge/README.md \
  --operation file.read --operation terminal.execute \
  --executable /usr/bin/osascript
```

Der CLI-Abgleich erkennt zusätzlich Abweichungen zwischen laufendem Dienst und
lokalem Quell-/Konfigurationsstand. `requested_prerequisites_ready=false` oder
CLI-Exit1 verlangt zuerst die genannte Korrektur. Ein konkreter Workflow mit
fehlender Audit-Aufzeichnung wird ebenfalls nicht grün ausgegeben. Ohne
Anforderungen bleibt das Ergebnis `null`. Die Abfrage führt kein Tool, keinen
Prozess und keine Dateiinhaltslesung aus. Mit `workflow_id` speichert sie einen
begrenzten Metadatenbeleg in der vorhandenen Audit-Kette.

Zusätzlich prüft der Dispatcher **jeden neuen Task vor dem Operationsstart**:
Dateilesung/-liste, verändernde Elternpfade, Terminalprogramm und CWD bzw.
Agenten-CWD. Ablehnung bleibt `failed`, mit tatsächlicher Annahmezeit und
`started=null`; Annahme ist keine Ausführung. Eine Capabilityprüfung allein
belegt keine erfolgreiche Programmausführung oder fremde Anmeldung. Die echten
Manager prüfen weiterhin unmittelbar bei Verwendung, weil Dateien und Rechte
sich nach der Vorabprüfung ändern können. Anfragehashes, Grants und
Idempotenzschlüssel bleiben unverändert; fertige alte Tasks laufen nicht neu.

## Fehlerbericht aus vorhandenen Daten

**`task_get`** ergänzt für failed/unknown/blocked einen kompakten `diagnostic`-
Block. **`task_diagnose`** liefert nur die reduzierte Diagnose für einen eigenen
Task; fremde Principals bleiben ausgeschlossen. Lokaler, rein lesender Weg:

```sh
kirabridge --principal chatgpt diagnose codex-open-review-read-20261018-1243
```

Der Bericht enthält Vorgangs-/Taskkennung, Berichtszeit, Operation/Fehlercode,
persistierte Annahme-/Start-/Abschlusszeiten, Quittung und tatsächlichen Status,
Ausführungsruntime mit Version/Konfigurations-/Quellfingerabdrücken sowie
Auditreferenzen zur Vorabprüfung und beobachteten Verbindung. Die lesende Runtime
ist getrennt. Bei historischen Tasks ohne Runtimebeleg bleibt die damalige
Ausführungsruntime **unbekannt**. `unknown` ist kein erfolgreicher Abschluss.
Abgewiesene Einreichungen vor Persistierung erhalten einen gesonderten Bericht,
ohne eine Annahme zu erfinden. Bei vorhandener eigener Task-ID wird der bereits
gespeicherte Zustand berücksichtigt. Transportfehler berichten den fremden
Taskzustand als unbekannt, nicht als nachweislich ungestartet.

Kein `args`, Prompt, Dateiinhalt, Kommandozeilenargument oder roher Exceptiontext
im Diagnose-/Beobachtungsbeleg. Taskinhalt bleibt im bisherigen privaten
Taskstore und den ausdrücklich autorisierten normalen Dateiwerkzeugen verfügbar.
Benötigte Pfade werden nur in der angeforderten Bereitschaftsantwort konkret
gezeigt; im Audit stehen Ressourcenfingerabdrücke. Hashes sind Zuordnungshilfen,
keine Behauptung vollständiger Anonymität.

## Verbindung und tatsächliches Laden

Eigene MCP-Clientkomponenten beobachten `connect.started`, geöffneten
Transportkontext, `initialize.started`, dessen Antwort, `initialized.sent`,
Bereitschaft, Aufruf/Antwort oder unklaren Ausgang, Abbruch und Schließen.
Gemeinsame Verbindungskennung und Vorgängerkennung ordnen einen Reconnect zu;
Taskkennungen verbinden Toolaufrufe mit vorhandenen Belegen. `initialized.sent`
bedeutet Rückkehr des SDK-Sendens, **keine fremde Empfangsbestätigung**.
HTTP-Kontextöffnung ist kein behaupteter TLS-/Endpunkt-Funktionstest.

Diese Beobachtung gilt insbesondere für den eigenen lokalen Proxy→Dispatcher
und eigene CLI-MCP-Verbindungen. Native Tunnel-/Cloud-/Frontend-Ereignisse, die
hier nicht beobachtbar sind, bleiben `unknown`. Alte bereits laufende fremde
CLI-Proxies werden nicht beendet oder rückwirkend instrumentiert. Kein
globaler ChatGPT-Trace aus lokalen Kennungen konstruiert.

Der Dispatcher hält tatsächliches Laden unter `diagnostic.runtime.loaded` in
derselben Audit-Kette fest: Runtimekennung, vorheriger Ladebeleg, Dateihash der
Konfiguration, Hash wirksamer Werte, Quellhash und Änderungsunterschiede. Ein
CLI-Abgleich einer abweichenden lokalen Datei erzeugt `config.observed_drift`;
das behauptet noch kein Laden. Wer eine außerhalb der Bridge bearbeitete Datei
geändert hat, bleibt unbekannt. Keine Tokens oder vollständigen Configpfade
werden in diesen Metadaten gespeichert.

## Begrenzung, Rotation und Aufbewahrung

Additive optionale Konfiguration, keine Secrets; Standardwerte gelten bereits:

```toml
[diagnostics]
enabled = true
max_events_per_day = 2000
max_records = 20000
```

Neue zusätzliche Beobachtungseinträge sind auf4096Bytes,2000/UTC-Tag und20000
insgesamt begrenzt. Nur eigene bekannte Metadatenfelder; Auslassungen/
Budgeterschöpfung erscheinen im Readiness-/Health-Status. Ein Loggingfehler
verwandelt einen erfolgreichen Toolaufruf nicht in eine Wiederholung. Die
bestehende Task-/Auditbelegkette und der kompakte Runtimebezug pro Task bleiben
die dauerhafte Quelle; deren historische Aufbewahrung wird nicht still geändert.

Rotation/Archivierung derselben Kette erfolgt ausdrücklich, begrenzt und ohne
Überschreiben oder automatische Löschung:

```sh
kirabridge audit --export /absoluter/privater/ordner/audit-0001.json --after 0 --limit 500
```

Maximal1000Datensätze und etwa1MB je0600-Segment, mit Originalsequenzen,
Vorgänger-/Datensatzhashes und `next_cursor` für das nächste Segment. Ein zu
großer einzelner historischer Datensatz wird verständlich abgelehnt, statt einen
unbeweglichen Cursor als Fortschritt auszugeben. Die Datenbank wird dabei nicht
gekürzt. Es gibt keinen zweiten laufenden Logger. Bei ausgeschöpftem Gesamtbudget
sind exportierte Einträge weiterhin in der DB erhalten; weitere Beobachtungen
stoppen bis zur bewussten Betreiberentscheidung über Budget und Aufbewahrung.
Eine automatische Löschfrist für historische Belege wurde nicht erfunden.

## Grenzen und Rückweg

Verbindungsfehler wiederholen niemals automatisch einen unklaren Schreibauftrag.
Zuerst ursprüngliche Task-ID lesen; neue Verbindung ist kein neuer Auftrag.
Gezielte Tests decken die bisherigen Pfad-/Programmfehler, Ownergrenzen,
Initialisierungstimeout, verlorene Antwort nach dauerhafter Annahme, Reconnect,
Budget/Export, Quellenzuordnung und Metadatensparsamkeit ab. Keine erneute
Hilfezentrum-/Provider-/Grok-Arbeit und kein erneuter ChatGPT-Dateiabnahmelauf.

Schema bleibt2; nur zusätzliche SQLite-Indizes und Auditmetadaten, keine
Umschreibung alter Taskzeilen. Rückweg auf0.5.1 bei ruhender aktiver/wartender
Task-/Empfängerqueue über den gesicherten vorherigen Quellstand. Falls später
ein `[diagnostics]`-Block ausdrücklich ergänzt wurde, vor alter Software nur
diesen unbekannten Block zurücknehmen. Keine DB-/Credentialrücksicherung;
Lesefreigaben und der bestehende Tunnel-Initialisierungsadapter bleiben erhalten.
Auslieferungs-/Prüfbelege werden nach der gezielten Aktivierung hier verlinkt.
