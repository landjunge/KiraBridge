# RC30 – weniger lokale Mehrarbeit und kompakte Sammelantworten

RC30 beseitigt mehrfaches Auflösen fertiger Taskausgaben, wiederholte
Metaschema-Kompilierung und übergroße Speicherreservierung bei frischen nativen
Integritätsprüfungen. Der passive Proxy-Monitor überträgt bei gleicher Frequenz
nur die frische Discoveryrevision. Rechte, Eingabe-/Ausgabevalidierung und
native SHA-Prüfungen bleiben aktuell.

Sammelantworten prüfen ihr Größenbudget linear. Optional
`read_query(query={"operation":"tool.batch","calls":[...],"result_format":"structured"})`
entfernt ausschließlich nachweislich identische dekorationslose JSON-Textkopien;
strukturierte Daten, Fehler und Metadaten bleiben vollständig. Default `full`
bleibt kompatibel, eigene Prosa und Bilder behalten ihre bisherigen Pfade.

Im echten Apps-Vergleich passt derselbe Workload mit acht gemischten großen
Leseergebnissen in **einen statt zwei Cloudaufrufe**. Über je drei Gruppen sinkt
P50 von **22,720 auf 13,015 Sekunden** (−42,72 %), P95/Maximum von 22,894 auf
15,916 Sekunden. Text und Base64 aller Datenseiten bleiben exakt gleich; die
normalisierte Antwortmenge halbiert sich ungefähr. Kleine Stichprobe, ohne
Voice-/Modellpausen und ohne erfasste Netzwerkbytes; kein allgemeines
Geschwindigkeitsversprechen für einzelne Tools.

204 gemeinsame relevante Tests und unabhängige Reviews bestanden. Lokale
Taskauflösung bei 4 MiB: P50 103,23 → 23,03 ms; wiederholte Inputschemaprüfung
17,41 → 0,185 ms. Explizites `tools/list` wurde nicht schneller. Die verbleibenden
Cloud-Sekunden lassen sich von hier aus nicht einzelnen Plattformabschnitten
zuordnen. Keine neue physische Tastenserie; vorhandene echte Ereignissequenzen
bleiben der passende Weg für vorgeplante Einzeltasten ohne Clipboard.

Genau ein lokaler Intel-Build, Release-Smoke und echter Installerdownload geprüft;
alle sieben Assets verfügbar. Intel-ZIP 3326833 Bytes, SHA-256
`a84e76edec09be23bbb9a7c2f65656db93ac3f9a72660afab4f4d3f03b239630`.
RC30 ist auf diesem Mac installiert, laufende Version und alle 165 Pythondateien
sowie native Dateien unabhängig gegen das Paket geprüft. Konfiguration,
Bestandsdaten und andere Sitzungen erhalten; Rückweg auf RC29 gesichert.
Kein GitHub Actions-/ARM-Build und keine OS-Rechteänderung.

Quell-/Runtimepin: `2d540ee05f945efdd2330b46a1a65a4b94bcb482`.
[Untersuchung mit Messdaten und Grenzen](RC30-HOTPATHS-20261103.md).
