# Gemeinsamer KiraBridge-Modulvertrag (Entwurf)
Module bleiben eigene Produkte. Der Bridge-Modulmanager soll registrierte Provider mit Name, Version, Capabilities, JSON-Eingabe-/Ausgabeschema, Berechtigungsbedarf, Gesundheitszustand und Belegreferenz entdecken. Unbekannte Fähigkeiten bleiben deaktiviert. Aufrufe müssen eindeutige Auftrags-IDs, strukturierte Fehler und nachvollziehbare Ergebnisse haben. Keine globalen Freigaben durch ein neues Modul.

Reihenfolge: 1) tatsächliche Funktionen der Zielprogramme lesen; 2) kleine Adapterverträge festlegen; 3) Stub-/Mocktests; 4) echte Integration mit begrenzten Rechten; 5) dokumentierte Abnahme. Kein Fork oder zusätzlicher Branch nötig, bevor konkrete Implementierung beginnt. Brainstorming ist keine fertige API.
