# Sicherheitsmodell und Threat Review

## Vertrauensgrenzen

Das lokale Betriebssystemkonto, die Installation, Konfiguration, Agentenbinärdateien und der lokale Bediener sind vertrauenswürdig. MCP-Clients und ihre Eingaben erhalten ausschließlich konfigurierte Rechte. Agentenrückgaben sind Belege eines konkreten Protokolls, keine allgemeine Autorität. Zugang zum lokalen Konto oder die Möglichkeit, den installierten Python-Code zu ersetzen, liegt außerhalb der Isolation dieses Dienstes.

Ein `terminal.execute`- oder `agent.execute`-Grant beziehungsweise eine dauerhafte automatische Freigabe ist eine bewusste Berechtigung für die Fähigkeiten des gestarteten Programms. KiraBridge ist **kein OS-Sandbox-Ersatz**: Ein erlaubter Interpreter kann andere Dateien lesen oder Programme starten, und ein Kindprozess kann sich einer Prozessgruppe entziehen. `roots` begrenzt Dateiwerkzeuge und das Startverzeichnis; es ist keine behauptete Dateisystem-Isolation für beliebigen Kindcode. Für fremden Code werden ein separates eingeschränktes OS-Konto oder ein Container und eine eigene Agenten-Sandbox benötigt. Der verwaltete Codex-Adapter startet hier im `read-only`-Modus; der verwaltete Grok-Adapter verweigert angefragte Schreib-/Terminal-/MCP-Berechtigungen. Diese Adaptergrenzen sind von Grok/Codex als authentifizierten MCP-Clients zu unterscheiden und ersetzen keine externe Sandbox-Prüfung.

## Umgesetzte Kontrollen

| Bedrohung | Kontrolle und Test |
|---|---|
| Fremder HTTP-Aufrufer | Bearer-Authentifizierung auf jeder Anfrage; mindestens 32 Zeichen; eindeutige Token je Principal |
| Fremde Clientdaten | Jede Task-/Event-/Ergebnisabfrage prüft den gespeicherten Principal; Tests mit zwei echten MCP-Clients |
| Replay und Doppelauftrag | In beiden Modi Idempotenz und Anfragehash je Principal; im manuellen Modus zusätzlich einmalige zufällige Grants mit exakter Bindung und atomarem Verbrauch |
| Selbst erteilte Rechte | Keine Grant-/Policy-/Adapterinstallations-Werkzeuge über MCP; lokale CLI ist die administrative Grenze |
| Unauthentifizierte Fernsteuerung | Loopback als Standard; andere Bindung nur mit explizitem `allow_remote`, TLS-Zertifikat und Schlüssel |
| DNS-Rebinding/Browseraufrufe | Host- und Origin-Prüfung des MCP SDK; unbekannte Origins werden abgelehnt |
| Symlink-/Traversal-Ausbruch | Absolute erlaubte Pfade, kein `..`, `O_NOFOLLOW` an jedem Traversierungsschritt; Operationen relativ zu offenen Verzeichnisdeskriptoren |
| Zusätzlich lesbare Projekte | `read_roots` ergänzt ausschließlich `file.read`/`file.image`/`file.list`; Dateiänderungen und Terminal-CWD verwenden weiterhin nur `roots`. Andere Principals erben diese Freigaben nicht. |
| Entwurfsbilder | Separate `file.image`-Capability; descriptorbasierter Snapshot, begrenzte tatsächliche PNG-Dekompression und komplette MCP-Antwort. Bildbytes liegen nur als autorisiertes Ergebnis in der bestehenden privaten Task-Datenbank; nicht in Audit oder Events. Nur eigene abgeschlossene Bildaufträge erzeugen MCP-`ImageContent`. [Grenzen und Abnahme](IMAGE-READ-20261018.md). |
| Zugriff auf Bridge-Datenbank | Zustandsverzeichnis vom Dateigateway ausgeschlossen, auch wenn eine konfigurierte Root darüber liegt |
| Unbeabsichtigtes Löschen | `file.delete` als separate, standardmäßig fehlende Capability; konfigurierter Freigabemodus, kein rekursives Löschen und keine automatischen Datenbereinigungen |
| Implizite Shell-Injection | Argumentlisten, keine Shell-Interpretation; absolute erlaubte Executables; Tests mit Shell-Metazeichen |
| Hängende oder laute Prozesse | Zeit-/Ausgabelimits, getrennte Prozessgruppen, reservierter Steuerungs-Worker, Stream-Cleanup |
| Secrets in Umgebung/Logs | Terminalumgebung wird neu aufgebaut; Agenten erhalten nur notwendige Auth-Variablen; keine Payloads, Token, Header oder rohen Exception-Texte im Audit |
| Stiller falscher Abschluss | Abschluss nur mit Rückgabebeleg; unbekannte Providerantworten und Verbindungsabbrüche werden nicht automatisch erneut ausgeführt |
| Clipboard-Ausspähung | Inhaltslesung nur mit Capability und manuellem Grant oder ausdrücklicher dauerhafter Freigabe; `clipboard_info` liest keine Inhalte; kein Polling |
| Ressourcenüberlastung | Eingabe-, Ausgabe-, Queue-, Verbindungs- und HTTP-Limits |

