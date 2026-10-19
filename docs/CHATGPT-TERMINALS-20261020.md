# Kira-Zugriff auf vorhandene Terminal.app-Sitzungen

## Ursache

Der aktive Dienst verwendete tatsächlich
`/Users/landjunge/.config/kirabridge/config.toml`; geladene Konfiguration und
Quellstand stimmten vor der Reparatur mit den Dateien überein.
`chatgpt` hatte bereits `session.inspect`, `session.input`, `terminal.execute`
und „Voll erlaubt“. Erkennung und Lesen beider offener Fenster funktionierten
auch schon vor der Änderung über authentifiziertes MCP mit dieser Identität.
Eine fehlende macOS-Automationsberechtigung wurde dabei nicht festgestellt.

`session_input_policy.enabled=false, principals=[]` ist kein ausgeschalteter
Terminalzugriff. Commit `0188f84` schaltete den früheren Zusatzpuffer für
Terminaleingaben bewusst aus und verlagerte die Versandregel auf ausgehende
Voice-Nachrichten. Diese Trennung bleibt bestehen.

`agent_status.managed_terminal_sessions` enthielt ausschließlich vom jeweiligen
Bridge-Principal gestartete Kindprozesse. Bereits offene Terminal.app-Fenster
wurden dort nie ermittelt. Die in dieser ChatGPT-Sitzung verfügbare
Werkzeugbindung enthielt zudem keine direkten `session_catalog`-/`session_read`-
Werkzeuge und auch kein allgemeines `read_query`. Vorhandene Rechte und funktionsfähiger Terminaltransport waren
deshalb für Kira nicht ausreichend sichtbar und erreichbar beschrieben.

## Änderung in 0.8.0rc3

* `agent_status.interactive_terminal_sessions` liefert jetzt den echten Katalog
  zusätzlich zu den weiterhin getrennten verwalteten Prozessen. Das liest keine
  Terminalinhalte und behauptet keine Bereitschaft eines laufenden Agenten.
* Der Katalog bindet Fenster-ID, TTY und eindeutigen Sitzungswurzel-PID und zeigt
  zugehörige Prozess-IDs/-Namen. Bei mehreren möglichen Wurzeln wird kein Ziel
  geraten. Prozessnamen bestätigen allein keine Agentenidentität.
* `read_query` ermöglicht über das bereits bestehende Wörterbuch-Schema
  `{"operation":"session.catalog"}` sowie
  `{"operation":"session.read","pane_id":"AUS_DEM_KATALOG","expected_pid":123}`.
  Die zweite Abfrage erfordert den tatsächlich beobachteten PID. Dadurch ist
  kein neuer Werkzeugname und kein Neustart des ChatGPT-Tunnels erforderlich,
  sofern der Client dieses Werkzeug bereits kennt.
* Für die tatsächlich vorhandene ChatGPT-Bindung werden dieselben beiden
  Leseoperationen zusätzlich im bestehenden `task_request` angeboten: Operation
  `session.catalog` mit leeren Argumenten bzw. `session.read` mit dem exakten
  Katalogziel. Das Ergebnis liefert das bereits vorhandene `task_get`.
  Diese Route wird durch die echte ChatGPT-Werkzeugbindung geprüft.
* `terminal_access` in Health, Rechteansicht und Operationskatalog unterscheidet
  erteilte Rechte, zusätzliche Eingabebestätigung und tatsächlich geprüfte
  Verfügbarkeit. „Voll erlaubt“ wird nicht als Nachweis für macOS-Automationsrechte
  oder einen abgeschlossenen Agentenauftrag ausgegeben.
* `session.input.require_idle=true` verweigert die Eingabe bei einem beschäftigten
  Terminal, auch bei einer Änderung zwischen Katalogabfrage und Terminaltransport.
  Das ist für den harmlosen Shell-Test vorgesehen. Terminal.app meldet ein
  laufendes Codex/Grok generell als beschäftigt; normale autorisierte Nachrichten
  an diese Agenten werden dadurch nicht pauschal gesperrt.

## Dauerhafte Einstellungen

In der tatsächlich verwendeten Konfiguration erhält `principals.chatgpt` die
zusätzliche dauerhafte Freigabe `automatic_operations=["session.input"]`.
Die vorhandenen Capabilities, Pfade und Zugangsdaten bleiben erhalten.
Der optionale Terminalpuffer bleibt ausgeschaltet. Die `go-go-go`-Regel für
ausgehende Eve-/Kira-Nachrichten wird unverändert weiter geprüft.

Die Auswahl „Voll erlaubt“ richtet diese Kira-Freigabe künftig mit ein.
Neue ausdrücklich mit Vollzugriff installierte Profile setzen sie ebenfalls.
Bestehende Installationskonfigurationen werden bei Updates nicht überschrieben.
Die ChatGPT-Einrichtung kopiert künftig das gesamte autorisierte Profil, inklusive
Terminalpfaden, Rechtestufe und dauerhaften Operationsfreigaben; früher kopierte
sie nur einzelne Felder. Neu erzeugte Tunnelbefehle nennen die konkrete
`--config`-Datei statt von Umgebungsvariablen oder Standardpfaden abzuhängen.
Der bestehende produktive ChatGPT-Adapter nennt diese Datei bereits ausdrücklich.
Auch launchd startet den Kern mit dem absoluten kanonischen Konfigurationspfad.

