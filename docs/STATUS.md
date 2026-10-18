# Abnahmestand 0.5.1

Fortschreibung18.10.2026: Geladener lokaler Quell-/Konfigurationsstand geprüft,
Projektlesen für `chatgpt` korrigiert, zusätzliche reine Lesepfade ohne neue
Schreib-/Programmrechte. Neuer Readiness-Abgleich, sicherer Proxy-Reconnect und
persistenter Stdio-Benachrichtigungsadapter.15 gezielte lokale Prüfungen und die
vorhandene CI auf drei Plattform-/Python-Kombinationen bestanden. Echter Datei-
und Ergebnisabruf über die verbundene App dieser Codex-Sitzung nachgewiesen;
separater Ziel-ChatGPT-/iPhone-Abruf bleibt ausdrücklich ausstehend. Kein neuer
Agentenauftrag. [Ursachen, Belege, genauer Abruf und Rückweg](REPAIR-PROJECT-ACCESS-20261018.md).

Die folgenden Abschnitte erhalten den historischen Stand0.5.0:

Stand: 17. Oktober 2026. Grundlage bleibt der [Entwicklungsplan](DEVELOPMENT_PLAN.md). Der frühere rein paketbezogene Stand ist in [STATUS-v0.1.md](STATUS-v0.1.md) archiviert.

## Direkter Agentenkanal

Version 0.5.0 stellt `message_send`, `message_receive`, `message_ack`, `message_get`, `conversation_get`, `message_events` und `message_channel_status` bereit. Die vorhandenen Zugänge `codex` und `grok` sind gegenseitig freigeschaltet; beide behalten den automatischen Freigabemodus. SQLite-Schema 2 speichert adressierte Nachrichten, Reihenfolge, Quittungen und begrenzte Empfängerjobs getrennt von bestehenden Aufgaben. Die frühere Aufgabenhistorie wird bei der atomaren Migration nicht umgeschrieben.

Ein echter authentifizierter Austausch Codex → Grok → Codex ist mit zwei separaten CLI-Arbeitssitzungen und beiden Empfangsquittungen nachgewiesen. Ein tatsächlicher Dienstneustart erhält eine zusätzliche unquittierte Nachricht samt ID und Quittung; wiederholtes Senden erzeugt keine zweite Nachricht. Unauthentifizierter Zugriff, Zugriff durch `chatgpt`, gefälschte Absender und falsche Quittierungen wurden zurückgewiesen. Die bestehende Grok-Hilfezentrum-Arbeit wurde nicht angesprochen oder dupliziert. Die neue Anbindung greift nicht auf bereits laufende interaktive Sitzungen zu. [Bedienung und tatsächliche Grenzen](AGENT_CHANNEL.md), [konkrete Belege](evidence/agent-channel-2026-10-17.json).

## Auf dem Ziel-Mac eingerichtet und geprüft

- KiraBridge ist als globaler CLI-Befehl verfügbar und läuft unter `com.kirabridge.bridge` im Benutzer-launchd. Autostart erfolgt bei Anmeldung, Wiederanlauf nach einem Fehler automatisch.
- Der Dienst bindet ausschließlich an `127.0.0.1:8765`. Ein echter nicht authentifizierter HTTP-Aufruf wurde mit 401 abgewiesen. Konfiguration und separate Tokens haben Modus 0600, das Zustandsverzeichnis 0700.
- `~/workspace/KiraBridge` ist der freigegebene Arbeitsbereich. Lokale Kurzbefehle für Dateien, Terminal, Clipboard und Agenten funktionieren ohne manuell erstellte JSON-Dateien.
- Echte Codex- und Grok-Aufträge wurden erfolgreich abgeschlossen, mit jeweils eigener Agenten-/Sitzungsidentität und echtem Abschlussbeleg.
- Codex hat `bridge_health` als nativer MCP-Client aufgerufen. Groks MCP-Doctor meldet einen erfolgreichen Handshake und zwölf erkannte Tools. Beide Konfigurationen verwenden tokenfreie Stdio-Proxies zum gemeinsamen Dienst.
- Ein realer SIGKILL des neu installierten KiraBridge-Dienstes wurde durch launchd behoben. Eine offene MCP-Anfrage blieb nach dem Neustart gesperrt und lief erst nach lokaler Freigabe. Der andere Agent durfte das Ergebnis nicht lesen.
- Datei-Schreiben/-Lesen und Terminalausführung wurden am echten Dienst geprüft. Clipboard-Fähigkeiten wurden ohne Auslesen oder Verändern persönlicher Inhalte abgefragt.
- Der private OpenAI-Tunnel ist eingerichtet. Die lokale Prüfung bestätigt laufenden Prozess, Health und Readiness; OpenAI-Discovery-Anfragen wurden an KiraBridge weitergeleitet. Lokale Tunnel-Metriken belegen außerdem echte `tools/call`-Anfragen mit Transportstatus 200. Der Nutzer meldet eine erfolgreiche Statusabfrage aus seinem ChatGPT-Chat mit Version 0.2.0 und aktivem Dispatcher. Der genaue Werkzeugname und dessen Ergebnis werden durch die Metriken allein nicht belegt.