## Daten und Zugangsdaten

Das Datenverzeichnis muss dem Konto gehören und Modus 0700 haben; die SQLite-Datei hat Modus 0600. Eine SQLite-Datenbank ist nicht automatisch verschlüsselt. Sie enthält die für Wiederherstellung erforderlichen Auftragsargumente und autorisierten Ergebnisse; diese können vertrauliche Texte enthalten. Das Audit enthält stattdessen nur eng definierte Metadaten und Hashes. Geheimnisse gehören in den OS-Secret-Store oder dedizierte Umgebungsvariablen, nicht in Prompts, argv, Git oder Audit-Referenzen. Vollverschlüsselung des Datenträgers und separate OS-Konten schützen gespeicherte Nutzdaten zusätzlich.

Die Audit-Kette erkennt Veränderungen in vorhandenen Einträgen. Ein lokaler Administrator kann die gesamte Kette neu schreiben oder ihr Ende entfernen; für Beweissicherung gegen diesen Administrator muss der ausgegebene Head-Hash extern verankert werden. KiraBridge behauptet keine manipulationssichere externe Beglaubigung.

`scripts/serve_keychain.py` kann einen bereits vorhandenen macOS-Keychain-Eintrag in die Umgebung des HTTP-Dienstes übernehmen. Unter Linux kann eine private systemd-`EnvironmentFile` verwendet werden. Beispiel-Service-Dateien sind Vorlagen und werden nicht automatisch installiert.

## Fernzugriff

Die direkte TLS-Implementierung ist für authentifizierte private Verbindungen vorgesehen. Zertifikatsprüfung ist im Client aktiv; eine private CA kann als `Peer.ca_file` angegeben werden. Proxy-Umgebungsvariablen werden für ausgehende Provider-/MCP-HTTP-Verbindungen nicht übernommen. Weiterleitungen dürfen keine Entscheidung über neue fremde Ziele ersetzen.

Dieser Threat Review ist eine interne Entwurfsprüfung, kein unabhängiges Penetrationstest-Zertifikat. Der autorisierte private OpenAI-Tunnel verbindet ausschließlich den MCP-Proxy. Es wurde kein öffentlicher HTTP-Dienst oder Portforwarding eingerichtet. Eine spätere öffentliche Internetbereitstellung erfordert ausdrücklich freigegebene Infrastruktur und passende OAuth-/Netzwerkregeln.


## Lokaler Betrieb 0.2.0

Der eingerichtete Dienst lädt getrennte, zufällige Tokens aus einer eigenen Datei unter dem privaten Konfigurationsverzeichnis. Die Datei wird mit `O_NOFOLLOW` geöffnet, Eigentümer und Modus werden geprüft; ihr Inhalt wird nicht ausgegeben. MCP-Stdio-Proxies lesen nur ihre konfigurierte Identität aus diesem Store und verbinden sich ausschließlich zu einem Loopback-Endpunkt. Globale Codex-/Grok-Konfigurationen enthalten keine Tokens.

Im Standardmodus `manual` sind Pending-Anfragen keine Genehmigungen. Sie werden anhand des Operationsrechts geprüft, zählen zur Queue-Grenze und starten erst nach lokalem `approve`. Die Freigabe wird mit dem ursprünglichen Anfragehash auditiert. Selbstfreigaben über MCP sind nicht implementiert. `pending` und `approve` sind lokale administrative Befehle und setzen das vertrauenswürdige OS-Konto voraus.

## Dauerhafte lokale Freigabe ab 0.4.0

Ein lokaler Administrator kann pro Zugang ausdrücklich `approval_mode = "automatic"` konfigurieren. Damit ist der authentifizierte Zugang dauerhaft berechtigt, Aufgaben innerhalb seiner eingerichteten Fähigkeiten ohne einzelne Bestätigung einzureichen. Dies umfasst auch eingerichtete Schreib-, Terminal-, Agenten- und Clipboard-Funktionen. Ein vertrauenswürdiger Client kann diese Fähigkeiten danach ohne zusätzliche Browserinteraktion verwenden; insbesondere werden Clipboard-Leseaufträge im automatischen Modus nicht erneut bestätigt. Die Bridge überwacht die Zwischenablage weiterhin nicht von sich aus.

