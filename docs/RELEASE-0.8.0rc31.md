# RC31 – weniger UI-Leseaufrufe und schnellere Ereignisabrufe

RC31 ergänzt direkte native JSON-Reads über den bestehenden `read_query`-Alias
(`operation="native.read"`). Apps, Fenster und Accessibility-Elemente können
ohne neue Tasks oder Completionmeldungen gelesen werden. Aktuelle Rechte,
manuelle Freigaben, Zielidentität und native Integritätsprüfungen bleiben wirksam.

`accessibility.inspect` liefert mit `max_depth>0` einen begrenzten Unterbaum mit
normalen aktuellen Elementtokens und Revisionen. Tiefe, Knotenmenge, Antwortgröße
und Zeit sind begrenzt; Teilansichten sind ausdrücklich erkennbar. Standardmäßig
bleibt die bisherige einzelne Inspektion aktiv. Im synthetischen 121-Knoten-Test
reicht eine Baumoperation statt 40 Einzelinspektionen. Für diesen Baum ist ein
explizit größeres Antwortbudget nötig, beispielsweise `max_bytes=262144`.

Ein nativer Read über den tatsächlichen lokalen HTTP-/MCP-SDK-Pfad benötigte bei
gleichem synthetischem Ergebnis im Median **7,58 statt 14,23 ms** (je 30 Samples).
Jeweils ein HTTP-Aufruf; 30 Tasks, 150 Events und 30 Notices entfallen. Das ist
kein Cloud-, Browser- oder Voice-Zeitvergleich.

Ereignisabfragen prüfen Eigentümer und Rechte, ohne große Taskausgaben mitzulesen.
Ein additiver Datenbankindex beschleunigt den gezielten Zugriff. Im kontrollierten
lokalen 4-MiB-/100k-Ereignistest sank der Median von 36,40 auf 0,049 ms.

380 relevante Tests und unabhängige Teamreviews bestanden. Intel-Build,
isolierte Paketabnahme, unabhängiger Paketvergleich und echter Installerdownload
bestanden. Alle sieben Assets des Prereleases sind verfügbar.
Die produktive RC30-Installation bleibt während des parallelen Windows-Auftrags
aktiv; RC31 wird hier nicht automatisch installiert. Bestehende Sitzungen,
Konfiguration und Zugriffsrechte bleiben erhalten.

[Bericht, Messdaten und Auslieferungsstand](https://github.com/landjunge/KiraBridge/blob/perf/rc31-latency-20261103/docs/RC31-NATIVE-READS-20261103.md).
