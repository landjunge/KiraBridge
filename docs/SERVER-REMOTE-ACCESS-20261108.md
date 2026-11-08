# KiraBridge und ThreadDesk auf dem Debian-Server von unterwegs nutzen

Stand 8. November 2026. Host `v2202608211799501333.goodsrv.de` (Debian 13, x86_64).
Ziel: Beide Produkte sind über das Internet erreichbar und arbeiten weiter,
auch wenn der Mac ausgeschaltet ist.

## Entscheidungen

| Frage | Entscheidung | Grund |
|---|---|---|
| Wie erreicht ChatGPT KiraBridge auf dem Server? | OpenAI **Secure MCP Tunnel** (`tunnel-client` 0.0.16) mit einem eigenen Server-Tunnel und Stdio-Profil `kirabridge --principal chatgpt connect` | Dieser Weg ist offiziell für private MCP-Server gedacht. Der Server baut nur eine ausgehende HTTPS-Verbindung zu `api.openai.com:443` auf. KiraBridge bleibt auf `127.0.0.1:8765` und bekommt keinen öffentlichen Port. Es ist derselbe Weg, den der Mac schon nutzt. |
| Warum kein öffentlicher `/mcp`-Endpunkt mit OAuth? | Wird nicht gebaut | ChatGPT verlangt für öffentliche MCP-Server OAuth 2.1 nach der MCP-Autorisierungsspezifikation (Protected Resource Metadata und anderes). KiraBridge hat dafür keinen Autorisierungsserver, sondern nur Bearer-Token. Ein öffentlicher Bearer-Endpunkt wäre ein unnötiges Risiko. |
| Warum ein eigener Tunnel statt des Mac-Tunnels? | Eigene Tunnel-ID für den Server | Bei Stdio-Servern ist je Tunnel-ID nur ein aktiver Client vorgesehen. Der Mac-Connector bleibt deshalb unverändert. |
| Wie wird ThreadDesk erreichbar? | ThreadDesk Server & Sync hinter dem vorhandenen Caddy auf `https://v2202608211799501333.goodsrv.de:8443` | Das vorhandene Let's-Encrypt-Zertifikat des Hosts wird genutzt, ein DNS-Eintrag ist nicht nötig. Der App-Port ist nicht öffentlich. |
| Welche ThreadDesk-Daten sieht KiraBridge? | Den Server-Speicher des Users `mac` | Vorher arbeiteten die `td_*`-Werkzeuge mit einem leeren eigenen Arbeitsbereich. Der Speicher sperrt Dateien beim Schreiben und prüft Revisionen, daher können mehrere Prozesse ihn gemeinsam nutzen. |
| Führt der Server Agenten aus? | Nein | Laut Big Plan vermittelt der Server nur. Agentenarbeit läuft weiter auf dem Mac. |

## Umgesetzt und geprüft

- **ThreadDesk öffentlich:** Der Caddy-Block `:8443` ist eingerichtet und Port 8443 im 4AllPass-Compose freigegeben. Ein systemd-Drop-in `threaddesk-server.service.d/public.conf` bindet ThreadDesk an `172.18.0.1:8766` und vertraut nur dem Proxy-Netz `172.18.0.0/16`. Eine ufw-Regel lässt nur den Caddy-Container zu 8766 durch. Der alte Zugang über `threaddesk-server-tls` auf Port 8446 ist abgeschaltet. Die Test-User `alice` und `bob` sind entfernt und liegen in `alt/`.
  - Geprüft: Die Seite liefert 200 mit gültigem TLS, auch aus einem fremden Netz. `/api/session` liefert ohne Anmeldung 401. Die Anmeldung mit dem `mac`-Schlüssel ergibt 200, die Projektliste ebenfalls.
  - Unverändert erreichbar: 4AllPass, TollGate, agent-authority.
- **KiraBridge-Server:** Der Dienst `kirabridge.service` läuft als systemd-User-Dienst, linger ist aktiv. Er läuft weiter nur auf Loopback mit Bearer-Pflicht.
  - Der `[threaddesk]`-Arbeitsbereich zeigt jetzt auf `…/data/users/mac/core`. Die Sicherung liegt unter `config.toml.bak.20261108-010232-td-workspace`.
  - Geprüft über Stdio als Principal `chatgpt`: Es kommen 242 Werkzeuge. `bridge_health` ist ok, `td_list_threads` liefert die echten Threads.
