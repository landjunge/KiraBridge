# RC28: verbleibende Grenze zwischen Modell, App-Connector und Mac

Unabhängige Untersuchung am installierten RC27 `38223b1`, aufbauend auf dem
[RC26/27-Bericht](RC26-KEYBOARD-LATENCY-20261102.md). Keine produktive Konfiguration,
OS-Rechte, Fenster, Tasten oder Benutzerdateien durch diese Teiluntersuchung verändert.

## Neu nachgewiesener gemeinsamer Mechanismus

Ein einzelner tatsächlicher App-Aufruf `clipboard_info` erzeugte **drei**
Tunnel-Kommandos: `initialize`, `notifications/initialized`, `tools/call`.
Die Zähler stiegen je genau **82 → 83**, die Response-POSTs **246 → 249**.
Der winzige reine Metadatenaufruf dauerte **2598 ms** ohne Sprach-/Modellturn
zwischen den Messpunkten. Die drei Response-POSTs verbrauchten zusammen
**799,517 ms**; die restliche Zeit ist dadurch nicht vollständig aufgeteilt.
[Einzelcall-Deltabeleg](evidence/rc28-tunnel-single-call-delta-20261103.json).

Auch die Prozesssummen zeigen 82 Initialisierungen, 82 Initialized-Notifications
und 82 Toolcalls. Im vollständigen lokalen Logbuffer steht dagegen nur **ein**
Start des Stdio-MCP-Kindprozesses. Der Mechanismus ist somit wiederholter
Protokoll-Handshake auf dem App-Pfad, **kein nachgewiesener neuer lokaler Prozess
oder neuer TCP-Kanal pro Call**. Im gemessenen Prozess erfolgten alle Antworten
mit Status 200. Ein allgemeiner Plattform-Durchsatzfehler wurde nicht reproduziert.

Der exakt installierte öffentliche Tunnel-Client `0.0.16`, Quellpin
`5f99daabd4aa4a77049e6d81d54a0d8c18335397`, belegt die Semantik:

