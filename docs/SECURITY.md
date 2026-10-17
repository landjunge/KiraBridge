# Sicherheitsmodell und Threat Review

## Vertrauensgrenzen

Das lokale Betriebssystemkonto, die Installation, Konfiguration, Agentenbinärdateien und der lokale Bediener sind vertrauenswürdig. MCP-Clients und ihre Eingaben erhalten ausschließlich konfigurierte Rechte. Agentenrückgaben sind Belege eines konkreten Protokolls, keine allgemeine Autorität. Zugang zum lokalen Konto oder die Möglichkeit, den installierten Python-Code zu ersetzen, liegt außerhalb der Isolation dieses Dienstes.

Ein `terminal.execute`- oder `agent.execute`-Grant ist eine bewusste Freigabe für die Fähigkeiten des gestarteten Programms. KiraBridge ist **kein OS-Sandbox-Ersatz**: Ein erlaubter Interpreter kann andere Dateien lesen oder Programme starten, und ein Kindprozess kann sich einer Prozessgruppe entziehen. `roots` begrenzt Dateiwerkzeuge und das Startverzeichnis; es ist keine behauptete Dateisystem-Isolation für beliebigen Kindcode. Für fremden Code werden ein separates eingeschränktes OS-Konto oder ein Container und eine eigene Agenten-Sandbox benötigt. Codex startet hier im `read-only`-Modus; Grok verweigert angefragte Schreib-/Terminal-/MCP-Berechtigungen. Das ersetzt keine externe Sandbox-Prüfung.

## Umgesetzte Kontrollen

| Bedrohung | Kontrolle und Test |
|---|---|
| Fremder HTTP-Aufrufer | Bearer-Authentifizierung auf jeder Anfrage; mindestens 32 Zeichen; eindeutige Token je Principal |
| Fremde Clientdaten | Jede Task-/Event-/Ergebnisabfrage prüft den gespeicherten Principal; Tests mit zwei echten MCP-Clients |
| Replay und Doppelauftrag | Einmalige zufällige Grants, SHA-256-Hash in SQLite, exakte Bindung an Principal, ID, API-Version und kompletten Inhalt; atomarer Verbrauch |
| Selbst erteilte Rechte | Keine Grant-/Policy-/Adapterinstallations-Werkzeuge über MCP; lokale CLI ist die administrative Grenze |
| Unauthentifizierte Fernsteuerung | Loopback als Standard; andere Bindung nur mit explizitem `allow_remote`, TLS-Zertifikat und Schlüssel |
| DNS-Rebinding/Browseraufrufe | Host- und Origin-Prüfung des MCP SDK; unbekannte Origins werden abgelehnt |
| Symlink-/Traversal-Ausbruch | Absolute erlaubte Pfade, kein `..`, `O_NOFOLLOW` an jedem Traversierungsschritt; Operationen relativ zu offenen Verzeichnisdeskriptoren |
| Zugriff auf Bridge-Datenbank | Zustandsverzeichnis vom Dateigateway ausgeschlossen, auch wenn eine konfigurierte Root darüber liegt |
| Unbeabsichtigtes Löschen | `file.delete` als separate Capability, exakt gebundener Grant, kein rekursives Löschen; keine automatischen Datenbereinigungen |
| Implizite Shell-Injection | Argumentlisten, keine Shell-Interpretation; absolute erlaubte Executables; Tests mit Shell-Metazeichen |
| Hängende oder laute Prozesse | Zeit-/Ausgabelimits, getrennte Prozessgruppen, reservierter Steuerungs-Worker, Stream-Cleanup |
| Secrets in Umgebung/Logs | Terminalumgebung wird neu aufgebaut; Agenten erhalten nur notwendige Auth-Variablen; keine Payloads, Token, Header oder rohen Exception-Texte im Audit |
| Stiller falscher Abschluss | Abschluss nur mit Rückgabebeleg; unbekannte Providerantworten und Verbindungsabbrüche werden nicht automatisch erneut ausgeführt |
| Clipboard-Ausspähung | Jede Inhaltslesung benötigt einen eigenen Grant; `clipboard_info` liest keine Inhalte; kein Polling |
| Ressourcenüberlastung | Eingabe-, Ausgabe-, Queue-, Verbindungs- und HTTP-Limits |

## Daten und Zugangsdaten

Das Datenverzeichnis muss dem Konto gehören und Modus 0700 haben; die SQLite-Datei hat Modus 0600. Eine SQLite-Datenbank ist nicht automatisch verschlüsselt. Sie enthält die für Wiederherstellung erforderlichen Auftragsargumente und autorisierten Ergebnisse; diese können vertrauliche Texte enthalten. Das Audit enthält stattdessen nur eng definierte Metadaten und Hashes. Geheimnisse gehören in den OS-Secret-Store oder dedizierte Umgebungsvariablen, nicht in Prompts, argv, Git oder Audit-Referenzen. Vollverschlüsselung des Datenträgers und separate OS-Konten schützen gespeicherte Nutzdaten zusätzlich.

Die Audit-Kette erkennt Veränderungen in vorhandenen Einträgen. Ein lokaler Administrator kann die gesamte Kette neu schreiben oder ihr Ende entfernen; für Beweissicherung gegen diesen Administrator muss der ausgegebene Head-Hash extern verankert werden. KiraBridge behauptet keine manipulationssichere externe Beglaubigung.

`scripts/serve_keychain.py` kann einen bereits vorhandenen macOS-Keychain-Eintrag in die Umgebung des HTTP-Dienstes übernehmen. Unter Linux kann eine private systemd-`EnvironmentFile` verwendet werden. Beispiel-Service-Dateien sind Vorlagen und werden nicht automatisch installiert.

## Fernzugriff

Die direkte TLS-Implementierung ist für authentifizierte private Verbindungen vorgesehen. Zertifikatsprüfung ist im Client aktiv; eine private CA kann als `Peer.ca_file` angegeben werden. Proxy-Umgebungsvariablen werden für ausgehende Provider-/MCP-HTTP-Verbindungen nicht übernommen. Weiterleitungen dürfen keine Entscheidung über neue fremde Ziele ersetzen.

Dieser Threat Review ist eine interne Entwurfsprüfung, kein unabhängiges Penetrationstest-Zertifikat. Es wurde kein öffentlicher Dienst, Tunnel oder Portforwarding eingerichtet. Eine spätere Internetbereitstellung erfordert ausdrücklich freigegebene Infrastruktur und passende OAuth-/Netzwerkregeln.


## Lokaler Betrieb 0.2.0

Der eingerichtete Dienst lädt getrennte, zufällige Tokens aus einer eigenen Datei unter dem privaten Konfigurationsverzeichnis. Die Datei wird mit `O_NOFOLLOW` geöffnet, Eigentümer und Modus werden geprüft; ihr Inhalt wird nicht ausgegeben. MCP-Stdio-Proxies lesen nur ihre konfigurierte Identität aus diesem Store und verbinden sich ausschließlich zu einem Loopback-Endpunkt. Globale Codex-/Grok-Konfigurationen enthalten keine Tokens.

Pending-Anfragen sind keine Genehmigungen. Sie werden anhand des Operationsrechts geprüft, zählen zur Queue-Grenze und starten erst nach lokalem `approve`. Die Freigabe wird mit dem ursprünglichen Anfragehash auditiert. Selbstfreigaben über MCP sind nicht implementiert. `pending` und `approve` sind lokale administrative Befehle und setzen das vertrauenswürdige OS-Konto voraus.
