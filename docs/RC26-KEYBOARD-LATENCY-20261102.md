# RC26: Ende-zu-Ende-Latenz aller Werkzeugbereiche

**Aktueller Betriebsstand:** Auf anschließenden ausdrücklichen Nutzerauftrag
ist RC27 (`38223b1`) produktiv installiert und geprüft.
[Installationsbeleg und Erhaltungsgrenzen](RC27-INSTALL-20261103.md).
Die unten dokumentierte RC26-Erhaltung beschreibt den Zustand vor diesem Upgrade.

Auftrag vom 2. November 2026, ergänzt am 3. November: Der Nutzer meldet riesige
Latenz in **allen Werkzeugbereichen**; Tastatur/Notizen dient als konkrete Reproduktion.
Untersucht werden gemeinsame Übergabe-/Orchestrierungskosten und bereichsspezifische
Ausführung getrennt. Intel-macOS 15.7.4, produktiv RC26, Quellstand
`34f5e6d` mit Dokumentationsbaseline `78b182b`. Das separate alte
Codex-Terminal-Statusproblem ist ausdrücklich kein Gegenstand dieses Berichts.

## Ergebnis und Sicherheit der Ursachenfeststellung

Beim historischen Gedichtversuch lagen **96,361 % der beobachteten Zeit außerhalb
der persistierten KiraBridge-Taskausführung**. Die Hypothese eines dominierenden
internen Ausführungsengpasses wird für diesen Versuch nicht gestützt. Die Lücken
enthalten Rücktransport, Verarbeitung der Toolantwort, Modell-/Code-Mode-
Orchestrierung und den nächsten Hintransport. Eine ausschließliche Zuordnung
zu einem Abschnitt **vor MCP-Eingang** wäre durch diese Daten nicht gedeckt.

Der gemeldete Abbruch „Code Mode exceeded the maximum number of tool calls“
ist als Nutzerbericht und persistierte ChatGPT-Arbeitsnachricht belegt. Zusammen
mit zehn abgeschlossenen und anschließend fehlenden Tasks spricht dies für einen
Abbruch der übergeordneten Aufrufkette. Der konkrete Plattformgrenzwert, seine
Zählweise und die Rohtelemetrie des Code-Mode-Laufs bleiben unbekannt. Zehn
angekommene Tastaturtasks beweisen keine allgemeine Zehn-Calls-Quote.

Zusätzlich wurde vermeidbarer lokaler Aufwand nachgewiesen: Der Stdio-Proxy
beschaffte vor jedem Dispatch den vollständigen Werkzeugkatalog. Ein begrenzter
Schemacache reduziert diesen Aufwand. Er behebt keine Plattform-Aufrufquote.
Die wirksamste Abhilfe für zusammenhängenden Text ist der bereits vorhandene
native `keyboard_control(text=...)`-Pfad mit einem Aufruf für den ganzen Absatz.

## Historischer Versuch: ChatGPT → RC26 → Notizen

[Rohzeiten und Statistik](evidence/rc26-keyboard-history-20261102.json), aus
`bridge.sqlite3` ausschließlich lesend exportiert. Prefix
`notes_poem_key_20261102_2340_`: exakt zehn Tasks `_0` bis `_9`, alle `completed`,
70 Taskevents. UTC 22:37:22.411907 bis 22:38:26.893570: **64,481663 s**.
Davon intern `created → finished` insgesamt **2,346416 s**, zwischen abgeschlossenem
und nächstem erstelltem Task **62,135247 s**. `_0` war Return; `_9` war bereits
das Leerzeichen hinter „Der Mond“. Cmd+N, A, B, C, Return und Backspace davor
waren sechs weitere abgeschlossene Tasks mit jeweils 228–355 ms interner Dauer.

