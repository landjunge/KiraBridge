# macOS installation / Installation · RC17

Current supported entrypoints, prerequisites, private authenticated download,
visible-terminal requirement, status, failure handling and rollback are documented
in [Deutsch](INSTALL-DE.md) and [English](INSTALL-EN.md). The [README](../README.md)
contains the single copy command for the actually available reviewed package.
Older source-pinned commands remain in Git history; they do not approve new builds.

Veröffentlicht bleibt RC14; RC17 ist Entwurf. Produktiv läuft derzeit RC17/14468ad.
Die Braille-Integration dieses Branches benötigt ihre eigene Paketabnahme und
verändert weder bestehende Rechte noch Daten oder launchd-Laufzeitverhalten.

Der Dienst läuft nach Schließen von Terminal/Browser weiter. Die produktive
Installation erfolgt nach Freigabe ausschließlich in einem frisch bestätigten
sichtbaren eigenen Arbeitsfenster, das für alle Schritte wiederverwendet wird.
Keine neuen Fenster pro Testschritt und keine Eingabe in andere Agentensitzungen.

Nachgewiesen auf Intel-macOS15.7.4: [source144 Verify](evidence/local-macos-acceptance-14468ad-20261026.json),
[gezielter RC14-Rollback einschließlich Lifecycle-Vorlauf](RC14-ROLLBACK-20261026.md),
[neue native Sichtbarkeitsprüfung](evidence/visible-installer-window-20261026.json).
Originalfehlversuch und erfolgreiche Nachtests werden nicht gleichgesetzt.
Kein ARM- oder gehosteter Actions-Pass wird dadurch behauptet.