Die konkreten Task-IDs, Sitzungsbelege und Prüfergebnisse stehen im [Betriebsnachweis](evidence/local-operation-2026-10-17.json). Private Konfiguration, Zugangsdaten und persönliche Inhalte sind nicht Bestandteil dieses Repositories.

## Freigaben auf diesem Mac

Auf ausdrücklichen Nutzerwunsch ist ab 0.4.0 für `chatgpt`, `codex`, `grok` und `local` dauerhaft `approval_mode = "automatic"` eingerichtet. Neue erlaubte Aufträge starten ohne einzelnen Browserklick oder Freigabetoken. MCP-Health, Operationskatalog und Oberfläche zeigen diesen Modus; `task_request` meldet `approval_required=false`. Authentifizierung, Fähigkeiten, erlaubte Programme und Verzeichnisse, Ressourcenlimits und Schutz gegen doppelte Ausführung bleiben aktiv. Neu angelegte Zugänge verwenden weiterhin standardmäßig `manual`. Die private Konfiguration ist gesichert; der Modus lässt sich lokal zurücknehmen. Die nachfolgenden Browsernachweise dokumentieren weiterhin den zusätzlich verfügbaren manuellen Modus.

Vier echte Terminal-Prüfaufträge wurden unter den vier Zugängen ohne Freigabetoken oder manuellen Freigabeaufruf abgeschlossen, jeweils mit Exitcode 0 und nur einem Ausführungsversuch. Codex und Grok wurden dabei über ihre stdio-Proxies zum gemeinsamen HTTP-Dienst angesprochen; es wurden keine Agenten- oder Modellaufrufe gestartet. Die bisherigen 16 Auftragsdatensätze und bestehenden Agentenprozesse blieben unverändert, der private Tunnel bereit. Ein isolierter Chrome-Test bestätigt die sichtbare Anzeige „Ohne Freigabeklick“ für alle vier Zugänge ohne JavaScript-Ausnahme. Der [Nachweis zum automatischen Modus](evidence/automatic-mode-2026-10-17.json) enthält die konkreten Aufträge und Prüfgrenzen.