- [processor.go, Notification-Ack und Responseforwarding](https://github.com/openai/tunnel-client/blob/5f99daabd4aa4a77049e6d81d54a0d8c18335397/pkg/dispatcher/internal/processor.go#L656):
  Notifications erhalten einen Response-POST; Calls werden bis zur Rücklieferung
  weitergeleitet. Die Info-Meldung „forwarded command“ entsteht **nach** dem
  Responseforwarding einschließlich POST, nicht beim ersten MCP-Eingang.
- [stdio_command.go](https://github.com/openai/tunnel-client/blob/5f99daabd4aa4a77049e6d81d54a0d8c18335397/pkg/mcpclient/stdio_command.go#L78):
  das Stdio-Transportobjekt und Kindprogramm werden wiederverwendet.
- [poller.go](https://github.com/openai/tunnel-client/blob/5f99daabd4aa4a77049e6d81d54a0d8c18335397/pkg/controlplane/internal/poller.go#L114):
  nach erfolgreichem Poll läuft die Schleife weiter. Warten/Backoff ist an
  Fehler oder volle Queue gebunden. Kein fester Fünf-Sekunden-Sleep im Erfolgsweg.
- [metrics.go](https://github.com/openai/tunnel-client/blob/5f99daabd4aa4a77049e6d81d54a0d8c18335397/pkg/dispatcher/internal/metrics.go#L58):
  `enqueue_to_response` verwendet Cloud-Enqueuezeit und Hostuhr,
  `poll_to_response` die lokale Abholung bis zur vollständigen Response.

[Minimierte Histogramme](evidence/rc28-tunnel-metrics-20261103.json): über den
bisherigen Prozess, 82 Samples pro Methode, Mittelwerte Enqueue→Response:
Initialize 825,89 ms, Initialized-Notification 694,73 ms, Toolcall 1605,95 ms.
Die 246 Response-POSTs dauerten im Mittel 673,66 ms. Diese Mittelwerte sind
Prozessaggregate verschiedener Callarten; sie werden nicht als exakte Zerlegung
jedes einzelnen Voice-Aufrufs ausgegeben. Histogramm-P50/P95 sind nur obere
Bucketgrenzen, keine rekonstruierten Einzelperzentile. Pollzeiten enthalten auch
30-Sekunden-Leerlauf und dürfen nicht als Zustelllatenz interpretiert werden.

## Kontrollierte werkzeugübergreifende Messung

Je zehn echte, ausschließlich lesende Aufrufe über beide angebundenen Wege,
abwechselnde Reihenfolge, **60/60 ohne Fehler**. Zwischen Calls kein Modell-
oder Sprachturn. Beide Wege erreichten dieselbe laufende RC27-Instanz.
Lokale Tool-Identität `codex`, App-Identität `chatgpt`; diese Differenz bleibt
in der gepaarten Serie ausdrücklich erfasst.

| Werkzeug | lokal P50 / P95 ms | App-Pfad P50 / P95 ms | Anzahl je Weg |
| --- | ---: | ---: | ---: |
| `bridge_health` | 43 / 1628 | 3495,5 / 4926 | 10 |
| `clipboard_info`, kein Clipboardinhalt | 20,5 / 113 | 2668,5 / 5923 | 10 |
| `operation_catalog`, kein Terminalscan | 294,5 / 1198 | 6934,5 / 8533 | 10 |

Gesamtzeit über 30 Calls: lokal **6,477 s**, App **135,873 s**.
P50 = Median; P95 = Nearest Rank `ceil(0,95*n)`. Bei n=10 ist P95 der Maximalwert;
der kalte lokale Health-Ausreißer bleibt enthalten. Kleine Stichprobe, nicht
randomisierte Domänenreihenfolge und anderer paralleler Verkehr begrenzen die
Übertragbarkeit. Die reine Metadatenantwort von `clipboard_info` ist kleiner
als 1 KiB. Der Catalog erzeugte rund 505.000 UTF-16-Einheiten des erneut
serialisierten Ergebnisobjekts; dies sind keine gemessenen Netzwerkbytes.
[Alle Einzelmessungen](evidence/rc28-frontdoor-baseline-20261103.json).

Zusätzliche Kontrolle mit derselben konfigurierten `chatgpt`-Identität über einen
lokalen persistenten HTTP-MCP-Client, je zehn Calls: Health P50/P95 **22,53/74,86 ms**,
Clipboardinfo **6,89/104,83 ms**, Catalog **218,03/291,21 ms**. Zugangsdaten blieben
nur im RAM; keine Identitätsbehauptung eines tatsächlich ausgeführten Voice-Chats.
Dieser Pfad schließt Host-Toolübergabe aus, bestätigt aber schnelle lokale
Ausführung auch unter demselben Principal.
[Kontrollmessung](evidence/rc28-same-principal-local-20261103.json).

## Neuer Voice-Praxistest historisch rekonstruiert

`rc27_realkeys_20261103_0042_0..7`: acht `keyboard.control`-Tasks, alle completed,
jedes Receipt zwei native Posts und kein automatischer Retry. Der Nutzer bestätigt
„Stern am“. SQL-Zeiten: erstes Created bis letztes Finished **33,763208 s**;
Summe interner Taskzeiten **2,538690 s**. **92,481 %** dieses persistierten Fensters
liegen außerhalb der internen Taskausführung. Der gemeldete Gesamtwert **42,504 s**
enthält zusätzlich **8,740792 s** außerhalb dieses Fensters; dafür fehlen
eigenständige Sprach-/Modell-Timestamps. Aus dem Nutzerwert allein lässt sich
keine konkrete ASR-, VAD- oder Modellzeit ableiten.

| Historische Phase | N | Summe ms | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: |
| Created → Accepted | 8 | 86,122 | 9,396 | 27,144 |
| Accepted → Running | 8 | 223,274 | 32,304 | 41,964 |
| Running → Targetbound | 8 | 1355,542 | 118,750 | 391,820 |
| Nativeattempt → Finished | 8 | 804,098 | 101,198 | 132,288 |
| Created → Finished | 8 | 2538,690 | 269,055 | 523,755 |
| vorher Finished → nächste Created | 7 | 31224,518 | 4727,674 | 5912,848 |

[Reproduzierbarer Read-only-Export](evidence/rc28-voice-history-20261103.json):
`python scripts/analyze_rc27_voice_latency.py --db …/bridge.sqlite3 --output …json`.
Der Blocktext-Task `rc27_long_poem_20261103_0040` enthält 570 Codepoints,
davon **568 ohne die beiden äußeren Zeilenumbrüche**. Sein gesamter persistierter
Task dauerte **603,780 ms**; Commitattempt→Finished **317,117 ms**. Das ist mit
dem Bericht „ca. 0,34 s interne Textausführung“ vereinbar, darf aber nicht mit der
Gesamtzeit verwechselt werden. Der externe Wert **3,426 s** bleibt nutzerberichtet.

Im erhaltenen Tunnelbuffer ließ sich jeder der acht Taskintervalle eindeutig
zeitlich in eine vollständige Initialize/Notification/Toolcall-Gruppe einordnen.
Das ist ein **temporaler gleicher-Host-Match**, keine direkte Task-ID-Korrelation,
weil die Task-ID im Tunnel-Info-Log nicht vorhanden ist.

| Weiter aufgelöste Phase | N | Summe ms | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: |
| Initialize-Response gepostet → Core Created | 8 | 10191,043 | 940,224 | 2631,738 |
| Core Finished → Tool-Response gepostet | 8 | 3784,115 | 378,323 | 716,804 |
| Tool-Response gepostet → nächste Initialize-Response gepostet | 7 | 18395,047 | 2735,867 | 4539,114 |

Der letzte Zwischenraum enthält Caller-/Modellorchestrierung **und** den nächsten
Initialize-Roundtrip; er ist keine reine Modellzeit.
[Zeitlich korrelierte, pseudonymisierte Gruppen](evidence/rc28-history-tunnel-correlation-20261103.json).

## Grenzen, Optionen und wirksame Abhilfe

| Abschnitt | Evidenz | Offen / beeinflussbar |
| --- | --- | --- |
| Sprache, VAD, Modellplanung | Nutzer-Gesamtzeit und historische Taskankünfte | keine internen Voice-Timestamps; hier nicht direkt steuerbar |
| App-Orchestrierung | pro kleinem App-Tool drei Tunnel-Kommandos; direkter App-Test ohne Modellturn | Initiierung dieser Sequenz durch gehosteten Caller nicht im KiraBridge-Code |
| Tunnel / Cloudqueue / Netz | drei POSTs pro Appcall, lokale Histogramsummen und korrelierte Logs | Cloudqueue/Netz/Hostanteile nicht vollständig voneinander getrennt |
| Stdio / Proxy / HTTP | langlebiger Prozess, lokale schnelle MCP-Kontrolle | Schema-Cache spart diese Cloud-Handshakes nicht |
| Core Zulassung / Dispatcher | Created/Accepted/Running separat je Task | kleiner Anteil, Schwankung bis ca. 0,52 s pro Tastentask |
| macOS / Nutzerziel | native Postreceipts; Nutzer bestätigt alle acht Zeichen | historischen Notes-Readback unabhängig vom Nutzer nicht vorhanden |
| Rückmeldung | Core-Finished bis Tunnel-Response-POST aufgelöst | Rücklieferung bis Voice-Ausgabe nicht instrumentiert |

Der installierte Client bietet TTL 10 Minuten für lokale Verbindungen. Die
5-Sekunden-Guardrail verlängert das Poll-Deadlinebudget und ist keine Pollkadenz.
`stdio_send_initialized_notification=true` ist bereits konfiguriert. Die
Stateless-Flags des Clients starten **Demo-Stubs**, keine alternative Konfiguration
des KiraBridge-Forwarders. Die angebotenen Optionen enthalten keinen Schalter,
der die vom gehosteten Caller geforderten drei Kommandos in eines verwandelt.
Initialize oder die Notification-Acknowledgements zu unterdrücken wäre kein
nachgewiesen protokollkorrekter Geschwindigkeitsfix. Ein HTTP-Backend kann lokale
Transportdetails ändern; aus dem Quellcode folgt kein Wegfall der drei Cloud-
Kommandos. Produktive Konfiguration oder Tunnel-Binary wurden nicht verändert.

Die [offizielle OpenAI-Tunnel-Dokumentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
beschreibt ausgehendes Polling und Response-Posting sowie derzeit 600 Requests
pro Minute, 10 MiB pro Envelope und 120 Sekunden Gesamtdeadline. Diese Schutzlimits
sind keine Latenzgarantie. Der hier erfasste erfolgreiche Verkehr beweist keine
fixe Fünf-Sekunden-Quote oder deren Erreichen. Der [MCP-Guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
benennt große Werkzeugkataloge als möglichen Latenz-/Kostenfaktor; die deutliche
Kataloggrößen-Korrelation ist deshalb ein weiterer sinnvoller Optimierungspunkt,
aber kein Beweis, dass allein die Bytezahl sämtliche Zusatzzeit verursacht.

Wirksame lokale Architektur: mehrere **echte einzelne Down/Up-Paare** in einer
begrenzten seriellen Serveroperation ausführen, sodass ihre Semantik erhalten
bleibt und die teure äußere Handshake-Sequenz einmal anfällt. Das ist kein
Unicode-/AX-Blocktext. Falls ausdrücklich acht **separate MCP-RPCs mit Modell-
Feedback dazwischen** verlangt werden, bleiben deren externe Roundtrips bestehen;
eine Serversequenz ist dann eine andere Orchestrierungsform und muss so benannt
werden. Entsprechend können unabhängige Leseabfragen in einer begrenzten
Read-Bundle-Operation mehrere äußere Handshakes vermeiden. Zustände und Effekte
werden dabei nicht als Erfolg gecacht; ungewisse Eingaben werden nicht wiederholt.
