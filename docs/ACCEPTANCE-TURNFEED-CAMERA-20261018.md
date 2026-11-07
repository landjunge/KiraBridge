# Abnahmetestszenario: Turnfeed-Kamerastream

Quelle: Rückmeldung von Theodor Nesfeldt Engøy (@TheodorNEngoy), https://github.com/openai/codex/discussions/55086, 18.10.2026. Externer Vorschlag, kein bestätigter eigener Produktfehler.

## Ausgangslage
Ein Codex-Test mit generiertem Video besteht, während der reale Kamerastream auf der gehosteten Seite weiter hängt. Lokaler Testerfolg ist kein Nachweis der Behebung des ursprünglichen Nutzerproblems.

## Abnahmekriterien ThreadDesk ↔ KiraBridge
1. Originalsymptom und ursprüngliches Nutzerziel bleiben als offene Abnahmekriterien erhalten.
2. Jede Prüfung hält genaue Eingabe (generiertes Video oder echte Kamera), Umgebung, Zeitpunkt, Resultat und Belegreferenz fest.
3. Getesteter Quellcommit, Build, Deployment und tatsächlich auf der gehosteten Seite ausgelieferte Revision werden getrennt dokumentiert; nicht nachgewiesene Deployment-Zuordnung bleibt unbekannt.
4. Generiertes Video: bestanden; echter Kamerastream: ausstehend oder fehlgeschlagen, bis real erfolgreich geprüft; Gesamtauftrag: nicht verifiziert.
5. Versionierte Handoff-/Return-IDs, Revisionen, Task-/Run-Bezug und Belege bleiben nach Unterbrechung oder Agentenwechsel erhalten; doppelte Ausführung und veraltete Rückgaben werden abgewehrt.
6. Ein lokaler Test darf weder die reale Kameraprüfung stillschweigend bestehen lassen noch die Nutzerabnahme ersetzen.

## Testdurchführung
Mit synthetischen Testdaten zuerst erfolgreiche Videowiedergabe und fehlgeschlagenen realen Kamera-Test simulieren. Rückgabe und Status prüfen. Danach Unterbrechung/Agentenwechsel und Wiederaufnahme simulieren, Status und Revisionen abgleichen. Erst nach belegtem realem Kamera-Erfolg darf die technische Prüfung auf bestanden wechseln; Nutzerannahme bleibt getrennt.

Status: Abnahmeszenario erfasst; Implementierung und Ende-zu-Ende-Test noch offen.
Kontakt: Theodor als möglicher externer Tester vormerken; keine Repository-Rechte erteilt.
