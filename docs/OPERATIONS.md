Aktueller Stand am 20. Oktober 2026: produktiv **0.8.0rc8**, geprüftes Wheel
mit 817 bestandenen Gesamttests, unabhängigen Grok-Abnahmen und praktisch
bestätigtem Kira-Terminal-Rückweg. Die tatsächlichen Aktivierungs- und weiterhin
offenen Handy-/Voice-Nachweise stehen in [der Etappenakte](ARCHITECTURE-STAGES-20261020.md).
Sichtbare Übergaben verwenden ausschließlich die gespeicherte bestehende
Fenster-/TTY-/PID-Zuordnung in der entsperrten Mac-Sitzung. Fehlende Ziele starten
keinen Ersatz. Der koordinierte Neustart wartet auch auf Team-Ergebnisverarbeitung.

Fortschreibung0.5.2: [Workflow-Vorabprüfung, Diagnose und Audit-Rotation](DIAGNOSTICS-20261018.md).

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

# Bereitschaft und Projektdateien

`bridge_health` zeigt Dispatcher/Authentifizierung/Freigabemodus. `automatic`
bedeutet keine Erweiterung der Pfade oder Programme. Der neue authentifizierte
MCP-Aufruf `bridge_readiness` prüft nur die anfragende Identität, beispielsweise:

```json
{
  "read_paths": ["/Users/landjunge/Projects/ki-hilfezentrum/.worktrees/codex-abschluss-20261017T2335/docs/MORGENUEBERGABE-20261018.md"],
  "executables": ["/usr/bin/osascript"]
}
```

Der lokale Abgleich fragt denselben laufenden Dienst ab und vergleicht zusätzlich
geladene Konfiguration und Quellfingerabdruck mit der lokalen Installation:

```sh
kirabridge --principal chatgpt readiness --read-path /Users/landjunge/Projects/ki-hilfezentrum/.worktrees/codex-abschluss-20261017T2335/docs/MORGENUEBERGABE-20261018.md --executable /usr/bin/osascript
```

`path_denied` verlangt einen Pfad innerhalb der expliziten `roots`/`read_roots`.
`path_missing` bezeichnet eine fehlende Datei unter einem zugänglichen Elternpfad;
`path_unavailable`/`path_denied` können auch eine nicht sicher traversierbare
Verzeichniskette oder Symlinks bezeichnen. `forbidden` bedeutet ein fehlendes
Operationsrecht. `executable_denied` ist die beabsichtigte Programmliste;
`executable_unavailable` meldet einen fehlenden/nicht ausführbaren erlaubten Pfad.
`service_matches_local_config_and_source=false` verlangt einen kontrollierten
Abgleich/Reload, keine neue Zugangsdatenvergabe. Ohne konkrete Anforderungen ist
`requested_prerequisites_ready=null`, keine grüne Arbeitsfähigkeitsbescheinigung.
Maximal16 Dateipfade und16 Programme pro Abfrage. Kein Dateiinhalt, Prozessstart,
Auftrag oder Freigabeschreiben entsteht bei dieser Prüfung. Zeitpunktbezogene
Prüfung, keine Funktions-/Tunnel-/ChatGPT-/Dauerhaftigkeitsgarantie.

`roots` bleibt die bestehende allgemeine Dateigrenze und Terminal-CWD-Grenze.
Die additive Principal-Option `read_roots` erweitert nur Lesen/Listen. Auf diesem
Mac wurden am18.10.2026 ausschließlich beim bestehenden Principal `chatgpt`
`/Users/landjunge/KiraBridge` und `/Users/landjunge/Projects`
ergänzt. Damit sind die bestehenden Projektbäume unter `Projects` lesbar,
einschließlich der Hilfezentrum-Worktrees. Nicht das gesamte Home oder `/`. Die alte Konfiguration liegt lokal in
`~/.config/kirabridge/backups/config-before-project-read-roots-20261018.toml`,
ebenfalls0600. Tokens, Programme und fremde Principals sind unverändert.

Zum Lesen **`task_request` mit `operation="file.read"`** verwenden, anschließend
`task_get`/`task_events`. Der genaue freigegebene Abruf steht in
[examples/project-handoff-read.json](../examples/project-handoff-read.json).
`cat` und `/usr/bin/python3` sind dafür nicht erforderlich und wurden nicht
ergänzt. Bereits bestehende Interpreter-/Shellrechte wurden nicht geändert.
`osascript` ist eine eigenständige bereits erlaubte Terminalfunktion; sein Erfolg
belegt keine Dateiwerkzeug-Freigabe und ist kein empfohlener Umgehungsweg.

## Wiederverbindung und unklarer Ausgang

