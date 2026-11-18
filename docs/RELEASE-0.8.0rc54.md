# KiraBridge 0.8.0 RC54

macOS-Kandidat nach RC53. Schwerpunkt: Nachrichten gehen nicht mehr verloren, eigene Limits lehnen nichts mehr ab,
Abschlussmeldungen kommen neueste zuerst. ThreadDesk-Bibliothek unverändert (Pin `22fda1d`).

Neu gegenüber RC53:

- Nachrichten an einen gerade arbeitenden Agenten werden gehalten und später zugestellt, statt verworfen zu werden.
  Eine Zustellung wird nur wiederholt, wenn sicher ist, dass noch nichts angekommen ist (#224).
- KiraBridges eigene Grenzen (Nachrichtenspeicher, Team-Warteschlange, Läufe je Stunde und Gespräch, Kontextgröße)
  lehnen nichts mehr ab. Sie nehmen an und vermerken die Überschreitung (#222). Grenzen und Budgets gehören in TollGate.
- Abschlussmeldungen kommen neueste zuerst, neue Ergebnisse stehen nicht mehr hinter alten unquittierten (#225).
- Ein fehlender Ordner wird als `not_found` gemeldet statt als `path_denied`, ChatGPT hält ihn nicht mehr für gesperrt (#226).
- Die CLI blättert lange Listen (#221).

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