| Abschnitt, historische Uhrzeiten | Minimum ms | Median ms | Maximum ms |
| --- | ---: | ---: | ---: |
| created → accepted | 2,328 | 3,163 | 18,269 |
| accepted → running | 10,538 | 10,828 | 41,813 |
| running → target_bound | 85,212 | 106,984 | 180,260 |
| target_bound → native_attempt | 0,863 | 1,024 | 16,570 |
| native_attempt → finished | 82,429 | 93,830 | 123,968 |
| created → finished | 181,983 | 225,227 | 377,605 |
| finished → nächste created | 4773,866 | 6744,804 | 9711,974 |

Native Receipts melden jeweils zwei zurückgekehrte Posting-Aufrufe, keinen
automatischen Retry und `app_processing_confirmed=false`. Das bestätigt Posting,
nicht das Lesen jedes Zeichens durch Notizen. Die zehn Completion-Inboxeinträge
entstanden 3,751–5,735 ms nach Abschluss, blieben aber unabgeholt; dies beweist
keinen Verlust synchroner Toolantworten. Für spätere numerische Task-Suffixe
wurden keine Tasks oder Auditzeilen gefunden.

Der Diagnosespeicher ist bereits ausgeschöpft; letzte `diagnostic.connection`
am 31. Oktober 01:11:44 UTC. Fehlende Diagnose-/Rejecteinträge aus diesem Versuch
sind daher kein Beweis, dass kein Request vor Admission angekommen ist.

## Messabdeckung der gesamten Kette

| Abschnitt | Gemessen / geprüft | Verbleibende Grenze |
| --- | --- | --- |
| Modell, Code Mode, Callbudget | Historische Admission-Abstände; berichteter Limitfehler | Kein Zugriff auf Cloud-Scheduler, interne Zählung oder exakte Fehlerzeit |
| ChatGPT-Discovery und Cache | Offizielle API-/MCP-Primärquellen geprüft | API-Regeln beweisen nicht den damaligen ChatGPT-Cachezustand |
| ChatGPT → öffentlicher Transport | Taskankünfte am lokalen Speicher | Cloud-/Tunnel-/Proxyanteile historisch nicht einzeln zeitlich erfasst |
| Tatsächliches angebundenes Codex-Tool | Fünf serielle `connection_check`-Aufrufe: 655–1079 ms, Median 849 ms | Enthält Host-Werkzeugübergabe und Rückweg, keine Modellpause zwischen Turns; kein ChatGPT-Cloudlauf |
| Lokaler Proxy, Discovery, Dispatch | Echter Loopback-MCP-Vergleich, List-/Dispatchzähler | Kein vollständiger Cloud- oder Stdio-Framing-Latenzlauf |
| JSON, Schemakatalog, SDK | 72 Tools, 88.143 Bytes; Kosten im gemessenen lokalen Roundtrip | Keine isolierte Serialisierungs-Mikromessung oder nachgewiesene Größenlimitverletzung |
| Admission, Queue, Dispatcher | Rohzeiten und Events je Task | Historische Uhrzeiten statt monotoner verteilten Trace-Uhr |
| Native Zielprüfung und Ausführung | Eigener Empfänger, instrumentierte Native-RPCs | Keine allgemeine macOS-/Notizen-Zuverlässigkeitsquote |
| Empfänger / Zeichenfolge | Inhaltshash, Länge, Cursor, Tastenevents, Clipboardgeneration | Historisches Notizen-Posting hat keinen vergleichbaren unabhängigen Readback |
| Rückweg, Completion, Folgecall | Lokaler Response und Inboxzeiten; Zwischenraum historisch | Response-Rückweg und Modellpause historisch nicht trennbar |

Protokoll der neuen lokalen Verbindung: MCP **2025-11-25**, SDK **1.30.0**;
historischer ChatGPT-Handshake unbekannt. Quellen und Interpretation stehen in
[MCP-/Orchestrierungsrecherche](RC26-MCP-RESEARCH-20261102.md). Neuere
Protokollversionen wurden nicht rückwirkend als beobachtetes Verhalten behandelt.

## Bereichsübergreifende Messungen