[KiraBridge Freigaben öffnen](http://127.0.0.1:8766/). Der getrennte Benutzer-Dienst `com.kirabridge.approvals` bindet ausschließlich an Loopback. `kirabridge approvals` meldet den Browser über eine private, kurzlebige Einmal-Datei an; „KiraBridge Freigaben.command“ auf dem Schreibtisch öffnet die Seite erneut. Einmal angemeldet bleibt die Browserberechtigung 30 Tage gültig, auch bei einem Dienstneustart.

Anfragen erscheinen automatisch. Im manuellen Modus werden die vollständigen Angaben vor einer Entscheidung geladen; die Freigabe ist atomar an den dargestellten Anfragehash gebunden. Auf der Seite werden der tatsächliche Zustand, Empfangsbestätigung, Ergebnis und Ausführungsbeleg angezeigt. Die Agenten erhalten den Link auch direkt in `task_request` und `bridge_health`. Es ist kein Kopieren von IDs zwischen Chats erforderlich.

Ein echter Dateilistenauftrag wurde über MCP mit Principal `chatgpt` angefragt, über die lokale Browser-API freigegeben und vom vorhandenen Dispatcher abgeschlossen. Ein zusätzlicher Test in einem isolierten Chrome-Profil hat die lokale Anmeldung, das Öffnen der Angaben, den tatsächlichen Klick auf „Auftrag freigeben“, den automatischen Statuswechsel und das sichtbare Ergebnis geprüft; es gab keine JavaScript-Ausnahmen. Dieser lokale Browsertest ist kein zusätzlicher Aufruf aus einer ChatGPT-Unterhaltung. Die [konkreten Belege](evidence/local-console-2026-10-17.json) halten Herkunft und Grenzen fest. Es wurden keine Modell-API-Aufrufe ausgelöst.

Der anschließend gemeldete Fehler `executable_denied` beim Codex-Terminalabruf ist auf diesem Mac behoben: In der tatsächlich vom LaunchAgent geladenen privaten Konfiguration wurde ausschließlich `/usr/bin/osascript` für `chatgpt` ergänzt. Der bereits gestartete Codex-Reparaturauftrag hatte die Ursache bestätigt, konnte in seiner lesbaren Sitzung aber keine Änderung speichern. Nach dessen Abschluss wurde die Konfiguration gezielt korrigiert. Ein neuer, einzeln freigegebener MCP-Prüfauftrag las über JavaScript for Automation 893 Zeichen aus einem passenden Terminal-Tab und endete mit Exitcode 0. Die vorhandenen zwölf Auftragsdatensätze blieben unverändert; die bestehenden Codex-/Grok-Prozesse liefen weiter. AppleScript selbst fehlt auf diesem Mac weiterhin, deshalb benötigen solche Terminalabfragen ausdrücklich `-l JavaScript` und ein passendes Skript. [Nachweis und Prüfgrenzen](evidence/terminal-access-2026-10-17.json).

## Automatische Prüfungen

Lokal auf macOS 15.7.4, Intel x86_64, Python 3.11.15: **107 Tests bestanden in 24,55 Sekunden**. Ruff und Paketbau sind erfolgreich. Zusätzlich zu den bisherigen Sicherheits- und Wiederherstellungstests werden Pending-Freigaben, Zurückweisung, geschützte lokale Einrichtung, gemeinsam verwendete Stdio-Proxies und die Geheimnisbehandlung im Kontoverbindungsassistenten geprüft. Weitere Regressionstests decken automatische Freigaben über echte stdio-/HTTP-Verbindungen und Proxies, optionale MCP-Freigabetoken, Rollen-/Pfad-/Programmbegrenzungen, Idempotenz, Auditbelege und unveränderte Wiederherstellung unbekannter Zustände ab. Elf gezielte Kanaltests prüfen den authentifizierten Austausch mit isolierten Testagenten, Quittungen, Eigentümergrenzen, Payload-/Queue-/Schleifengrenzen, parallele Migration, Wiederaufnahme wartender Empfängerjobs und erhaltene Belege unterbrochener Turns. Der manuelle Modus mit browsergebundenen, atomaren Entscheidungen wird weiterhin geprüft.

Die [Verify-Pipeline](https://github.com/landjunge/KiraBridge/actions/workflows/ci.yml) prüft Codeänderungen auf Ubuntu 24.04 mit Python 3.11/3.13 sowie macOS 15 mit Python 3.11. Version 0.5.0 einschließlich Agentenkanal, Empfängeranbindung, atomarer Migration und weiterhin verfügbarem manuellen/automatischen Freigabemodus ist im Commit `a660419` auf allen drei Kombinationen [erfolgreich geprüft](https://github.com/landjunge/KiraBridge/actions/runs/39062642733). Der anschließende reine Nachweis-Commit ändert keinen Programmcode.

Die Leerlaufmessung des Kerns lag auf diesem Intel-Mac bei etwa 56 MiB Spitzenspeicher und 0,03 % eines CPU-Kerns über fünf Sekunden. Das ist keine Lastmessung und enthält nicht den Speicher externer Agentenprozesse. Eine GPU wird nicht benötigt.

## ChatGPT-Nachweis und optionale Erweiterungen

Der offizielle Tunnel-Client v0.0.16 ist einschließlich Begleitprogramm installiert und anhand der Release-Prüfsummen geprüft. Der Nutzer hat den Tunnel und das ChatGPT-Plugin angelegt. Die private Runtime ist lokal als bereit bestätigt. Die erfolgreiche ChatGPT-Statusantwort liegt als Nutzerbericht vor; in dieser Entwicklungssitzung steht das Plugin selbst weiterhin nicht als aufrufbares Werkzeug zur Verfügung. Auftragsfreigabe, Ausführung und Ergebnisabruf aus ChatGPT sind noch nicht gemeinsam geprüft. Die fest ausgegebenen Felder `chatgpt_integration="unverified"` und `chatgpt_tool_call="unverified"` ändern sich durch einen Statusaufruf nicht automatisch.

Der Kontoverbindungsassistent wartet vor dem Tunnelstart auf eine authentifizierte Antwort des lokalen Dispatchers. So wird die nach einem Dienstneustart noch nicht bereite Bridge nicht sofort als ausgefallener MCP-Prozess behandelt. Die Bereitschaftsprüfung wiederholt ausschließlich die Statusabfrage und führt keine Aufträge aus.

Windows-Nativadapter, Bilder/Dateien in der Zwischenablage, interaktive PTYs, zusätzliche Agentenprotokolle/A2A und die optionalen externen Systeme bleiben Erweiterungen. Linux-Clipboard benötigt eine echte grafische Sitzung. Es wurden keine öffentlichen Dienste oder fremden Agenten bereitgestellt beziehungsweise beendet. Bestehende Codex-/Grok-Konfigurationen wurden ausschließlich um KiraBridge ergänzt und zuvor privat gesichert.
