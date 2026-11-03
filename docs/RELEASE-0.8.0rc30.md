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

204 gemeinsame relevante Tests bestanden, unabhängige Reviews und kontrollierte
lokale Vorher-/Nachhermessungen dokumentiert. Die verbleibenden Cloud-Sekunden
werden nicht mit lokalen Millisekunden gleichgesetzt. Intel-Paket, verfügbare
Assets, tatsächliche Installation und echter Apps-Nachlauf werden erst nach
Verifikation bestätigt. [Untersuchung](RC30-HOTPATHS-20261103.md).