36 zusätzliche, tatsächlich ausgeführte Leseaufrufe prüfen sechs Bereiche ohne
UI-Eingabe, Clipboardinhalt oder Benutzerdateien. Je Bereich drei Aufrufe vorher
und nachher: Discovery sinkt von drei auf einen Request; jeder Toolcall wird
weiterhin separat ausgeführt. Backend bleibt produktives RC26, variiert wird
nur der gemeinsame lokale Proxy. [Rohdaten](evidence/rc26-cross-domain-latency-20261103.json).

| Bereich | Median vorher ms | Median mit Proxycache ms |
| --- | ---: | ---: |
| Health | 89,41 | 47,40 |
| Clipboard-Fähigkeitsinfo, kein Inhalt | 105,17 | 5,79 |
| Berechtigungskontext | 102,61 | 66,44 |
| Taskübersicht, begrenzt auf eine Zusammenfassung | 102,96 | 6,86 |
| macOS-Fähigkeiten | 136,35 | 75,62 |
| Plattform-Leseabfrage | 106,53 | 41,68 |

Bei den historischen Abständen von etwa fünf bis zehn Sekunden läuft der
Ein-Sekunden-Schemacache zwischen Aufrufen aus. Er hilft schnellen Aufruffolgen;
die beobachteten 62 Sekunden werden damit nicht als behoben dargestellt.

Der Cache ist werkzeugübergreifend, sitzt jedoch im Stdio→HTTP-Proxy. Die
hier eingerichtete ChatGPT-Tunnelroute benutzt `kirabridge --principal chatgpt
connect` und durchläuft diesen Proxy. Ein alternativer direkter HTTP-Client
bekommt diese Optimierung nicht automatisch. Die Verbesserungen liegen lokal
im Bereich einiger Dutzend Millisekunden; sie erklären keine riesige allgemeine
Cloud-/Modellwartezeit. Keine Hochrechnung auf unbeobachtete Werkzeuge.

Der siebte Bereich, `operation_catalog`, brauchte am unveränderten produktiven
Backend median 1363 ms ohne und 1263 ms mit Proxycache. Beide Varianten holten
drei Kataloge für drei Dispatches, weil ein Call länger als die Ein-Sekunden-TTL
brauchte. Der Proxycache allein löst diesen Backendengpass also nicht.
[Separater Beleg](evidence/rc26-catalog-domain-latency-20261103.json).

Im gemeinsamen Serverpfad sind deshalb zusätzlich zwei Ursachen behoben:
Der Operationskatalog verwendete pro passender Operation eine vollständige
native Momentaufnahme und las/hashte dabei das App-Binary wiederholt.
76 Operationen verursachten in der Messung **50 statt benötigter zwei** solcher
Metadatenaufrufe. Jetzt wird die unveränderliche Hostplattform direkt verwendet.
Health berechnet seine normale Discovery nur einmal statt zweimal. Drei
alternierende direkte FastMCP-Paare mit echtem installiertem Binary ergaben
median **250,03 → 65,96 ms** für den Operationskatalog und **9,28 → 4,82 ms**
für Health. Dies ist ein direkter Funktionsbenchmark mit temporärem Zustand,
kein gemessener Cloud-/HTTP-Geschwindigkeitsfaktor.
[Messdaten](evidence/mcp-request-snapshots-20261103.json).

Außerdem liest `operation_catalog` Terminal-Sitzungen nur noch auf ausdrücklichen
Wunsch `observe_terminals=true`. Der normale Schemaabruf benötigt keine fremde
Terminalabfrage. Seine Beobachtungen sind explizit `not_probed` oder `cached`,
niemals als aktuelle Inputfreigabe verwendbar. Die tatsächlichen Zielprüfungen
bei Eingabe und die aktuelle Berechtigung je Request bleiben erhalten.
Sieben gezielte HTTP-/Rechte-/Fehlerprüfungen dieses letzten Schritts bestanden.
Diese generischen Serververbesserungen wirken auch für direkte HTTP-Clients.

## Implementierte Änderungen und kontrollierter Vergleich

