# Eingerichteter Betrieb ab 0.3.0

Auf dem Ziel-Mac wurden `kirabridge setup` und `kirabridge service install` ausgeführt. Der Dienst `com.kirabridge.bridge` läuft unter dem angemeldeten Benutzer und startet nach einem Fehler automatisch neu. Er bindet ausschließlich an `127.0.0.1:8765`; jede HTTP-Anfrage benötigt Authentifizierung.

Standarddateien: `~/.config/kirabridge/config.toml` (0600), `credentials.json` daneben (0600), Zustandsverzeichnis `~/.local/share/kirabridge` (0700), Arbeitsbereich `~/workspace/KiraBridge`. `local`, `codex` und `grok` haben getrennte Bearer-Identitäten. Agenten-MCP-Konfigurationen enthalten nur `kirabridge --principal NAME connect`, keine Token. Der Proxy verwendet den vorhandenen gemeinsamen Dispatcher.

`kirabridge status` fragt den laufenden Dienst ab. `ls`, `read`, `write`, `exec`, `ask` und `clipboard` sind lokale Komfortbefehle. Sie geben für den konkret vom lokalen Bediener gewählten Inhalt eine auftragsgebundene Freigabe und warten auf den tatsächlichen Ausgang. Bestehende Dateiinhalte werden nur mit `write --overwrite` ersetzt. Zusätzliche Verzeichnisse werden ausdrücklich in der privaten Konfiguration freigegeben.

