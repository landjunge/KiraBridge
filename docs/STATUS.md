# Abnahmestand 0.3.0

Stand: 17. Oktober 2026. Grundlage bleibt der [Entwicklungsplan](DEVELOPMENT_PLAN.md). Der frühere rein paketbezogene Stand ist in [STATUS-v0.1.md](STATUS-v0.1.md) archiviert.

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

[KiraBridge Freigaben öffnen](http://127.0.0.1:8766/). Der getrennte Benutzer-Dienst `com.kirabridge.approvals` bindet ausschließlich an Loopback. `kirabridge approvals` meldet den Browser über eine private, kurzlebige Einmal-Datei an; „KiraBridge Freigaben.command“ auf dem Schreibtisch öffnet die Seite erneut. Einmal angemeldet bleibt die Browserberechtigung 30 Tage gültig, auch bei einem Dienstneustart.

Anfragen aus ChatGPT erscheinen automatisch. Die vollständigen Angaben werden vor einer Entscheidung geladen; die Freigabe ist atomar an den dargestellten Anfragehash gebunden. Auf der Seite werden danach der tatsächliche Zustand, Empfangsbestätigung, Ergebnis und Ausführungsbeleg angezeigt. Die Agenten erhalten den Link auch direkt in `task_request` und `bridge_health`. Es ist kein Kopieren von IDs zwischen Chats erforderlich.

Ein echter Dateilistenauftrag wurde über MCP mit Principal `chatgpt` angefragt, über die lokale Browser-API freigegeben und vom vorhandenen Dispatcher abgeschlossen. Ein zusätzlicher Test in einem isolierten Chrome-Profil hat die lokale Anmeldung, das Öffnen der Angaben, den tatsächlichen Klick auf „Auftrag freigeben“, den automatischen Statuswechsel und das sichtbare Ergebnis geprüft; es gab keine JavaScript-Ausnahmen. Dieser lokale Browsertest ist kein zusätzlicher Aufruf aus einer ChatGPT-Unterhaltung. Die [konkreten Belege](evidence/local-console-2026-10-17.json) halten Herkunft und Grenzen fest. Es wurden keine Modell-API-Aufrufe ausgelöst.

## Automatische Prüfungen

Lokal auf macOS 15.7.4, Intel x86_64, Python 3.11.15: **87 Tests bestanden in 16,97 Sekunden**. Ruff und Paketbau sind erfolgreich. Zusätzlich zu den bisherigen Sicherheits- und Wiederherstellungstests werden Pending-Freigaben, Zurückweisung, geschützte lokale Einrichtung, gemeinsam verwendete Stdio-Proxies und die Geheimnisbehandlung im Kontoverbindungsassistenten geprüft. Zusätzliche Regressionstests decken verzögerte Dispatcher-Bereitschaft, Browserauthentifizierung, Origin-/Host-Schutz, Einmal-Anmeldung, falsche Anfragehashes, doppelte Freigaben, Ablehnung ohne Ausführung und den atomaren Schutz bereits aktiver Aufträge ab.

Die [Verify-Pipeline](https://github.com/landjunge/KiraBridge/actions/workflows/ci.yml) prüft Codeänderungen auf Ubuntu 24.04 mit Python 3.11/3.13 sowie macOS 15 mit Python 3.11. Die Bereitschaftskorrektur `c259ffe` ist auf allen drei Kombinationen [erfolgreich geprüft](https://github.com/landjunge/KiraBridge/actions/runs/39054163072). Die lokale Freigabeoberfläche ab 0.3.0 hat zusätzlich ihren eigenen Code- und Browsernachweis.

Die Leerlaufmessung des Kerns lag auf diesem Intel-Mac bei etwa 56 MiB Spitzenspeicher und 0,03 % eines CPU-Kerns über fünf Sekunden. Das ist keine Lastmessung und enthält nicht den Speicher externer Agentenprozesse. Eine GPU wird nicht benötigt.

## ChatGPT-Nachweis und optionale Erweiterungen

Der offizielle Tunnel-Client v0.0.16 ist einschließlich Begleitprogramm installiert und anhand der Release-Prüfsummen geprüft. Der Nutzer hat den Tunnel und das ChatGPT-Plugin angelegt. Die private Runtime ist lokal als bereit bestätigt. Die erfolgreiche ChatGPT-Statusantwort liegt als Nutzerbericht vor; in dieser Entwicklungssitzung steht das Plugin selbst weiterhin nicht als aufrufbares Werkzeug zur Verfügung. Auftragsfreigabe, Ausführung und Ergebnisabruf aus ChatGPT sind noch nicht gemeinsam geprüft. Die fest ausgegebenen Felder `chatgpt_integration="unverified"` und `chatgpt_tool_call="unverified"` ändern sich durch einen Statusaufruf nicht automatisch.

Der Kontoverbindungsassistent wartet vor dem Tunnelstart auf eine authentifizierte Antwort des lokalen Dispatchers. So wird die nach einem Dienstneustart noch nicht bereite Bridge nicht sofort als ausgefallener MCP-Prozess behandelt. Die Bereitschaftsprüfung wiederholt ausschließlich die Statusabfrage und führt keine Aufträge aus.

Windows-Nativadapter, Bilder/Dateien in der Zwischenablage, interaktive PTYs, zusätzliche Agentenprotokolle/A2A und die optionalen externen Systeme bleiben Erweiterungen. Linux-Clipboard benötigt eine echte grafische Sitzung. Es wurden keine öffentlichen Dienste oder fremden Agenten bereitgestellt beziehungsweise beendet. Bestehende Codex-/Grok-Konfigurationen wurden ausschließlich um KiraBridge ergänzt und zuvor privat gesichert.