1. `DaemonConnection` verwendet Schemas höchstens eine Sekunde wieder. Explizite
   Discovery bleibt frisch; Verbindung, Epochwechsel und Änderungshinweise
   invalidieren den Cache. Autorisierung und Zielprüfung erfolgen weiterhin je
   Ausführung. Ausführungsergebnisse werden nicht gecacht und Eingaben nicht wiederholt.
2. `keyboard.control` wartet bis zu zwei Sekunden auf denselben dauerhaften Task,
   damit kurze Aktionen häufig schon im ersten Response ihr Ergebnis enthalten.
   Ein überschrittenes Wartebudget beendet weder Task noch native Ausführung;
   danach wird derselbe Task abgefragt. Diese Änderung spart bei kurzen Aktionen
   einen zusätzlichen Statusaufruf; sie garantiert keinen Zweitsekunden-Abschluss.
3. Discovery und Werkzeugbeschreibung empfehlen einen ganzen Absatz einschließlich
   Zeilenumbrüchen pro Textrequest. Abhängige Aktionen bleiben seriell; `repeat`
   bündelt gleiche Tasten. Eine allgemeine neue Mischsequenz-API wurde nicht eingeführt.

| Lokaler Vergleich | Vorher | Nachher |
| --- | ---: | ---: |
| 10 lesende Health-Dispatches: Katalogabfragen | 10 | 1 |
| Dieselben Health-Aufrufe: Median | 86,64 ms | 28,90 ms |
| 8 einzelne Tasten am eigenen Empfänger: Gesamtdauer | 2,1637 s | 1,7498 s |
| Identische 8 Zeichen nach beiden Durchläufen | Hash und Cursor korrekt | Hash und Cursor korrekt |

[Katalogmessung](evidence/rc26-catalog-cache-benchmark-20261102.json) und
[native Messung](evidence/rc26-native-keyboard-latency-20261102.json): kleine,
sequenzielle Stichproben, feste Vorher-/Nachher-Reihenfolge, möglicher Warmup-Effekt.
Im nativen Vergleich ist das zweisekündige Inline-Warten **in beiden Varianten**
aktiviert; dort wird der Cacheeffekt und nicht ein Gesamt-RC26-Upgrade isoliert.
Instrumentierung einschließlich synchroner Evidenzschreibvorgänge ist enthalten.

Das 41-Zeichen-Testgedicht gelang mit **einem Textcall in 0,4227 s einschließlich
Readback**. Erwarteter Hash, 41 UTF-16-Einheiten und Cursorposition stimmten;
Clipboardgeneration blieb unverändert, kein Retry und kein zusätzliches Return.
Dieser Textpfad kann AX-Texteinfügung verwenden; er verspricht keine physischen
Einzeltastenereignisse. Dies ist eine lokale Architekturdemonstration, kein
Vorher-/Nachher-Geschwindigkeitsfaktor des historischen ChatGPT-Gedichts.

Native Mediane: `apps.list` 22,49 ms, `keyboard.inspect` 58,20 ms,
`keyboard.key` 74,07 ms, `keyboard.chord` 79,02 ms; einmaliger Textcommit 198,01 ms.
143 Metadaten-/Identitätsprüfungen kosteten median 3,67 ms. Daraus folgt kein
sinnvoller Anlass, sicherheitsrelevante Zielidentität über Requests zu cachen.

## Tests, Fehlerläufe und Betriebsstand

101 gezielte lokale Tests bestanden in 14,2 s; zusätzlich 28 Paketvertrags-
und Installer-App-Tests in 0,38 s. [Prüfbeleg](evidence/rc26-latency-tests-20261102.json). Analyseprüfungen sichern Read-only-
Zugriff und Inhaltsminimierung; Cacheprüfungen erfassen Ablauf, Invalidierung,
Verbindungswechsel, Racebedingungen und Rechteentzug; Keyboardprüfungen erfassen
Inline-Ergebnis und unveränderten dauerhaften Task bei Wartezeitüberschreitung.
Drei zusätzliche Discovery-/Terminalfixture-Fehler reproduzieren auch auf der
unveränderten Baseline; sie sind keine bestandenen Checks und kein Ergebnis
zum ausgeschlossenen „working“-Problem.

