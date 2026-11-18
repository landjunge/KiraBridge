# KiraBridge 0.8.0 RC56

macOS-Kandidat nach RC55. Schwerpunkt: Aufräumen.

Neu gegenüber RC55:

- AutoNext ist entfernt (#232): die alte, nie benutzte Kette über Codex-Fenster (Paket, Tests, Skripte, Dokumente,
  Operation `autonext.control`, Werkzeug `coordinator_status`, Lesezugriff `coordinator.status`, Konfigurationsabschnitt,
  Gesundheitsfeld). Die Fortsetzung übernimmt `team.coordinator_resume`. Ein alter Abschnitt `[autonext]` in einer
  Konfigurationsdatei wird ignoriert. Der Werkzeugkatalog wird dadurch weiter kleiner.

Offen und nicht Teil dieses Releases:

- TollGate-Adapter: sinnvoll erst, wenn in TollGate ein Limit für einen Agenten gesetzt ist.
- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