Anmeldung, Fähigkeitsprüfung, Programmlisten, Verzeichnisgrenzen, Eingabe-/Ausgabegrenzen und Ressourcenlimits bleiben in Kraft. Jede automatisch genehmigte Aufgabe wird innerhalb derselben Transaktion mit dem exakten Anfragehash unter `task.auto_approved`, Quelle `principal_policy`, auditiert. Empfang und Start werden erst mit dem tatsächlichen Dispatcher- beziehungsweise Prozessbeleg gemeldet. Idempotenz und die konservative Wiederherstellung unbekannter Zustände gelten unverändert. Ein ausdrücklich übergebener Freigabetoken muss auch in diesem Modus gültig sein. Eine MCP-Anfrage kann weder den Freigabemodus ändern noch einen anderen Zugang oder dessen Aufgaben übernehmen.

Neue Konfigurationen und Zugänge bleiben standardmäßig `manual`; ein ungültiger Modus wird zurückgewiesen. Auf diesem Mac wurde `automatic` auf ausdrücklichen Nutzerwunsch für die vier bestehenden Zugänge eingerichtet. Der Modus kann in der privaten Konfiguration zurückgenommen werden. Das ist eine Änderung der lokalen Vertrauensentscheidung, keine Aufhebung von Authentifizierung oder Plattformrechten.

## Lokale Freigabeoberfläche ab 0.3.0

Der Browserzugang läuft als getrennte Anwendung ausschließlich auf `127.0.0.1:8766` und wird nicht an den MCP-Gateway oder Tunnel gemountet. Host und Clientadresse werden geprüft. Aufgaben und Entscheidungen erfordern eine signierte Browserberechtigung; Schreibanfragen benötigen zusätzlich die genaue lokale Origin und JSON. Es gibt kein CORS für fremde Seiten. CSP, Framing-Verbot, `no-store`, `no-referrer` und ausschließlich textbasierte Darstellung von Auftragsdaten begrenzen Browserangriffe.

Der Launcher prüft einen zufälligen Health-Challenge über HMAC, damit ein fremder lokaler Listener keine Anmeldung erhält. Ein Anmeldeticket wird durch eine private HTML-Datei mit Modus 0600 als POST übermittelt. Es gilt höchstens zwei Minuten, nur für die aktuelle Dienstinstanz und nur einmal. Der langfristige lokale Schlüssel wird weder im Browser noch in URLs, argv oder Plists hinterlegt. Eine Browserberechtigung gilt maximal 30 Tage und wird im lokalen Speicher exakt dieser Origin einschließlich Port abgelegt. Das vertrauenswürdige lokale Betriebssystemkonto und sein Browserprofil gehören weiterhin zur administrativen Vertrauensgrenze.

Eine Entscheidung enthält den Hash des vollständig dargestellten Auftrags. Hash und zulässiger Zustand werden innerhalb derselben SQLite-Transaktion geprüft. Doppelte Freigaben werden abgewiesen; ein inzwischen empfangener oder laufender Auftrag kann nicht über die Ablehnen-Funktion als wartender Auftrag abgebrochen werden. Freigaben tragen die Auditquelle `local_console`. Die Oberfläche startet keinen zweiten Dispatcher und erweitert keine Principal-Rechte.

## Agentennachrichten ab 0.5.0

Nachrichten benötigen eigene Fähigkeiten und gegenseitige `message_peers`. Der Absender stammt aus der authentifizierten MCP-Verbindung; ein `sender`-Eingabefeld wird abgewiesen. Inhalte, Gesprächsverläufe und Ereignisse gehören ausschließlich den beiden Gesprächspartnern. Empfangsquittungen können nur adressierte Empfänger setzen. Ein geteilter `task_id`-Bezug erweitert keine allgemeinen Auftragsrechte. Nachrichtentexte liegen in der privaten Datenbank; ins Audit gelangen nur eng definierte Metadaten und Hashes.

Der lokale, begrenzte Dispatcher darf unter der ausdrücklich konfigurierten Empfängeridentität separate CLI-Turns starten und authentifiziert sich für Rücknachrichten tatsächlich an deren MCP-Zugang. Bestehende interaktive Sitzungen werden nicht übernommen. Er interpoliert Nachrichtentexte nicht in Shellbefehle und verändert die vorhandenen Adapter-Sandboxen nicht. Automatische Antworten fordern keine Folgeantwort; Nachrichten-, Tiefen-, Laufzeit- und Ausführungsbudgets begrenzen den Austausch. Vor einem möglichen externen Aufruf wird der Job dauerhaft beansprucht. Beim Neustart wird eine unterbrochene Beanspruchung mit letztem Beleg `unknown` und nicht wiederholt. Empfang, Agentenstart, Abschluss und Quittierung bleiben unterscheidbar. [Details und Bedienung](AGENT_CHANNEL.md).