Regressionstests prüfen diese Erhaltung beim erneuten Einrichten und Laden sowie
beim Update. Ein absichtlicher Wechsel auf eine andere, weniger berechtigte
Konfiguration oder der Entzug von macOS-Rechten kann weiterhin den Zugriff ändern;
die Bridge stellt dann den fehlenden Zugriff dar, statt Freigaben heimlich zu erweitern.

## Prüfung und Grenzen

Die Produktionsprüfung verwendet ausdrücklich `chatgpt`, einschließlich der
bestehenden ChatGPT-Werkzeugbindung. Für den Eingabetest wird ein eigenes
Terminal.app-Testfenster geöffnet und vor dem Schreiben anhand Fenster-ID, TTY,
PID und `busy=false` geprüft. Nur dort wird ein eindeutiges `printf` ausgeführt.
Bestehende Codex-/Grok-Fenster werden erkannt und gelesen, erhalten aber keine
Testeingabe. Tunnel werden nicht neu gestartet.

Private Vorher-/Nachher-Belege liegen unter
`~/.config/kirabridge/repairs/chatgpt-terminals-20261020-011050/`.
Diese Terminalprüfung ist keine Abnahme einer hörbaren Antwort in Grok Voice.

## Tatsächliche Aktivierung und Ergebnis

Der gepushte Code-Commit ist `4188f00`. Der produktive Kern läuft nach
kontrolliertem Leerlauf-Neustart als `0.8.0rc3`, PID 46820. `policy_inspect`
bestätigt `matches_loaded` für Quelle und Konfiguration. Die tatsächliche
ChatGPT-Werkzeugbindung bestätigt `automatic_operations=["session.input"]`,
keine zusätzliche Eingabefreigabe und weiterhin `voice_message_gate=true`.

Beim ersten Aktivierungsversuch zeigte sich zusätzlich ein veralteter
Steuerfenster-Prozess: Sein bereits geladener Konfigurationsparser kannte die
inzwischen vorhandenen Voice-Felder noch nicht. Er scheiterte vor dem Neustart
des Kerns. Der unveränderte alte Kern-PID wurde danach überprüft; anschließend
wurde nur `com.kirabridge.approvals` neu geladen und der Kern über dessen
Leerlaufprüfung aktiviert. Die Tunnel wurden dabei nicht neu gestartet.

Über die echte ChatGPT-App-Werkzeugbindung wurden anschließend geprüft:

| Prüfung | Tatsächlicher Befund |
| --- | --- |
| Bestehendes Codex-Fenster | Fenster 22104, `/dev/ttys000`, Wurzel-PID 94023, Codex-PID 94386 |
| Codex lesen | `session.read` über bestehendes `task_request`/`task_get`: abgeschlossen, tatsächliche Ausgabe zurück |
| Bestehendes Grok Build | Fenster 22228, `/dev/ttys002`, Wurzel-PID 6957, Grok-PID 6986; vor der Änderung mit ChatGPT gelesen und danach im Katalog unverändert |
| Testterminal | Eigenes Fenster 22803, `/dev/ttys001`, Wurzel-PID 46994; `busy=false`, nur login und zsh |
| Testeingabe | Einmaliges `printf` mit `require_idle=true`, ohne Nachrichtenmarker; abgeschlossen |
| Ausgabe | Eindeutige Markerzeile exakt in der tatsächlichen Shell-Ausgabe gefunden |
| Aufräumen | Ausschließlich das weiterhin unbeschäftigte eigene Testfenster geschlossen |
| Abschließender Katalog | Über ChatGPT-`task_request` mit `session.catalog`: beide ursprünglichen Fenster mit unveränderten IDs und PIDs |

Die Eingabefunktion wurde bewusst nur im Testterminal ausgeführt. Lesen des
bestehenden Codex-Fensters ist belegt; eine Eingabe in den laufenden Codex
wurde nicht als Test durchgeführt. macOS-Automation für diese Terminalaktionen
funktioniert im tatsächlichen Dienstkontext.

595 Tests haben im vollständigen lokalen Prüflauf bestanden; Paketbau,
Ruff und JavaScript-Syntaxprüfung sind erfolgreich. Ein früherer Prüflauf
traf beim bestehenden Prozessgruppen-Test auf dessen knappe 300-ms-Startfrist;
derselbe Test bestand separat und anschließend im vollständigen Prüflauf.
Die Laufzeitfrist der Anwendung wurde dafür nicht verändert.

Die privaten Belege enthalten `before.json`, `activation.json`,
`actual-chatgpt-app-test.json` und Prozess-Snapshots vor/nach der Aktivierung.
