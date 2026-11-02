# RC26: MCP- und Orchestrierungsrecherche, 2. November 2026

Unabhängiger Teambeitrag mit OpenAI-Docs-Skill und geöffneten Primärquellen.
Keine feste öffentliche ChatGPT-Code-Mode-Aufrufquote nachgewiesen. Das separate
Codex-Terminal-Statusproblem gehört nicht zu dieser Untersuchung.

## Protokoll und Messgrenzen

Ein eigener authentifizierter, nur lesender Loopback-MCP-Client hat am
2026-11-02T22:51:04Z mit dem laufenden Daemon **protocolVersion 2025-11-25**
ausgehandelt. SDK: **mcp 1.30.0**, entsprechend dem Lockfile. Das belegt diese
zusätzliche lokale Verbindung; die ausgehandelte Version der historischen
ChatGPT-Verbindung bleibt unbekannt.

Die [MCP-Toolspezifikation 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
trennt paginiertes `tools/list`, `tools/call` und
`notifications/tools/list_changed`. Schema-Discovery ist kein Ausführungsnachweis.
Nach [Transport 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
ist ein Disconnect keine implizite Cancellation. SSE-Fortsetzung kann per GET und
`Last-Event-ID` erfolgen; ein verlorener Response erlaubt kein blindes erneutes
POST einer Tastatureingabe. Ein JSON-RPC-Korrelationsbezeichner allein garantiert
keine Idempotenz des Anwendungseffekts.

Neuere [Tools-](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
und [Transportregeln 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
enthalten unter anderem explizite Cachemetadaten, abonnierte Änderungshinweise
und andere HTTP-Cancellation-Semantik. Diese sind nicht automatisch auf die
beobachtete 2025-Verbindung anzuwenden. Ein Protokollupgrade ist für den
begrenzten lokalen Schemacache nicht erforderlich.

## OpenAI-seitige Befunde

Der [offizielle MCP-Guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
beschreibt Discovery als `mcp_list_tools`, danach tatsächliche `mcp_call`-Einträge.
Bleibt der Discovery-Eintrag im Responses-API-Kontext, wird die Liste nicht je Turn
neu abgefragt. Viele exponierte Tools erhöhen möglicherweise Kosten und Latenz;
`allowed_tools` begrenzt die importierte Auswahl. Das ist dokumentiertes
API-Verhalten, kein Nachweis des internen ChatGPT-Caches im reproduzierten Fall.

Der [Programmatic-Tool-Calling-Guide](https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling)
zeigt einen `program`-Eintrag und separate verschachtelte `function_call`-Einträge
mit eigenen Call-IDs. Eine JavaScript-Schleife reduziert gegebenenfalls
Modellwechsel und Zwischenausgaben, verwandelt N Werkzeugaufrufe aber nicht in
eine Serveroperation. Der Guide empfiehlt Idempotenz sowie Messungen von
Modellturns, Toolcalls, Retries und Ende-zu-Ende-Latenz.

Die [Responses-API-Referenz](https://developers.openai.com/api/reference/resources/responses/methods/create)
dokumentiert `max_tool_calls` als gemeinsames Limit eingebauter Tools je Response;
weitere Versuche werden ignoriert. Das ist **kein Beleg für den konkreten
ChatGPT-Code-Mode-Schwellenwert** oder dessen interne Implementierung. Die
Referenz wurde zusätzlich als offizielles `.md` per HTTPS abgerufen, weil die
HTML-Ansicht für das Browserwerkzeug zu groß war. Die exakte gemeldete
Fehlerzeichenfolge ließ sich in den geprüften offiziellen Seiten nicht einer
veröffentlichten festen Quote zuordnen.

[OpenAIs Latenzleitfaden](https://developers.openai.com/api/docs/guides/latency-optimization)
empfiehlt weniger serielle Requests, weil jede Runde zusätzliche Latenz verursacht.
Für Tastaturtext ist serverseitiges Bündeln daher ein sinnvoller Lösungsansatz;
parallel gesendete Tasten bewahren die erforderliche Reihenfolge nicht zuverlässig.

## Lokaler Vorher-/Nachher-Vergleich

[Messdaten](evidence/rc26-catalog-cache-benchmark-20261102.json), reproduzierbar mit
`PYTHONPATH=src python scripts/benchmark_proxy_catalog.py` in einer vorhandenen
Projektumgebung. Das Skript sendet insgesamt 20 nur lesende `bridge_health`-Calls
über eine eigene Loopback-Verbindung; es startet keine native Eingabe, verwendet
kein Clipboard und verändert keine Konfiguration. Baseline-Proxycode aus
Commit `78b182b` und aktueller Proxy werden im selben Prozess verglichen.

| Messgröße | RC26 vorher | begrenzter Schemacache |
| --- | ---: | ---: |
| Tatsächliche Tool-Dispatches | 10 | 10 |
| Metadata-List-Requests | 10 | 1 |
| Median Aufrufdauer | 86,64 ms | 28,90 ms |
| Summe Aufrufdauer | 1133,58 ms | 387,71 ms |

72 Tools, kompakte JSON-Kataloggröße 88.143 Bytes. Die Nachher-Messung enthält
das erste kalte Discovery. Die 1-Sekunden-TTL wurde im schnellen Nachherlauf
nicht erreicht. Geringe Stichprobe, feste Reihenfolge und möglicher Warmup-Effekt:
kein universeller Beschleunigungsfaktor. Gemessen sind lokaler Catalogtransfer,
SDK/Serialisierung und lesender Toolcall zusammen; kein Cloud-, ChatGPT-,
Stdio- oder nativer Eingabebenchmark. Der Calllimit-Abbruch wird dadurch nicht
repariert; nur ein belegter lokaler Aufwand sinkt.

## Review und praktische Empfehlung

Unabhängiges Review von `proxy.py` und `test_mcp_proxy_catalog_cache.py`:
keine blockierenden Defekte gefunden. Wiederverwendet werden höchstens eine
Sekunde alte Schemas, keine Effekte, Antworten, Zielbeobachtungen oder Rechte.
Explizite Discovery bleibt frisch. Verbindungsgeneration, Änderungshinweis,
externer Pool-Refresh und Epochwechsel verwerfen die Wiederverwendung;
fehlgeschlagene Refreshes dürfen keine alten Schemas ausliefern.
Zusätzliche unabhängige Race-Tests prüfen Änderungshinweise während laufender
Discovery und Sessionwechsel vor Dispatch. Zusammen mit den Cachetests:
**11 passed in 0.12s**. Der Implementierungsagent ergänzt einen echten
Rechteentzugstest mit isolierter Konfiguration.

Zusammenhängenden Text über den vorhandenen `keyboard_control(text=...)`-Pfad
übergeben; dieser nutzt den nativen Unicode-Eingabepfad ohne Clipboard.
Gemischte Sequenzen gegebenenfalls als begrenzte, serialisierte Serveroperation
bündeln. Stabile Task-/Idempotenzschlüssel beibehalten. Nach unsicherem Ausgang
die ursprüngliche Task-ID abfragen und den Zielinhalt unabhängig lesen;
keine Wiederholung mit neuer Task-ID. Ein Posting-Beleg bestätigt noch nicht
die Verarbeitung jedes Zeichens durch die Zielanwendung.