MCP-Clients können `task_request` nutzen. Im Standardmodus `manual` wird die Anfrage dauerhaft als `created` gespeichert; die Antwort enthält den lokalen Freigabelink. Der Bediener öffnet [KiraBridge Freigaben](http://127.0.0.1:8766/), sieht dort automatisch die Anfrage, öffnet ihre vollständigen Angaben und entscheidet mit „Auftrag freigeben“ oder „Ablehnen“. Ergebnisse und Statuswechsel erscheinen anschließend auf derselben Seite. Als CLI-Alternative stehen `pending`, `approve TASK_ID` und `deny TASK_ID` bereit. Der MCP-Server bietet kein Tool zur Selbstfreigabe an. Pending-Anfragen zählen zur Queue-Quote und bleiben nach einem Neustart ungeprüft.

Ab Version 0.4.0 erlaubt `approval_mode = "automatic"` unter `[principals.<zugang>]` neue Aufträge innerhalb der eingerichteten Funktionsrechte ohne einzelne Freigabeklicks. Auf diesem Mac wurde dies auf ausdrücklichen Nutzerwunsch für `chatgpt`, `codex`, `grok` und `local` aktiviert. `task_request` stellt erlaubte Arbeit direkt als `queued` ein und meldet `approval_required=false`; `task_submit`, `clipboard_read` und `clipboard_write` benötigen dann keinen Freigabetoken. Ein ausdrücklich mitgesendeter Token wird weiterhin auf Gültigkeit und einmalige Nutzung geprüft. `bridge_health` und `operation_catalog` zeigen den Modus des authentifizierten Zugangs. Die Oberfläche nennt die automatisch freigegebenen Zugänge.

Der Modus ist eine dauerhafte lokale Berechtigungsentscheidung, kein zweiter Dispatcher: Authentifizierung, erlaubte Fähigkeiten, Programme und Verzeichnisse, Quoten, Zustandsbelege und Idempotenz bleiben aktiv. Automatische Entscheidungen stehen mit Anfragehash und Quelle `principal_policy` als `task.auto_approved` im Audit. Bereits fehlgeschlagene, abgebrochene oder unbekannte Aufträge werden nicht neu gestartet. Zur Rücknahme `approval_mode = "manual"` setzen und den Dienst ohne laufende Aufträge neu starten. Dies gilt für neue Anfragen; bereits autorisierte Aufträge verlieren ihre Freigabe dadurch nicht. Historische Pending-Anfragen werden durch den Moduswechsel nicht nachträglich ausgeführt.

`kirabridge approvals` richtet den getrennten lokalen Benutzer-Dienst `com.kirabridge.approvals` auf `127.0.0.1:8766` ein und öffnet den Browser. Der Launcher „KiraBridge Freigaben.command“ auf dem Schreibtisch öffnet dieselbe Seite und erneuert bei Bedarf die Browseranmeldung. Unter Linux kann `kirabridge approval-server` im Vordergrund gestartet werden; danach öffnet `kirabridge approvals` die lokale Anmeldung.

Die Oberfläche bleibt außerhalb des MCP-Tunnels. Der lokale Launcher prüft den Dienst kryptografisch, bevor er eine private, kurzlebige Einmal-Anmeldedatei öffnet. Die langfristige lokale Anmeldeberechtigung bleibt mit Modus 0600 im Konfigurationsverzeichnis. Der Browser erhält eine auf diese Oberfläche beschränkte, signierte 30-Tage-Berechtigung in seinem origin-gebundenen lokalen Speicher. Es werden keine Zugangsdaten in Links, Prozessargumenten oder Logs ausgegeben. Bei gesperrten lokalen Browserdaten kann der Browser nicht angemeldet werden; die Seite erklärt dann den erneuten Start über den Schreibtisch.

Echte Codex- und Grok-Aufträge, Codex als nativer MCP-Client, Groks MCP-Doctor sowie ein realer launchd-Neustart wurden geprüft; siehe [Betriebsnachweis](evidence/local-operation-2026-10-17.json).

Die folgende Referenz beschreibt zusätzlich manuelle Konfiguration und Betrieb auf weiteren Rechnern. Die Beispiel-Service-Dateien werden dadurch nicht automatisch auf anderen Rechnern installiert.

# Referenz: Betrieb und Wiederherstellung

## Konfiguration

`kirabridge init CONFIG --workspace EXISTING_DIRECTORY` erstellt eine private, konservative TOML-Datei. Für zusätzliche Funktionen werden in dieser Datei konkrete Capabilities, kanonische absolute Workspace-Pfade, erlaubte Executables und Agentennamen ergänzt. [policy.toml](../examples/policy.toml) zeigt alle Felder. Es gibt keine Wildcard-Rechte. Die Konfiguration wird beim Prozessstart geladen; eine Rechteänderung benötigt einen kontrollierten Neustart.

Terminal- und Agentenrechte sind mächtig: siehe [Vertrauensgrenzen](SECURITY.md). Agentennamen sind frei wählbare eindeutige Identitäten; `kind` bezeichnet das Protokoll. Beispielsweise können zwei separat konfigurierte Codex-Identitäten unterschiedliche Aufträge erhalten, ohne mit Grok oder mit einer vorhandenen fremden Sitzung verwechselt zu werden.

### macOS-Terminal lesen: `executable_denied`

Eine Browserfreigabe erlaubt genau den geprüften Auftrag; sie erweitert nicht die Programmliste des Zugangs. Bei `executable_denied` zuerst den `--config`-Pfad des laufenden Dienstes und dort `principals.<zugang>.executables` prüfen. Für den freigegebenen Terminalabruf auf diesem Mac wurde ausschließlich `/usr/bin/osascript` unter `principals.chatgpt.executables` ergänzt. Andere Zugänge, Fähigkeiten, Verzeichnisse und Einzelauftragsfreigaben wurden nicht erweitert. Die private Originalkonfiguration wurde vor der Änderung gesichert. Der Bridge-Dienst wurde erst nach Abschluss des bereits laufenden Reparaturauftrags und ohne weitere wartende oder aktive Aufträge neu gestartet.

Auf diesem Mac meldet `osascript -l AppleScript` weiterhin `no such component "AppleScript"`. JavaScript for Automation funktioniert: Ein neuer, einzeln freigegebener Auftrag mit `argv=["/usr/bin/osascript", "-l", "JavaScript", "-e", SCRIPT]` konnte über den Zugang `chatgpt` einen anhand von Titel oder Prozessnamen als Codex erkannten Terminal-Tab lesen. Das Skript prüfte zuerst, ob Terminal bereits läuft, las ausschließlich passende Tabs und startete oder veränderte keine Sitzung. Der Nachweis enthält nur Zeichenanzahlen, keine Terminaltexte. Ein passender Titel oder Prozessname belegt keinen laufenden Agentenauftrag.

AppleScript-Aufträge werden nicht automatisch umgeschrieben oder erneut ausgeführt. Geänderte Skriptargumente benötigen eine neue Anfrage und eine eigene Freigabe; der fehlgeschlagene Vorgänger bleibt dokumentiert und wird über `parent_id` verknüpft. Die konkreten Ergebnisse und Grenzen stehen im [Terminalzugriff-Nachweis](evidence/terminal-access-2026-10-17.json).

Codex wird als absoluter CLI-Pfad konfiguriert. Der Adapter nutzt `exec --json`, stdin für Prompts, `--ignore-user-config`, `--ignore-rules` und `--sandbox read-only`. Grok Build nutzt `agent stdio` mit ACP v1; clientseitige Datei-/Terminalfähigkeiten werden nicht angeboten, Rechteanfragen abgelehnt und Subagenten deaktiviert. Vorhandene eigene CLI-Authentifizierung wird ausschließlich durch die entsprechende CLI verwendet. Alternativ benötigt `grok_api` eine explizite Modell-ID und eine Umgebungsvariable für den xAI-Schlüssel; dieser Adapter liefert Text und führt keine lokalen Tools aus.

CLI-Flags und Protokolle können sich ändern. Ein unbekanntes Ereignis darf nicht zu erfundenem Erfolg führen. Nach einem CLI-Upgrade müssen die Adapter-Smokes mit dem freigegebenen Providerkonto separat nachgewiesen werden. Die automatischen Tests verursachen keine Provideraufrufe. Die getrennten manuellen Betriebsprüfungen auf diesem Mac sind im Nachweis dokumentiert.

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

Nur ein Dispatcher pro Datenverzeichnis; mehrere MCP-HTTP-Clients teilen denselben Dispatcher. Separate stdio-Prozesse benötigen eigene Zustandsverzeichnisse. `doctor` meldet Schema, Auditstatus und konfigurierte Identitäten, nicht erfundene aktive Agenten. `status` fragt dagegen den laufenden Dispatcher tatsächlich über MCP ab.

Vor Sicherungen den Dienst kontrolliert stoppen oder die SQLite-Backup-API verwenden; eine einzelne Kopie der Datenbank bei aktivem WAL ist keine vollständige Sicherung. Es wird keine automatische Löschung historischer Aufgaben vorgenommen. Die Queue ist in der Anzahl begrenzt, historische Daten benötigen langfristig einen administrativen Archivierungsplan. Parallelität auf dem älteren iMac kann auf `concurrency=1` gesetzt werden.

