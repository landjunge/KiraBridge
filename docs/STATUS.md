# Abnahmestand 0.2.0

Stand: 17. Oktober 2026. Grundlage bleibt der [Entwicklungsplan](DEVELOPMENT_PLAN.md). Der frühere rein paketbezogene Stand ist in [STATUS-v0.1.md](STATUS-v0.1.md) archiviert.

## Auf dem Ziel-Mac eingerichtet und geprüft

- KiraBridge ist als globaler CLI-Befehl verfügbar und läuft unter `com.kirabridge.bridge` im Benutzer-launchd. Autostart erfolgt bei Anmeldung, Wiederanlauf nach einem Fehler automatisch.
- Der Dienst bindet ausschließlich an `127.0.0.1:8765`. Ein echter nicht authentifizierter HTTP-Aufruf wurde mit 401 abgewiesen. Konfiguration und separate Tokens haben Modus 0600, das Zustandsverzeichnis 0700.
- `~/workspace/KiraBridge` ist der freigegebene Arbeitsbereich. Lokale Kurzbefehle für Dateien, Terminal, Clipboard und Agenten funktionieren ohne manuell erstellte JSON-Dateien.
- Echte Codex- und Grok-Aufträge wurden erfolgreich abgeschlossen, mit jeweils eigener Agenten-/Sitzungsidentität und echtem Abschlussbeleg.
- Codex hat `bridge_health` als nativer MCP-Client aufgerufen. Groks MCP-Doctor meldet einen erfolgreichen Handshake und zwölf erkannte Tools. Beide Konfigurationen verwenden tokenfreie Stdio-Proxies zum gemeinsamen Dienst.
- Ein realer SIGKILL des neu installierten KiraBridge-Dienstes wurde durch launchd behoben. Eine offene MCP-Anfrage blieb nach dem Neustart gesperrt und lief erst nach lokaler Freigabe. Der andere Agent durfte das Ergebnis nicht lesen.
- Datei-Schreiben/-Lesen und Terminalausführung wurden am echten Dienst geprüft. Clipboard-Fähigkeiten wurden ohne Auslesen oder Verändern persönlicher Inhalte abgefragt.

Die konkreten Task-IDs, Sitzungsbelege und Prüfergebnisse stehen im [Betriebsnachweis](evidence/local-operation-2026-10-17.json). Private Konfiguration, Zugangsdaten und persönliche Inhalte sind nicht Bestandteil dieses Repositories.

## Automatische Prüfungen

Lokal auf macOS 15.7.4, Intel x86_64, Python 3.11.15: **77 Tests bestanden in 16,97 Sekunden**. Ruff und Paketbau sind erfolgreich. Zusätzlich zu den bisherigen Sicherheits- und Wiederherstellungstests werden Pending-Freigaben, Zurückweisung, geschützte lokale Einrichtung, gemeinsam verwendete Stdio-Proxies und die Geheimnisbehandlung im Kontoverbindungsassistenten geprüft.

Die [Verify-Pipeline](https://github.com/landjunge/KiraBridge/actions/workflows/ci.yml) prüft jeden Commit auf Ubuntu 24.04 mit Python 3.11/3.13 sowie macOS 15 mit Python 3.11. Die vorangegangenen Kernimplementierungen sind auf allen drei Kombinationen grün; der aktuelle Commit trägt seinen eigenen CI-Nachweis.

Die Leerlaufmessung des Kerns lag auf diesem Intel-Mac bei etwa 56 MiB Spitzenspeicher und 0,03 % eines CPU-Kerns über fünf Sekunden. Das ist keine Lastmessung und enthält nicht den Speicher externer Agentenprozesse. Eine GPU wird nicht benötigt.

## Verbleibende Kontoverbindung und optionale Erweiterungen

Die direkte ChatGPT-Verbindung ist **noch nicht nachgewiesen**. Der offizielle Tunnel-Client v0.0.16 ist einschließlich Begleitprogramm installiert und anhand der Release-Prüfsummen geprüft. Es fehlen die autorisierte Tunnel-/Workspace-Verbindung und ein tatsächlicher Toolaufruf aus ChatGPT. `kirabridge chatgpt setup` führt die einmalige Kontoeinrichtung lokal durch; kein Schlüssel gehört in den Chat. Der Assistent und seine Geheimnis-/Statusprüfungen sind getestet, ein echtes Account-Linking ohne vorhandenen Zugang wird nicht behauptet.

Windows-Nativadapter, Bilder/Dateien in der Zwischenablage, interaktive PTYs, zusätzliche Agentenprotokolle/A2A und die optionalen externen Systeme bleiben Erweiterungen. Linux-Clipboard benötigt eine echte grafische Sitzung. Es wurden keine öffentlichen Dienste oder fremden Agenten bereitgestellt beziehungsweise beendet. Bestehende Codex-/Grok-Konfigurationen wurden ausschließlich um KiraBridge ergänzt und zuvor privat gesichert.
