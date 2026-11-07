# RC30: lokale MCP-Validierung und passiver Discoveryverkehr

Aufbauend auf RC28/29; keine Cloud-, Voice-, UI- oder Produktivkonfigurationsaktion.
Diese Teiluntersuchung beschleunigt belegte lokale Arbeit und beansprucht keine
Beseitigung der weiterhin externen Sekunden pro Cloud-Roundtrip.

## Neuer lokaler Befund und Änderung

Der lokal installierte MCP-SDK-1.30-Quellcode führt im Lowlevel-Proxy vor jedem
Toolcall `jsonschema.validate(arguments, inputSchema)` aus. Der SDK-Client nutzt
dieselbe Funktion zur Outputprüfung. `jsonschema.validate` prüft dabei auch das
unveränderte Schema erneut gegen sein Metaschema. Am wirklichen registrierten
Keyboard-Control-Schema benötigt das rund 18 ms, obwohl keine Taste ausgeführt
wird. Die eigentliche Instanzprüfung eines bereits geprüften Schemas ist deutlich
kürzer.

`SchemaValidatorCache` behält deshalb ausschließlich fertig geprüfte Validatoren:
maximal 64 Einträge und 8 MiB kanonische Schemadaten. **Jede Instanz wird weiter
validiert.** Der vollständige kanonische Schemainhalt wird bei jedem Call neu
verglichen, einschließlich In-place-Änderungen. Die kompilierte Dokumentkopie
kann durch nachträgliche Änderungen des Peerobjekts nicht verändert werden.
Ungültige Schemas werden nicht gecacht. Der SDK-Client und Proxy-Inputpfad nutzen
diesen Cache; Ergebniscaches und Autorisierungsentscheidungen bleiben unberührt.
Dokumentlokale `$ref`s funktionieren. Eine explizit leere Ref-Registry bewahrt den
SDK-Schutz gegen Netzwerkabruf fremder Schemareferenzen auch im Proxy.

Der weiterhin jede Sekunde laufende Proxy-Monitor nutzt künftig das kleine
`bridge_epoch`, sofern der aktuelle Backendkatalog dieses anbietet. Alte Backends
verwenden `bridge_health`. Das neue Tool prüft bei jedem Call das aktuelle
`bridge.health`-Recht und ermittelt dieselbe Permission-/Instanz-/Plattform-/Session-
Revision wie die volle Discovery. Kein Hash-/Integritäts-, Rechte- oder
Ergebniscache. Explizites `bridge_health`, explizites `tools/list`, Epoch-
Invalidierung, Verbindungswechsel, Notifications und dynamische ThreadDesk-
Katalogabfragen behalten ihre frischen Pfade. Nur der passive Rückgabekörper wird
kleiner. Die bisherige Unterdrückung unveränderter erfolgreicher Auditmeldungen
gilt auch für Epoch; Fehler und Recovery bleiben sichtbar.

`discovery.snapshot` und `epoch` teilen dieselbe Berechnung ihrer Fakten. Eine
Permissionrevision wird innerhalb einer synchronen Beobachtung wiederverwendet,
statt sie mehrfach identisch zu hashen. Der Server heftet dieselben frischen
Epoch-Metadaten an die aktuell registrierten Tools.

## Kontrollierte Vorher-/Nachhermessung

[Reproskript](../scripts/benchmark_mcp_hotpaths.py): privater temporärer Core,
echter MCP-SDK über Loopback-HTTP, gleiche begrenzte Grants. Basisquellen aus
`git archive adf69e0 src`, Kandidat aus dem RC30-Arbeitsbaum; Quellfingerprints
werden vor dem Lauf erfasst und sind nach beiden Läufen unverändert. Keine
produktiven Credentials geladen, keine Tasks angelegt, kein nativer Worker
gestartet. Das Keyboard-Schema wird ausschließlich validiert und niemals aufgerufen.

Methodenkorrektur: Die anfängliche explorative Serie ist **keine gültige
Vorher-/Nachherbasis**. Ein reines Sourcearchiv ohne `.git` und `pyproject.toml`
wurde vom Native-Release-Resolver als ungültiges Installationslayout behandelt
(`expected_commit=""`), der Kandidat als Developmentcheckout. Dadurch unterschieden
sich native Verfügbarkeit und Toolkatalog unabhängig vom untersuchten Fix.
Die ursprünglichen JSONs bleiben privat als `*-methodology-exploratory.json`
unter dem RC30-Profilingbackup erhalten und werden durch die folgende Serie ersetzt.

Beide Varianten erhalten jetzt ausdrücklich dieselbe temporäre
`MetadataFixture.app`: gültige Identifier-/Protocol-/Fake-Sourcepin-Metadaten,
eine **59 Byte** kleine Mode-0755-Datei und deren identischen SHA-256. Apppfad,
erwarteter Commit und Binärhash werden am bereits gemeinsam referenzierten
privaten Transport gesetzt; Keyboard-, Terminal- und Providerreferenzen werden
geprüft. Ein Factoryguard verhindert jede Ausführung. Beide Metadatenpreflights
bestätigen vor den Zeitmessungen dieselbe Verfügbarkeit. Grant- und Fixturehashes
stimmen überein, Ausführungsversuche bleiben null. Dies prüft den passiven
Metadatenpfad und bestätigt keine tatsächliche Native-App-Ausführung.

