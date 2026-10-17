# Betrieb und Wiederherstellung

## Konfiguration

`kirabridge init CONFIG --workspace EXISTING_DIRECTORY` erstellt eine private, konservative TOML-Datei. Für zusätzliche Funktionen werden in dieser Datei konkrete Capabilities, kanonische absolute Workspace-Pfade, erlaubte Executables und Agentennamen ergänzt. [policy.toml](../examples/policy.toml) zeigt alle Felder. Es gibt keine Wildcard-Rechte. Die Konfiguration wird beim Prozessstart geladen; eine Rechteänderung benötigt einen kontrollierten Neustart.

Terminal- und Agentenrechte sind mächtig: siehe [Vertrauensgrenzen](SECURITY.md). Agentennamen sind frei wählbare eindeutige Identitäten; `kind` bezeichnet das Protokoll. Beispielsweise können zwei separat konfigurierte Codex-Identitäten unterschiedliche Aufträge erhalten, ohne mit Grok oder mit einer vorhandenen fremden Sitzung verwechselt zu werden.

Codex wird als absoluter CLI-Pfad konfiguriert. Der Adapter nutzt `exec --json`, stdin für Prompts, `--ignore-user-config`, `--ignore-rules` und `--sandbox read-only`. Grok Build nutzt `agent stdio` mit ACP v1; clientseitige Datei-/Terminalfähigkeiten werden nicht angeboten, Rechteanfragen abgelehnt und Subagenten deaktiviert. Vorhandene eigene CLI-Authentifizierung wird ausschließlich durch die entsprechende CLI verwendet. Alternativ benötigt `grok_api` eine explizite Modell-ID und eine Umgebungsvariable für den xAI-Schlüssel; dieser Adapter liefert Text und führt keine lokalen Tools aus.

CLI-Flags und Protokolle können sich ändern. Ein unbekanntes Ereignis darf nicht zu erfundenem Erfolg führen. Nach einem CLI-Upgrade müssen die Adapter-Smokes mit dem freigegebenen Providerkonto separat nachgewiesen werden. Die automatischen Tests verursachen keine Provideraufrufe.

## Genehmigen und einreichen

1. Eine `TaskRequest`-JSON-Datei mit stabiler ID und Idempotenzschlüssel erstellen und prüfen.
2. `kirabridge --config CONFIG grant REQUEST.json` lokal ausführen. Der Token gilt standardmäßig 300 Sekunden, maximal 3600 Sekunden.
3. Per MCP mit `task_submit(request, approval)` einreichen; oder den Token als `KIRABRIDGE_APPROVAL` an den lokalen `enqueue`-/`run`-Prozess geben. Tokens nicht in Shell-Historie oder geteilte Logs kopieren.
4. Den Beleg mit `task_get` beziehungsweise `kirabridge ... task TASK_ID` prüfen. `accepted` quittiert den Dispatcherempfang. `running` zeigt einen beobachteten Start. `completed` benötigt ein Ergebnis mit Belegen.

`run REQUEST.json --approve` verbindet für den lokalen Bediener bewusste Freigabe und Ausführung. Läuft bereits ein Dispatcher, wartet die CLI auf dessen persistenten Auftrag; andernfalls startet sie für die Dauer des Auftrags eigene Worker. Ein HTTP-/stdio-Verbindungsabbruch beendet einen persistenten Auftrag nicht.

`operation_catalog` liefert die JSON-Schemas der tatsächlich freigegebenen Operationen. Argumente werden exakt gehasht; ein ausgelassenes Default-Feld und ein ausdrücklich gesetztes Default-Feld sind verschiedene Anfragen. Clipboard-Komfortwerkzeuge konstruieren beispielsweise `{"max_bytes":65536}` für `clipboard_read` und `{"text":"…"}` für `clipboard_write`; der Grant muss genau diese Argumente verwenden.

## Zustände nach Ausfällen

