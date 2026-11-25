# KiraBridge 0.8.0 RC80 — Codex 0.172 und sichere Bindungswiederaufnahme

Source-only release candidate. No package was built or installed, and no release was published.

Neu gegenüber RC59:

- **Native Codex host pin:** Unterstützt den exakten verwalteten App-Server `0.172.0` neben den
  bisherigen `0.169.x`- und `0.171.0`-Pins. Prozess-, UID-, Startzeit-, argv-, Peer-PID-, Socket-,
  Inode-, `CODEX_HOME`- und Thread-Root-Prüfungen bleiben aktiv. `0.172.1`, `0.173.x`, andere
  Releasepfade/Architekturen und abweichende Handshake-Identitäten werden abgewiesen. Es wurde kein
  Resume-Pfad ergänzt.
- **Bindungen nach Tabbewegung und Core-Neustart:** Dieselbe verifizierte Codex-Prozessgeneration
  kann nach einer Tabbewegung wiedergefunden werden; Übergabe, Reservierungen und Rootbindung
  bleiben an die nachgewiesene Sitzung gebunden.
- **RC59-Overlay-Migration:** Alte Overlay-Zeilen ohne Protokollfingerabdruck werden nicht beim
  Start als aktuelle Bindung übernommen. Ein neuer Zielprozess wird erst nach vollständigem
  Live-Katalog, bestätigter Abwesenheit des alten Ziels, stabiler Zielgeneration und Eindeutigkeit
  übernommen. Vorhandene `owner_started_assignment`-Lineage wird nur bei exakt passender Live-
  Generation fortgeführt. Ein altes Codex-Protokollpaar wird nie in einen Ersatzprozess kopiert;
  bei ungeklärter Herkunft bleibt das Ziel `ambiguous` und verlangt eine neue exakte Zuordnung.
  Manuelle Protokolländerungen haben Vorrang vor einem älteren Overlay.

Gezielte Abnahme: 154 Tests bestanden über Native Codex Host Identity/Delivery, sichtbare Bindungen,
Zielersetzung, Terminalwiederverwendung und Core-Neustart. Ruff-Prüfung, Formatprüfung und
`git diff --check` bestanden.

Release-Status: Quellkandidat. Paketbau, Signierung, Installation, Veröffentlichung und Neustart
sind nicht erfolgt. Die README-Downloadlinks bleiben auf RC59, dessen veröffentlichte Artefakte sie
adressieren.
