# Technische Whiteboard-Einträge

ThreadDesk bleibt die Ablage für Pläne, Entscheidungen, wichtige Erkenntnisse und aktuelle Stände. Fortschritt, Claims, Aufträge und Probleme (`progress`, `claimed`, `task`, `problem`) schreibt KiraBridge nicht mehr auf das Board.

Der Aufruf wird nicht abgewiesen. KiraBridge hält je Principal, Thread, Akteur und Art nur den letzten Stand im laufenden Prozess und schreibt weder ein Audit noch die Datenbank. Die Antwort nennt `routed` `kirabridge` und `kept` `latest_state_only`. Ein neuer Stand ersetzt den alten desselben Schlüssels. `decision`, `result`, `note` und jeder andere oder fehlende Typ gehen weiter an ThreadDesk.

Schalter in der KiraBridge-Konfiguration, Standard an:

```toml
[threaddesk]
route_technical_entries = false
```

`false` stellt das bisherige Schreiben auf das Board wieder her. Der Schalter ändert keine Rechte und startet keinen weiteren Dienst.
