# Steuerfenster und Reparatur · 19.10.2026

## Ursachen und Änderungen

Die frühere Health-Ausgabe beschrieb den gemeinsamen Nachrichten-Dispatcher,
während `message_channel_status` den angemeldeten Empfänger beschrieb. Für
ChatGPT ist dessen Postfach kein eigener CLI-Worker. Die Ausgaben benennen jetzt
jeweils ihren Geltungsbereich und zeigen die konfigurierten Worker der Gegenstellen.
Codex und Grok haben aktive automatische Empfänger; ChatGPT und Grok-App lesen
über ihre angeschlossenen Clients. Das wird nicht als autonomer Chatempfang ausgegeben.

Laufende Prozesse waren erkennbar, aber Terminal.app hatte keine adressierbaren
Sitzungen in der Bridge. Die neue Anbindung liefert genaue Fenster-/TTY-Ziele mit
PID-Prüfung sowie Lesen, Eingeben und Öffnen. Sie verwendet die auf diesem Mac
funktionsfähige JavaScript-Automation. Die bestehenden Sitzungen bleiben erhalten.
`managed_terminal_sessions` beschreibt weiterhin separate verwaltete Aufträge;
der Zugriff auf sichtbare Terminals wird gesondert ausgewiesen. Es wird keine
Sitzungsübernahme vorgetäuscht.

Die bisherigen Adapter konnten trotz erteilter Vollfreigabe lokale Werkzeuge und
MCP ausschalten. Die explizite Vollfreigabe wird nun in die nativen Agentenprofile
übernommen. Versteckte Pfadausschlüsse widersprechen dieser Freigabe nicht mehr.
OpenCode übernimmt sein konfiguriertes lokales Modell und dessen Serveradresse
sowohl als Worker als auch beim Öffnen aus der Oberfläche.

Nachrichten unterscheiden automatische Worker-Verarbeitung und externe
Client-Postfächer. Eine gespeicherte Nachricht ist keine bestätigte Zustellung;
eine Quittierung ist kein bestätigter Agentenabschluss. Ergebnisse und Fehler
stehen im Protokoll mit dem Zustand zum jeweiligen Ereigniszeitpunkt. Bereits
fehlgeschlagene oder unbestätigte Fremdaufträge wurden nicht blind wiederholt.

## Bedienung

Die neue macOS-App zeigt Prozesse, Kira/ChatGPT und Grok, Terminals, Doktor und
drei Rechtestufen in einem Fenster. Nur das Protokoll öffnet ein weiteres Fenster.
Start und Neustart sind direkt erreichbar; vorhandene Nutzersitzungen werden
beim Reparieren nicht beendet. „Neu verbinden“ erhält die bestehenden öffentlichen
Adressen und Kontoverknüpfungen. Die Steuerung bleibt verfügbar, wenn die Bridge aus ist.

„Voll erlaubt“ nutzt die erteilten Freigaben ohne zusätzliche Auftragsnachfrage.
„Mittel“ gibt Lesen automatisch frei; Änderungen und Ausführung warten auf Zustimmung.
„Nur mit Erlaubnis“ lässt neue Aufträge auf Zustimmung warten.
Vorhandene Zugangsdaten und Zugriffsrechte werden beim Stufenwechsel erhalten.

## Tatsächlich geprüft

- Komplette automatisierte Tests, Formatierung, Lint und Paketbau im sauberen Checkout;
  zusätzliche Prüfung über GitHub CI auf macOS und Linux.
- Echte Codex- und Grok-Arbeitssitzungen mit tatsächlicher Bridge-Toolabfrage.
- 72 gerichtete Nachrichtenwege zwischen neun authentifizierten Identitäten,
  jeweils empfangen und quittiert. Das prüft Transport, nicht 72 Modellantworten.
- Echte Nachricht über den Codex-Connector an das ChatGPT-Postfach und Empfang
  samt Quittierung über den getrennten ChatGPT-Connector.
- Öffentlicher Grok-OAuth-/HTTPS-Zugang: Version 0.8.0rc1, Vollfreigabe,
  sichtbare Terminalziele und tatsächliche Shell-Testantwort lesbar.
  Ausschließlich der eigene temporäre Testclient wurde anschließend widerrufen.
- Terminaleingabe aus der Oberfläche nach sofortigem Sitzungswechsel und Rücklesen
  der echten Shell-Antwort. Der zuvor gefundene Verlust dieses Klicks ist behoben.
- Oberfläche mit allen vier Ansichten bei 1280×800, 1024×720 und 390×844:
  keine Seitenüberläufe, keine abgeschnittenen Bedienelemente, keine JavaScript-Fehler.
- Eigenes Protokollfenster und Anmeldung der nativen macOS-App.
- Kontrollierter Start der ausgeschalteten Bridge über die weiterlaufende Steuerung.
- Bestehende Nutzerterminals, Codex-Prozesse, Tunnel und Zugangsdaten erhalten.

## Noch nicht bestätigt

Native Gespräche in ChatGPT und Grok auf einem physischen Handy, einschließlich
Live und Sprache, konnten hier nicht direkt bedient werden. Der öffentliche
Transport ist geprüft; das bestätigt nicht, dass der jeweilige Anbieter in jedem
Gesprächsmodus Werkzeuge freigibt. Die Oberfläche markiert solche Zugänge erst
nach einem tatsächlichen Aufruf als bestätigt. Gerät und Modus bleiben dabei
Selbstauskünfte des Clients.

Das automatische Aufwecken eines inaktiven ChatGPT-/Grok-App-Chats ist durch die
aktuell verwendeten Client-Verbindungen nicht belegt. Dauerhafte Postfächer und
Abschlussmeldungen stehen bereit, benötigen aber einen empfangenden Client.
Provider-Anmeldungen optionaler CLI-Agenten wurden nicht durch neue Konten ersetzt;
ein gestartetes CLI ist kein Nachweis einer erfolgreichen Modellantwort.

Das macOS-App-Paket wurde auf diesem Intel-Mac gebaut und lokal signiert.
Eine notarierte universelle macOS-Auslieferung ist damit nicht nachgewiesen.
