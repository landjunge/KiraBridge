# KiraBridge 0.8.0 RC53

macOS-Kandidat nach RC52 (`e4f395f`). Schwerpunkt: ThreadDesk bleibt das Gedächtnis des Nutzers und
füllt sich nicht mehr mit technischen Meldungen. Mitgeliefert wird die aktuelle ThreadDesk-Bibliothek
(Pin `22fda1d`).

Neu gegenüber RC52:

- Technische Einträge bleiben aus ThreadDesk heraus. Ein `whiteboard_append` mit dem Typ `progress`,
  `claimed`, `task` oder `problem` (über das `td_`-Gateway und das MCP-Werkzeug) wird nicht an
  ThreadDesk weitergegeben, sondern gelingt sofort mit `routed: "kirabridge"` und
  `kept: "latest_state_only"`. KiraBridge hält nur den letzten Stand je Principal, Thread, Akteur und Typ
  im Speicher, ohne Datenbank und ohne Audit-Kette. Entscheidungen, Ergebnisse, Notizen und unbekannte
  Typen gehen unverändert durch. Schalter: `threaddesk.route_technical_entries` (Standard an).
- ThreadDesk-Bibliothek (Pin `22fda1d`), Änderungen dort, die auch die Agentenwerkzeuge betreffen:
  Whiteboard-Einträge lassen sich ersetzen (gleicher `external_key`), mit `supersedes` ablösen, per
  `entry.remove` entfernen und mit `expires_at` selbst ablaufen lassen. Neues Werkzeug `search_entries`
  für die Suche in Boardeinträgen. Das endgültige Löschen aus dem Papierkorb wird nicht mehr durch
  Vorschau-Hinweise blockiert. Der Graph verbindet den Big Plan mit den fünf Werkzeugen.
- Mit dem neuen ThreadDesk-Stand laufen 971 KiraBridge-Tests (alle ThreadDesk- und Whiteboard-Dateien)
  ohne Fehler.

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