- **Neustartfest:** `docker`, `threaddesk-server` und `kirabridge` (User-Dienst) sind enabled, linger ist an, Caddy hat die Restart-Policy `unless-stopped`. Die Konfiguration verweist nicht auf den Mac.
- **Tunnel vorbereitet:** `tunnel-client` 0.0.16 linux-amd64 ist heruntergeladen und gegen `SHA256SUMS.txt` geprüft. Das Einrichtungsskript liegt unter `~/.local/bin/kirabridge-tunnel-setup`. Es installiert das Programm, fragt Tunnel-ID und Runtime-Schlüssel verdeckt ab und speichert den Schlüssel als Datei mit Modus 0600. Danach schreibt es das Profil, ruft `doctor` auf und richtet `kirabridge-tunnel.service` (systemd --user, `Restart=always`) mit Gesundheitscheck auf `127.0.0.1:8781` ein.

## Noch offen

1. **Tunnel anlegen:** Auf <https://platform.openai.com/settings/organization/tunnels> einen neuen Tunnel „KiraBridge Server“ und einen Runtime-Schlüssel mit Tunnels Read + Use anlegen. Den Tunnel dem ChatGPT-Workspace zuordnen. Das geht nur im OpenAI-Konto selbst.
2. **Tunnel auf dem Server starten:** `ssh -t netcup-daniel ~/.local/bin/kirabridge-tunnel-setup`. Die Ausführung des heruntergeladenen Programms war für die automatische Sitzung gesperrt.
3. **ChatGPT verbinden:** In ChatGPT unter Plugins bzw. Connectors einen eigenen MCP-Server hinzufügen, Connection: **Tunnel**, die neue Tunnel-ID, ohne zusätzliche Authentifizierung. Danach `bridge_health` und `td_list_threads` aufrufen.
4. **Mac-aus-Abnahme:** Den Mac ausschalten und vom Handy aus prüfen, ob ThreadDesk im Browser und der ChatGPT-Connector „KiraBridge Server“ antworten. Diese Prüfung ist bisher nicht erfolgt. Belegt ist nur, dass keine Serverkomponente den Mac braucht.
5. **Auftragsweg auf der Mac-Seite:** siehe nächster Abschnitt.
6. **Mac-Desktop:** In ThreadDesk unter „Server und Abgleich“ die neue Adresse `https://v2202608211799501333.goodsrv.de:8443` eintragen.

## Auftragsweg (Handoff)

**Server-Hälfte ist eingeschaltet.** Der Dienst startet jetzt über
`serve_handoff.py`, also `create_app(..., handoff_rpc=True)` mit denselben
Parametern wie `threaddesk-server serve`. Die vorherige Drop-in-Datei ist
gesichert als `public.conf.bak.*-before-handoff`. Über das Internet geprüft:

- `GET /api/projects/{pid}/handoff` mit Bearer-Token liefert 200 und das Format
  `threaddesk.handoff-http.v1` mit `executes_agents=false`.
- `POST get_issued_handoff` mit Bearer-Token liefert eine ordentliche Antwort
  (`found=false` für eine unbekannte ID).
- Ohne Token kommt 401. Mit einer Browser-Sitzung ohne CSRF-Token wird
  `csrf_required` abgelehnt. `review_return` und `answer_handoff_question`
  werden mit 403 gesperrt, wie vorgesehen.

Der Server kann damit Aufträge annehmen, speichern und für genau einen
Zustellversuch reservieren, auch während der Mac aus ist. Er führt nichts aus.

**Auflisten:** `serve_handoff.py` ergänzt das nur lesende Werkzeug
`list_issued_handoffs`. Es liefert höchstens 100 Handoffs des angemeldeten
Users und Projekts mit Reservierungs- und Bindungsstatus. Ohne dieses Werkzeug
könnte der Mac neue Aufträge nicht finden. Unbekannte Argumente werden mit 400
abgelehnt.

**Mac-Hälfte ist in Betrieb** (vom Nutzer so beauftragt: jeder Auftrag nur mit
lokaler Bestätigung).

- **Eigener Zugang `remote`** in der Mac-KiraBridge mit
  `approval_mode = "manual"`. Er darf nur `agent.execute`, `task.read`,
  `task.cancel` und `bridge.health`, nur mit den Agenten codex, claude und grok
  und nur in den sechs Projektordnern plus `~/remote-relay-test`. Die Bestätigung
  wird damit von KiraBridge selbst erzwungen und hängt nicht am Relay. Alle
  anderen Zugänge auf dem Mac stehen auf `automatic`/`full` und werden deshalb
  nicht genutzt. Sicherungen: `config.toml.bak.20261108-013125-remote-principal`
  und `credentials.json.bak.…`.