Zwei anfängliche native Läufe wurden nicht als Erfolg gezählt: Lauf 01 erwartete
fälschlich sofort `completed`, obwohl RC26 `queued` zurückgeben darf; Harness
korrigiert, ursprünglicher Task vor Cleanup abgeglichen. Lauf 02 erhielt alle
16 Eingabezeichen korrekt, endete aber beim 20. Task, dem späteren Cleanup-
Backspace, mit `unknown / macos_target_changed`. Ursache nicht aufgeklärt;
keine Wiederholung der unsicheren Eingabe. Alle drei Läufe wurden vollständig
bereinigt; eigener Empfänger und Worker unabhängig zweimal abwesend geprüft.

Weitere aktuelle Kosten bleiben sichtbar: `connection_check` liest ausdrücklich
Terminalmetadaten; dynamische `td_*`-Aufrufe prüfen nachgelagerte ThreadDesk-Kataloge
mehrfach und seriell. Diese fachlichen Prüfungen sind keine reine Transportlatenz
und werden nicht durch den Core-Schemacache aufgehoben. Es wurde weder ein
Rechte-/Zielcache noch ein Cache für Seiteneffekte eingeführt.

Produktive RC26-Installation und andere Sitzungen wurden nicht geändert.
Kein neuer kompletter ChatGPT-Cloudlauf, keine garantierte Ende-zu-Ende-Zeitzusage
und keine vollständige Fehlerfreiheit beansprucht. Nach unsicherem Ausgang:
ursprüngliche Task-ID abfragen, Ziel unabhängig lesen, niemals unter neuer ID
blind erneut tippen. Code, Messdaten und Untersuchungsbericht sind auf dem
Branch `fix/rc26-keyboard-latency-20261102` gesichert; abschließende Paketprüfung
und veröffentlichter Commit werden unten ergänzt.

## Abschließender Quell-, Paket- und Betriebsstand

Implementierung gepusht: `08209f1` (Cache/Inline/Textweg) und
`38223b16ed286aacf951f91890a6eafae6ea88f0` (gemeinsame Serverpfade und
bedarfsgesteuerte Terminalbeobachtung). Die letzten 27 betroffenen Regressionen
bestanden in 13,63 s; Ruff/Format und Lockdateiprüfung bestanden.

[RC27 für Intel veröffentlicht](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc27):
finales Installationspaket lokal aus `38223b1` gebaut, Signatur/Architektur/
Checksummen und echte isolierte Paketinstallation geprüft. Der veröffentlichte
Installer wurde erneut heruntergeladen und bytegenau per SHA-256 verglichen.
[Veröffentlichungsbeleg](evidence/rc27-latency-publication-20261103.json).
Das frühere Paket aus `08209f1` bleibt unveröffentlicht erhalten; nach Erweiterung
auf alle Werkzeugbereiche wurde nur der vollständige neue Stand freigegeben.
Der erste GitHub-Upload scheiterte mit HTTP 408; nach Zustandsabgleich gelang die
verifizierte Übertragung über HTTP/1.1. Dies ist kein KiraBridge-Latenzbefund.

Produktiv bleibt ausdrücklich **RC26**, PID 21419, unveränderte Runtimeinstanz;
die Optimierungen sind im veröffentlichten RC27 verfügbar und noch nicht in
die laufende Installation übernommen. Andere Sitzungen und OS-Rechte wurden
erhalten. Im kanonischen ThreadDesk-Whiteboard `188ce4729a62` wurde auf Basis
der beobachteten Threadrevision 487 Ergebnis 127 angehängt und separat vollständig
zurückgelesen. Das ausgeschlossene Codex-„working“-Thema wurde nicht bearbeitet.
