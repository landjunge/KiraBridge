# RC28 — echte Tastensequenzen und weniger externe MCP-Zyklen

`keyboard_sequence` führt bis zu 32 echte native Tastenpaare in einem dauerhaften,
idempotenten Task aus. Kein Unicode-Blocktext, kein Clipboard. Ziel und Rechte
werden vor jedem Schritt frisch geprüft; Teilfehler/Unknown stoppen die Folge,
ohne bestätigte oder ungewisse Eingaben automatisch zu wiederholen.
`keyboard_control` bleibt für separate/adaptive Einzelschritte erhalten.

`read_queries` bündelt bis zu acht unabhängige autorisierte Reads. Der Proxy
behält Schemas bis zu 30 Sekunden, invalidiert bei Epoch-/Verbindungswechsel
und Notifications und prüft Ausführung weiterhin serverseitig. Das vollständige
JSON-Textfallback wird verlustfrei komprimiert; strukturierte Daten, eigene
Textantworten und Bilder bleiben erhalten. Standard-MCP-Metadaten liefern lokale
Daemon-/Proxy-Zeitspannen ohne Argumente oder Protokollspeicher.

Neu nachgewiesen: Ein Apps-Werkzeugaufruf erzeugt jeweils Initialize,
Initialized-Notification und eigentlichen Call als drei externe Zyklen. Kleine
Fähigkeitsabfragen benötigen dort schon median 2,67 Sekunden ohne Voice.
Lokale wiederholte Calls verursachen diesen Zusatz nicht. Bündelung reduziert
diese Plattformübergaben; sie beseitigt keine externe Latenz eines weiterhin
notwendigen einzelnen Aufrufs. [Untersuchung](RC28-E2E-LATENCY-20261103.md).

Lokale Native-Tests: je fünf gleiche Durchläufe „Stern am“, acht echte Down/Up-
Paare, Hash/Cursor korrekt, Clipboard unverändert; abgeschlossene Idempotenz
produziert keine weiteren Events. Lokale und echte Apps-Messungen einschließlich
P50/P95, Fehlerläufen und Grenzen stehen im Bericht. Intel-Paket und produktive
Installation werden nach Abschluss separat belegt. Keine GitHub Actions.
