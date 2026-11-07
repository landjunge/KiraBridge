# Brainstorming: Agent Authority × KiraBridge
Stand 2026-10-22. Planung, kein implementiertes Modul.

Ziel: Per Sprache nach Gefahren, erfolgreichen Ausführungen und Evidenz fragen; vorhandenen Authority Graph verwenden, nicht neu in KiraBridge bauen.

Geplante read-only Operationen: status, agents/list, authority/check, delegation/trace, evidence/get, warnings/list, graph/query. Abfrage: „Zeig mir den roten Punkt“ → belegter Agent/Delegation/Prozess/Wirkung mit Evidenz-IDs. „Was lief gut?“ → nachgewiesene erfolgreiche Ausführung getrennt von Ergebnisqualität.

Status: Grün = im geprüften Scope belegt, Gelb = Nachweislücke/unklare Identität, Rot = nachgewiesene Verletzung; Unbekannt als eigenständiger Zustand, niemals grün raten. Keine automatische Eskalation oder Rechteänderung durch bloße Auswertung.

Offen: aktuelle Agent-Authority-API, Datenmodell, Authentifizierung externer Agenten, Belegabdeckung und tatsächlicher Graph-Render.
