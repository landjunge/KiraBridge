# KiraBridge 0.8.0 RC55

macOS-Kandidat nach RC54. Schwerpunkt: Stabilität und Geschwindigkeit, gemessen an der echten Installation.

Neu gegenüber RC54:

- Leerlauf: Die Bridge verbraucht im Leerlauf weniger CPU (gemessen an einer Kopie der echten Datenbank:
  von 3,5 % auf 0,8 %). Die Aufräumung des Ausgabeverlaufs lief bei jedem Wecken der Arbeiter; jetzt höchstens alle 30 Sekunden,
  vor jedem Schreiben wird weiterhin aufgeräumt (#229).
- Werkzeugkatalog: Die veröffentlichten Eingabeschemata der 81 Werkzeuge tragen keine erzeugten Titel mehr
  (rund 25 % kleiner, etwa 2.400 Token weniger je Gespräch; Prüfung der Eingaben unverändert) (#230).
- Das Stundenlimit des Teams blockiert keine Arbeit mehr, es wird nur vermerkt (`team.limit_noted`). Budgets gehören in TollGate (#228).
- Ein Herzschlag-Fehler beim Verlängern der Auftragsmiete beendet den Herzschlag nicht mehr stillschweigend (#228).

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