- **Relay** `scripts/remote_handoff_relay.py`, installiert als launchd-Dienst
  `com.kirabridge.remote-relay`. `run.sh` sucht die Python-Umgebung der jeweils
  installierten KiraBridge-Version über `~/.local/bin/kirabridge`. Das Relay
  baut nur ausgehende Verbindungen auf und fragt alle 60 Sekunden. Für jeden neuen
  Handoff eines zugeordneten Projekts geht es so vor:
  1. Prüfen, ob der lokale Task `remote-<handoff_id>` schon existiert.
  2. Den Handoff auf dem Server mit `reserve_handoff_delivery` reservieren und
     die Reservierung zurücklesen.
  3. `task_request` mit `agent.execute` stellen. Der Prompt wird aus Aufgabe,
     Beschreibung, Notizen und Abnahmekriterien gebaut und als nicht
     vertrauenswürdiger Kontext markiert.
  4. Einen Whiteboard-Eintrag `progress` schreiben und eine macOS-Mitteilung
     zeigen.
  Ist der Task beendet, schreibt das Relay das Ergebnis als `result` oder
  `problem` ins Whiteboard. Doppelte Einträge verhindert `external_key`.
- **Konfiguration** `~/.config/kirabridge/remote-relay.json` (0600). Sie enthält
  die Projektzuordnung und den Zeitpunkt `since`. Handoffs von vor der
  Einrichtung werden nie aufgegriffen. Den ThreadDesk-Zugang liest das Relay aus
  `~/.config/kirabridge/remote-relay-td.token` (0600). Zustand:
  `~/.local/state/kirabridge-remote-relay/state.json`, Log:
  `~/Library/Logs/kirabridge-remote-relay.log`.
- **TLS:** Das Server-Zertifikat wird normal über die CA und den Hostnamen
  geprüft, nicht gepinnt. Ein Pin würde bei jeder automatischen Erneuerung
  brechen.

**Bewusst anders als `RemoteRelay` aus BP-REMOTE-02:** Ein remote ausgestellter
`NativeGrant` und ein Pairing werden nicht gebraucht, weil die lokale
Bestätigung die Freigabe ist. Der Mac-Core wird nicht auf eine Handoff-Quelle
auf dem Server umgestellt, lokale Handoff-Abläufe bleiben unverändert. Die
Rückgabe läuft über das Whiteboard statt über `import_return`. Die strikte
Return-Inbox verlangt einen gebundenen Lauf, und diese Laufbindung bleibt
offen.

**Geprüft am 8. November 2026** mit dem Testprojekt „Remote-Auftrag Test“
(`d0c0cb9edc3d`) und dem Handoff `b195c74ba6ec` mit Ziel codex. Der Auftrag
lautet: im Testordner eine Datei anlegen.

- Die Reservierung durch `mac-relay` ist auf dem Server gespeichert.
- Der lokale Task `remote-b195c74ba6ec` hat den Zustand `created`, Principal
  `remote`. Er wartet auf Freigabe, gestartet ist nichts.
- Im Whiteboard steht genau ein `progress`-Eintrag.
- Ein zweiter Durchlauf erzeugt nichts doppelt.
- Der launchd-Dienst läuft.

**Noch offen:**
- Lokale Freigabe dieses Testauftrags über `kirabridge approvals` (öffnet die
  Freigabeseite mit Einmal-Login; die bloße Adresse 127.0.0.1:8766 verlangt eine
  Anmeldung) und der
  `result`-Eintrag danach. Freigeben muss der Nutzer selbst.
- Aufträge vom Handy anlegen. Das geht über ChatGPT, KiraBridge Server und
  `td_issue_handoff`, sobald der Tunnel läuft.
- Die Laufbindung (`bind_handoff_run`) und die strikte Return-Inbox.

## Quellen

- OpenAI, Secure MCP Tunnel: <https://developers.openai.com/api/docs/guides/secure-mcp-tunnels>
- `tunnel-client`: <https://github.com/openai/tunnel-client>
- ChatGPT mit eigenem MCP-Server verbinden: <https://developers.openai.com/plugins/deploy/connect-chatgpt>, <https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt>
- Authentifizierung für ChatGPT-MCP-Server: <https://developers.openai.com/plugins/build/auth>
- MCP-Autorisierung: <https://modelcontextprotocol.io/specification/draft/basic/authorization>, Spezifikation 2026-07-28: <https://blog.modelcontextprotocol.io/posts/2026-07-28/>