Je Domäne n=20; Median und Nearest-Rank-P95. Der erste Call bleibt enthalten.
CPU ist Prozess-CPU. Peakallokation wird in **einem zusätzlichen einzelnen Call**
mit Tracemalloc beobachtet, getrennt von den Latenzsamples. Größen sind erneut
serialisierte MCP-Ergebnisobjekte in UTF-8, keine Transportpaketmessung.

| Lokaler Pfad | Vorher P50 / P95 ms | RC30 P50 / P95 ms | CPU-Summe vorher / RC30 ms |
| --- | ---: | ---: | ---: |
| explizites frisches SDK `tools/list` | 19,864 / 48,598 | 22,575 / 53,267 | 437,478 / 450,117 |
| registriertes Keyboard-Inputschema, nur Validierung | 17,409 / 24,196 | 0,185 / 0,252 | 342,294 / 21,824 |
| passiver SDK-/Proxy-/Core-RPC: Health → Epoch | 11,101 / 21,896 | 6,794 / 19,134 | 236,835 / 150,899 |

Der erste Schema-Call bleibt bei **19,261 → 20,421 ms**; der Cache spart die
wiederholte Metaschemaprüfung. 21 erfolgreiche Schema-Prüfungen einschließlich
des Allokationscalls werden zu einer. Das ist ein belastbarer lokaler
Wiederholungsfix, kein Cloud-Latenzversprechen.

Die passive Ergebnisgröße sinkt von etwa **35.517 auf 1.336–1.342 Bytes**,
ungefähr 96 %. Die Frequenz und jeder aktuelle Auth-/Epochcheck bleiben bestehen.
Die ersten vollständigen passiven Calls benötigen **42,629 → 34,801 ms**, weil
auch der kalte Metadatenpfad enthalten bleibt; solche Ausreißer werden nicht
weggewärmt.

**Explizites `tools/list` wurde in dieser Serie nicht schneller.** Der frische
Katalog wächst von 71 auf 72 Tools und von 88.893 auf 90.069 serialisierte Bytes.
Die einzige zusätzliche Toolidentität ist `bridge_epoch`; kein Tool entfällt.
Zeitlich getrennte Serien und parallele lokale Arbeit begrenzen kleine
Unterschiede; aus den Daten wird weder ein List-Speedup noch alleinige
Schemaanzahl-Kausalität abgeleitet.

Die einzelnen Peakallokationen betragen List **33.691.527 → 1.169.801 Bytes**,
Schemavalidierung **27.386 → 23.658 Bytes** und passiver RPC
**33.674.201 → 349.480 Bytes**. Mit identisch verfügbarer Native-Metadatenfixture
wird die frühere 32-MiB-Reservierung beim Binärlesen jetzt auch im RPC-Pfad
ausgeübt. Der Allokationsrückgang ist deshalb ausdrücklich ein **kombiniertes
RC30-Ergebnis einschließlich des Native-Dateilesefixes**, kein isolierter
Effekt des Validatorcaches oder des kleineren Epoch-Payloads. Beide Seiten
führen weiterhin eine frische Datei-/Hashprüfung aus.

[Vorherdaten](evidence/rc30-mcp-hotpaths-before-20261103.json),
[Kandidatendaten](evidence/rc30-mcp-hotpaths-after-20261103.json).

Beispiel, jeweils im gleichen vorhandenen Pythonumfeld:

```sh
PYTHONPATH=/path/to/baseline/src python scripts/benchmark_mcp_hotpaths.py --label rc29-adf69e0 --output before.json
PYTHONPATH=src python scripts/benchmark_mcp_hotpaths.py --label rc30-candidate --output after.json
```

## Prüfung und Grenzen

50 gezielte Prüfungen für Schemaänderungen, jede Ergebnisinstanz, lokale/externe
Refs, Größen-/Eintragsbounds, echte HTTP-Kontexte, Rights-Revisionswechsel,
Quiet-Health-Fehler, Proxycache-Invalidierung und Catalogbudgets bestanden.
Danach bestanden die beiden betroffenen echten SDK-/Stdio-Integrationstests;
der Stdiotest weist nach, dass ungültige Inputs vor dem Backend-Tooldispatch
abgewiesen werden. Acht Epochfälle bestanden nach Ergänzung von Session-,
Plattform-, Instanz- und Legacy-Notificationprüfungen. Die privaten Testfixtures
erzeugen keine produktiven Tasks, Eingaben oder Clipboardzugriffe.

Keine dieser Messungen enthält den gehosteten ChatGPT-Connector, Voice oder die
äußeren Tunnelhandshakes. Insbesondere entsteht aus 18 eingesparten lokalen
Millisekunden keine Behauptung über die zuvor beobachteten Cloud-Sekunden.
Die festen Grenzen von kooperativen Timeouts, frischer Auth und unveränderten
Einzelereignissen bleiben erhalten. Commit, Build, Release und Installation führt
der gemeinsame RC30-Abschluss aus.
