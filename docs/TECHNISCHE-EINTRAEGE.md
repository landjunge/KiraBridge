# Technische Whiteboard-Einträge

ThreadDesk bleibt die Ablage für Pläne, Entscheidungen, wichtige Erkenntnisse und aktuelle Stände. Fortschritt, Claims, Aufträge und Probleme (`progress`, `claimed`, `task`, `problem`) schreibt KiraBridge nicht mehr auf das Board.

Der Aufruf wird nicht abgewiesen. KiraBridge speichert ihn in der vorhandenen Audit-Tabelle (`kind` `whiteboard.technical`) mit Thread, Art, Akteur, Zeit, Hash und höchstens 2000 Zeichen Text und antwortet mit Erfolg (`routed` `kirabridge`, `stored` true). `decision`, `result`, `note` und jeder andere oder fehlende Typ gehen weiter an ThreadDesk.

Schalter in der KiraBridge-Konfiguration, Standard an:

```toml
[threaddesk]
route_technical_entries = false
```

`false` stellt das bisherige Schreiben auf das Board wieder her. Der Schalter ändert keine Rechte und startet keinen weiteren Dienst.
