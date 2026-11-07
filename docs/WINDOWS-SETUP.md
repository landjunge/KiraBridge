# KiraBridge unter Windows mit ChatGPT verbinden

Entpacke das vollständige Windows-Paket. Klicke doppelt auf
**Einrichtung-starten.cmd**. Die Vorbereitung installiert die nötigen Bestandteile
für deinen Windows-Benutzer und öffnet danach den Einrichtungsassistenten.
Du brauchst dafür keine Python- oder PowerShell-Befehle einzugeben.

Der Assistent begleitet dich durch vier Schritte:

1. **Windows prüfen:** Er prüft deinen angemeldeten Windows-Desktop. Bevor du
   KiraBridge startest, bestätigst du, dass ChatGPT Tasten drücken und Fenster
   bedienen darf. Der Start selbst drückt keine Tasten.
2. **Verbindung vorbereiten:** Er entpackt und prüft auf deinen Klick die beiliegende
   offizielle OpenAI-Verbindungshilfe. Dafür ist kein weiterer Download nötig. Die Schaltflächen öffnen
   die passenden Kontoseiten. Dort meldest du dich selbst an. Du brauchst einen
   Tunnel für den richtigen ChatGPT-Arbeitsbereich und einen eingeschränkten
   Runtime-Schlüssel. Wenn du KiraBridge auch auf einem Mac nutzt, lege für
   Windows einen eigenen Tunnel und eine eigene ChatGPT-Verbindung an, zum
   Beispiel **KiraBridge Windows**. Diesen Schlüssel gibst du ausschließlich in das verdeckte
   Feld des Assistenten ein. Kopiere ihn niemals in einen Chat.
3. **In ChatGPT hinzufügen:** Öffne in ChatGPT die Plugins, wähle **+**, dann
   **Add custom MCP server** und als Verbindung **Tunnel**. Wähle denselben Tunnel
   beziehungsweise seine ID. Prüfe den angezeigten Umfang und bestätige das
   Hinzufügen. Die Bezeichnungen können je nach Oberfläche abweichen.
4. **Verbindung testen:** Der Assistent gibt dir einen kurzen Prüfauftrag. Sende
   ihn im ChatGPT-Chat mit der ausgewählten KiraBridge-Verbindung. Trage den
   Antwortcode aus ChatGPT im Assistenten ein. Erst nach bestätigtem Rückweg
   erscheint **„Alles verbunden – du kannst loslegen.“** Der Test drückt keine
   Tasten, bewegt keine Fenster und ändert keine Dateien außerhalb seines
   eigenen Prüfbelegs.

Lass anschließend die beiden KiraBridge-Verbindungsfenster geöffnet. Der
Assistent selbst darf geschlossen werden. Zum späteren Öffnen dient der
Desktop-Starter **KiraBridge einrichten.cmd**. Es wird kein Windows-Dienst und
kein automatischer Start bei der Anmeldung eingerichtet.

Nach einem Windows-Neustart öffnest du den Assistenten erneut, bestätigst den
Umfang und startest KiraBridge. Klicke dann auf **Gespeicherte Verbindung
starten**. Die vorhandenen Zugangsdaten werden intern wiederverwendet; du musst
den Schlüssel nicht erneut eingeben. Ein unklarer alter Start wird zuerst
geprüft und niemals auf Verdacht wiederholt.

## Wenn etwas nicht klappt

- **Der Menüpunkt fehlt im Konto:** Der Assistent kann die Kontofunktion nicht
  freischalten. Prüfe den richtigen Arbeitsbereich und frage dessen Verwaltung
  nach Zugriff auf eigene MCP-Verbindungen. Tunnel-Nutzung benötigt getrennte
  Platform-Berechtigungen. Verfügbarkeit und Kosten gelten für dein eigenes
  Konto; ein beliebiger API-Schlüssel oder Codex-Login ersetzt sie nicht.
- **Die Verbindung ist noch nicht bereit:** Lass die KiraBridge-Fenster offen.
  Prüfe die Internetverbindung und klicke erneut auf **Verbindung prüfen**.
  Der erste Verbindungsaufbau kann einige Zeit dauern.
- **Der Prüfcode passt nicht oder ist abgelaufen:** Verwende die neue Antwort
  auf den aktuellen Prüfauftrag. Erstelle bei Bedarf einen neuen Prüfauftrag.
  Ein alter Code bestätigt keine neue Verbindung.
- **Es läuft bereits eine andere Einrichtung:** Die vorhandene Verbindung wird
  erhalten. Öffne ihren Starter beziehungsweise ihr Fenster. Der Assistent
  übernimmt keine fremden Ports und ersetzt keine Zugangsdaten.

Die Verbindung bleibt lokal auf diesem PC abgesichert; der Verbindungsclient
stellt die ausgehende Verbindung zu OpenAI her. Die vorhandenen dev2-, dev3-
und RC33-Testinstallationen werden nicht überschrieben. Der neue Assistent
verwendet einen eigenen Installationsordner, eigene Zugangsdaten und Port 8768.

Die Anleitung folgt der [offiziellen OpenAI-Dokumentation zu Secure MCP
Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), abgerufen
am 04.11.2026. Der Antwortcode belegt einen vom Nutzer bestätigten,
authentifizierten Rückweg; er ist keine kryptographische Herkunftsbestätigung
der ChatGPT-Cloud. Lokale simulierte Tests werden ausdrücklich getrennt
ausgewiesen. Er ersetzt keinen Funktionstest jeder Tastenkombination oder
eine Messung der Cloud-Latenz.