Nach einem Neustart setzt der neue Dispatcher alte `accepted`/`running`-Einträge mit dem letzten bekannten Beleg auf `unknown`. Er hängt sich nicht allein anhand einer möglicherweise wiederverwendeten PID an fremde Prozesse und sendet keine blinden Wiederholungen. Queued-Aufträge sind noch nicht dispatcht und können weiter abgearbeitet werden.

Für `unknown` externe Ergebnisse, passende Agentensitzung und tatsächliche Änderungen kontrollieren. Danach kann ein lokaler Bediener den geprüften Ausgang attestieren:

```sh
kirabridge --config CONFIG reconcile TASK_ID --state completed --evidence inspected-result-reference
```

Diese Referenz wird als lokale Bedienerattestation gekennzeichnet; sie ist kein durch KiraBridge unabhängig erhobener Providerbeweis. Keine Zugangsdaten als Referenz verwenden. Ein unbekannter Auftrag wird dadurch nicht erneut ausgeführt.

## Wiederholungen und Abbruch

Kontrollierte Wiederholungen sind nur erlaubt, wenn ein fehlgeschlagener Auftrag nachweislich **vor dem Start** zurückgewiesen wurde (`safe_to_retry=true`). Eine neue Anfrage muss Operation und Argumente beibehalten, eine neue ID/einen neuen Idempotenzschlüssel erhalten und `parent_id` auf den Vorgänger setzen. Sie benötigt eine eigene Freigabe:

```sh
kirabridge --config CONFIG retry RETRY_REQUEST.json --original ORIGINAL_ID --approve
```

Maximal drei Versuche pro Retry-Kette. Ein Exitcode ungleich null beweist keine nebenwirkungsfreie Ausführung und berechtigt deshalb nicht zu diesem Retry. Ebenso wenig berechtigt ein Verbindungsabbruch dazu. Neue explizit freigegebene Arbeit ist davon getrennt.

`task_cancel` beendet eigene noch wartende Aufgaben. Aktive Prozesse werden durch einen separat freigegebenen `process.terminate`-Auftrag mit `{"task_id":"…"}` beendet. Es gibt keine freie PID-Tötung. Grok ACP und entfernte Provider werden bei Dienstunterbrechung konservativ abgeglichen; ein Provider kann nach einer lokalen Trennung weiterarbeiten.

## Dienste, Sicherungen und Limits

[launchd](../examples/com.kirabridge.bridge.plist) und [systemd](../examples/kirabridge.service) sind nicht installierte Vorlagen für automatischen Dienstneustart. Absolute Pfade und die lokale Secret-Bereitstellung müssen eingesetzt werden. Der macOS-Wrapper erwartet den vorhandenen Keychain-Dienst `KiraBridge`, Account `local`, mit einem starken Token und `token_env="KIRABRIDGE_TOKEN"` in der Konfiguration. Der Token wird nicht als Prozessargument weitergegeben. Für Linux gehört `secrets.env` ausschließlich dem Dienstkonto und hat Modus 0600; eine grafische Clipboard-Sitzung muss ausdrücklich erreichbar sein.

Nur ein Dispatcher pro Datenverzeichnis; mehrere MCP-HTTP-Clients teilen denselben Dispatcher. Separate stdio-Prozesse benötigen eigene Zustandsverzeichnisse. `doctor` meldet Schema, Auditstatus und konfigurierte Identitäten, nicht erfundene aktive Agenten.

Vor Sicherungen den Dienst kontrolliert stoppen oder die SQLite-Backup-API verwenden; eine einzelne Kopie der Datenbank bei aktivem WAL ist keine vollständige Sicherung. Es wird keine automatische Löschung historischer Aufgaben vorgenommen. Die Queue ist in der Anzahl begrenzt, historische Daten benötigen langfristig einen administrativen Archivierungsplan. Parallelität auf dem älteren iMac kann auf `concurrency=1` gesetzt werden.

