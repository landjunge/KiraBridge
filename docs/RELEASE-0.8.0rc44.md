# KiraBridge 0.8.0 RC44

macOS-Kandidat nach RC43 (`f9e6ec8`). Ziel: alle Dienste laufen aus der installierten Version.

Neu gegenüber RC43:

- Der Installer übernimmt vorhandene Dienste für die Grok-Verbindung
  (`com.kirabridge.grok-app`) und die Antwortzustellung (`com.kirabridge.chat-events`)
  in seine Desktop-Transaktion. Er behandelt sie wie Freigaben und ChatGPT-Dienst:
  vorher sichern, auf die Release-venv umstellen, neu laden. `rollback` stellt die
  vorherigen Plists bytegleich wieder her.
  Fehlende Dienste legt er nicht an. Abweichende Definitionen lässt er unverändert
  und bricht vor jeder Änderung ab.
- Der Absender der Antwortzustellung (`integrations/chat-events/serve.py`) ist jetzt
  im Paket enthalten. Im Modus `--sender-only` läuft er ohne das MCP-2-SDK direkt in
  der Release-venv und liest die aktuelle Konfiguration. Bisher startete er aus dem
  Entwicklungsstand und brach mit `extra_forbidden` ab (`threaddesk.dynamic_*`,
  `file_transfer`).

Lokaler Intel-Build; kein öffentliches Release, kein Upload.
