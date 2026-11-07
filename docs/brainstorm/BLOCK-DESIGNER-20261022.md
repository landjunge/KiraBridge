# Brainstorming: Block Designer × KiraBridge
Stand 2026-10-22. Planung, kein implementiertes Modul.

Ziel: Eigenständiges Grafiktool über KiraBridge per Sprache bedienen; keine zusätzliche Ampel für gewöhnliche Designaufgaben. Vorhandene Toolfunktionen zuerst inventarisieren und nur belegte Fähigkeiten exponieren.

Geplante Operationen: Projekt öffnen, Elemente/Farben ändern, speichern, exportieren; Undo/Redo (mindestens fünf Schritte) und Snapshot vor größeren Änderungen als Anforderungen an Block Designer selbst, sofern nicht bereits vorhanden. KiraBridge leitet autorisierte Befehle weiter, führt keine eigene Grafik-Historie. Änderungen an Projekten sollen nicht unbemerkt überschrieben werden.

Modulvertrag (Entwurf): capabilities/list, project/open, design/edit, project/export, history/undo, history/redo, snapshot/create, snapshot/restore. Jede Capability mit verfügbar/nicht verfügbar, Eingabeschema und Version kennzeichnen. Keine Secrets- oder 4AllPass-Rechte.

Offen: tatsächliche Block-Designer-API, vorhandene Undo-/Snapshot-Funktionen, Projektschema, Fehler- und Versionsmodell.