Der eigene Proxy initialisiert eine nachweislich verlorene lokale MCP-Sitzung
**vor** dem nächsten Toolaufruf einmal neu, unter einem gemeinsamen Lock. Ein
bereits gesendeter Aufruf mit unklarem Ausgang wird nie automatisch wiederholt.
Nach Wiederverbindung zuerst `task_get`/`task_events` mit der ursprünglichen ID
lesen. Falls eine Einreichung erneut erforderlich ist, nur die unveränderte
Anfrage mit derselben ID und demselben Idempotenzschlüssel verwenden.

Der beobachtete Tunnel-HTTP409 `mcp_initialization_required` ist getrennt von
`path_denied`/`executable_denied`. Der eigene MCP-HTTP-Dienst läuft stateless;
er definiert diesen409-Code nicht. Der installierte `tunnel-client`v0.0.16
definiert genau diesen Code im Stdio-Initialisierungsschutz: Ein Legacy-Aufruf
vor erfolgreichem Initialize **und** Abschlussbenachrichtigung wird nicht an
das Kind weitergegeben. Seine mitgelieferte Konfigurationsreferenz dokumentiert
`mcp.stdio_send_initialized_notification` (Standardfalse). Der Schalter ist im
bestehenden lokalen Profil jetzttrue. Er sendet nach erfolgreicher Initialisierung
die Abschlussbenachrichtigung und unterdrückt deren spätere Dublette; er erfindet
keine Initialisierung, hebt keinen Guard auf und wiederholt kein Tool.
Der eigene Einrichtungsweg setzt die passende Laufzeitvariable und speichert das
Feld anschließend privat im erzeugten nativen JSON/YAML-Profil: Der native
`runtimes connect`-Generator lässt dieses optionale Feld sonst wieder weg.
Das gilt für unseren Stdio-Proxy mit regulärem MCP-Lifecycle, nicht beliebige
Fremdserver. Kein neuer Schlüssel/Kontoaufbau wurde dafür ausgeführt.

Die erhaltenen Tunnel-Metriken zählen409,
enthalten aber weder Task-ID noch den exakten früheren Timing-Auslöser. Nach
einem Reload trat einmal auch ein Ergebnisabruf-Timeout auf; die bereits
abgeschlossene Aufgabe wurde nicht neu ausgeführt. Im Zielclient muss eine neue
MCP-Verbindung ordnungsgemäß initialisiert werden, bevor wieder Tools gerufen
werden. Das ist keine Aufforderung zur Wiederholung einer Schreibaktion.
Proxy-Fix und Benachrichtigungsadapter sind kein Beweis, dass damit jeder
Cloud-/Tunnel409 beseitigt wäre.
[Offizielle OpenAI-Tunneldokumentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
trennt `/healthz`, `/readyz`, `/metrics` und den tatsächlichen Aufruf aus ChatGPT;
sie spezifiziert dort keinen genauen Auslöser dieses Fehlercodes.

Vor einem Reload aktive/wartende Tasks **und** `message_jobs` prüfen. Bei Arbeit
warten statt Prozesse/Aufträge abzubrechen. Queue/Belege/Credentials beibehalten;
keine Datenbank oder alten Ergebnisse zurückspielen. Ein Quell-Rückweg auf die
vorherige Fassung erfordert zuerst Rücknahme der neuen `read_roots`-Option in
der Konfiguration, weil alte Versionen unbekannte Felder absichtlich ablehnen.


## Begrenzte neue Ausgabehistorie (rc9-Kandidat)

Nach koordinierter Aktivierung gelten die persistenten Werte in
`[output_history]`: `max_bytes=16777216`, `max_entries=256`,
`max_item_bytes=8388608`, `retention_seconds=604800`. Änderungen benötigen
den bestehenden geprüften Aktivierungsweg. Ablauf und FIFO-Verdrängung gelten
nur für neue rohe Terminalausgaben. Taskstatus, fachliche Nachrichten und
historische Audit-Ketten bleiben erhalten. Das Protokoll zeigt Kürzung oder
fehlende Ausgabe; ein abgeschlossener Auftrag wird dadurch nie wiederholt.
`bridge_health.output_history` zeigt die logischen Nutzlastgrenzen, keine
Obergrenze für Datenbankdatei, WAL oder historische Daten.

Kein automatischer Code-Downgrade und kein Zurückspielen einer alten Datenbank.
Vor einem ausdrücklich gewünschten Wechsel auf einen Leser ohne den neuen
Codec: neue Arbeit persistent sperren, laufende Arbeit abwarten, passende
Konfiguration sichern und die im [Etappenbericht](ARCHITECTURE-STAGES-20261020.md)
beschriebene begrenzte Taskresultat-Aufbereitung oder einen kompatiblen Leser
verwenden. Neue Audit-Referenzen brauchen auch danach einen kompatiblen Leser;
der Rückkehrhelfer schreibt historische Audit-Zeilen nicht um.
