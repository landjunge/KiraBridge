# KiraBridge · Zuverlässigkeitsreview vom 1. November 2026

Dieser Bericht ergänzt den [RC24-Fortsetzungsstand](RC24-PREFLIGHT-20261101.md).
Ausgang ist `5fdb454d03d3cda6c0777eb7ccbcf1e54449950d`; Änderungen liegen getrennt
auf `fix/reliability-review-20261101`. Die produktive RC22-Installation wurde
während dieses Reviews weder ersetzt noch neu gestartet. RC23-Tags bleiben erhalten.

## Umfang und Methode

Inventar: 144 Python-Quelldateien mit 38.709 Zeilen sowie vier Swift-Dateien mit
1.473 Zeilen. Drei spezialisierte Agenten untersuchten macOS/Accessibility/Desktop,
Terminal/Sitzungen/Eingabe sowie MCP/Tasks/Nachrichten/Team. Der Koordinator prüfte
Integration, Routing, Authentifizierung, Dateisystem und Testergebnisse. Grundlage
waren vorhandene Architekturberichte, Quellcode, relevante RC22-/RC23-Differenzen,
deterministische Reproduktionen und unabhängige Diff-Reviews. Das ist keine
Garantie für jeden möglichen Zustand externer Programme, Server oder des Betriebssystems.

RC22-Vergleich: `f97ab1cdeebe1d06648febe685f7ebb738ca93a9`; veröffentlichter
RC23-Code: `04faa3b40e972cf155704dc5cb10a1784f8c10cb`. Die unten reproduzierten
Fehler existieren bereits in RC22; frühere Reparaturen des RC24-Ausgangs bleiben
erhalten. Es wurden keine produktiven Tasks wiederholt, Zugangsdaten veröffentlicht,
OS-Rechte geändert oder fremde Terminal-/Agentensitzungen verwendet.

Prioritäten: P1 = erheblicher Daten-/Verbindungszuverlässigkeitsfehler; P2 = begrenzter
Funktionsfehler oder vermeidbarer häufiger Aufwand; P3 = kleinere Verbesserung.
Ein statisch belegter Ablauf ist noch kein belegter praktischer Angriff oder Engpass.

## Repariert und unabhängig geprüft

Alle Pfade beziehen sich auf den Quellstand dieses Branches. Zeilen benennen den
Einstieg des relevanten Abschnitts; die zugehörigen Tests zeigen die genaue Grenze.

| ID | Priorität | Fundstelle | Evidenz und kleine Änderung | Risiko / Tests |
| --- | --- | --- | --- | --- |
| MCP-1 | P1 | `src/kirabridge/mcp_gateway/client.py:462` | Zwei gleichzeitige EOFs konnten denselben Owner zweimal abbauen; der zweite `connection_ids.pop` warf `KeyError`. Abbruch eines wartenden Aufrufers konnte Cleanup liegen lassen. Ein gemeinsamer, gegen Beobachterabbruch geschützter Cleanup pro Owner sammelt auch bereits abgebrochene Owner ein. | asyncio-/AnyIO-Lebenszyklus ist sensibel. Barrieren prüfen parallelen Abbau, Observer-Cancel, Owner-Cancel und Kapazitätsfreigabe. Bestehendes Timeout bleibt. |
| MCP-2 | P1 | `src/kirabridge/mcp_gateway/client.py:316` | Ein verspäteter EOF aus Verbindung A beendete nach Reconnect die Verbindung B; alte Diagnostik bezog sich auf B. Aufrufe binden Session, Owner und Connection-ID; nur die ursprüngliche Generation darf abgebaut werden. Alte Health-/Notice-Ergebnisse überschreiben B nicht. | Keine automatische Wiederholung ungewisser Remote-Aufrufe. Unabhängiger zusätzlicher Repro war vor der Änderung rot und danach grün; Timeout-/EOF-Diagnostik und Ersatzgeneration getestet. |
| MCP-3 | P2 | `src/kirabridge/mcp_gateway/client.py:236` | Eine ToolListChanged-Notification während `list_tools` ging durch abschließendes Löschen von dirty verloren; ein alter Refresh konnte neuen Cache überschreiben. Der Refresh konsumiert nur vorherige Invalidierungen und prüft die Session vor/nach jedem Page-Await. | Fehler stellen dirty für dieselbe Session wieder her. Grenzen von acht Seiten/512 Tools und Duplikat-/Cursorprüfung bleiben. Notification-, Lock-Warte- und Generationstauschtests. |
| MCP-4 | P2 | `src/kirabridge/mcp_gateway/client.py:392` | Ein am globalen Gate wartender Aufruf sprach nach Disconnect A/Reconnect B noch die alte Session A an. Unmittelbar vor `session.call_tool` wird die Generation jetzt erneut geprüft. | Barrieren belegen keinen Dispatch gegen A oder B. `peer_disconnected` behält A-ID und meldet ausdrücklich nur für diesen Client-Request accepted/started/completed=`no`. Nach bereits begonnenem Remote-Aufruf bleiben Fehler konservativ `peer_unknown`; kein Retry. Erfolgreiche Remote-Mutation nach geschlossenem Transport wurde nicht belegt. |
| TERM-1 | P2 | `src/kirabridge/terminal_manager/__init__.py:149` | Gültige JSONL-Zeilen nahe 1 MiB wurden abgewiesen, wenn die nächste Zeile im selben Pipe-Chunk begann. Der Parser trennt pro Chunk einmal und prüft vollständige Zeilen sowie Rest getrennt. Das entfernt wiederholtes Kopieren des gesamten Restpuffers. | 1 MiB Inhaltsgrenze ohne LF; jede zu große Zeile wird vor ihrem Callback abgewiesen. Acht Fälle: Grenzen mit/ohne LF, UTF-8, 20.000 Zeilen, Callbackfehler und Cleanup. Vorher drei rot. |
| TERM-2 | P2 | `src/kirabridge/session_manager.py:788` | `session.open` übernahm den ersten Treffer einer TTY auch bei mehreren Ansichten oder `identity_ambiguous`. Jetzt ist genau ein eindeutiger Treffer erforderlich. | Fünf Fälle, vorher vier rot. Bereits geöffnetes Fenster bleibt als `opened` dokumentiert. Belegt ist eine willkürliche Handle-Übernahme; der alte direkte argv-Pfad hatte danach bereits eine zusätzliche Eingabeprüfung. Kein bewiesener Wrong-Window-Ausführungsbypass. |
| MAC-1 | P2 / P3 | `src/kirabridge/platform_adapters/macos/system_transport.py:87`, `capabilities.py:12` | Syntaktisch gültige Plists mit Array-/Skalarwurzel führten bei `.get` zu `AttributeError`. Beide Grenzen verlangen nun ausdrücklich ein Dictionary und nutzen den bestehenden Fehlerpfad. | Zwölf Fälle mit Array/String/Integer/Bool/Data. Native Metadaten werden weiterhin frisch geprüft; kein Cache von Grants oder Binary-Identität. OS-Versiondatei ist normalerweise nicht vom Nutzer veränderbar; dieser Teil ist zusätzliche Robustheit (P3). |
| AUTH-1 | P2 | `src/kirabridge/security_manager/__init__.py:47`, `bridge_core/config.py:398` | Ein nicht-ASCII-Token in der Umgebung eines Principals ließ `hmac.compare_digest` bei einer legitimen ASCII-Anfrage an einen anderen Principal mit `TypeError` abbrechen. Konfiguration und Authentifizierung prüfen ASCII explizit. | Tests für Unicode-Anfrage, ungültigen früheren Principal und Startvalidierung. HTTP-Headerprüfung wies nicht-ASCII bereits ab; kein externer Auth-Bypass behauptet. ASCII-Tokens müssen weiterhin mindestens 32 Zeichen lang und eindeutig sein. |
| PERF-1 | P2 | `src/kirabridge/bridge_core/bridge.py:442`, `platform_adapters/macos/provider.py:104` | Jede Routenauswahl erstellte einen vollständigen macOS-Metadatensnapshot, obwohl nur das Hostbetriebssystem benötigt wurde. Eine schmale Property liest die vorhandenen Hostfakten. | Routingtests für portable/tmux/native Pfade und frische Capability-Verweigerung. `require`/Ausführungsprüfungen bleiben frisch; Berechtigungen werden nicht aus alten Snapshots abgeleitet. |

Neue Regressionstests:

- `tests/test_mcp_connection_races.py`
- `tests/test_terminal_event_framing.py`
- `tests/test_session_open_ambiguity.py`
- `tests/test_macos_metadata_boundaries.py`
- `tests/test_routing_and_auth_safety.py`

## Offener P1-Befund: konkurrierendes `file.move`

**Gesichert, nicht repariert:** `src/kirabridge/filesystem_manager/__init__.py:156`.
Die Folge `stat → link → fsync(Ziel) → unlink(Quelle)` ist keine atomare
Verschiebung. Ersetzt ein anderer Prozess die Quelle nach dem Link, löscht unlink
die neue Datei. In einem privaten Tempverzeichnis deterministisch reproduziert:
Ziel enthält die ursprünglichen Bytes; die konkurrierend neu angelegte Quelldatei
fehlt nach erfolgreicher Rückgabe. Kein produktiver Datenverlust wurde ausgelöst.

Ein kleiner Versuch mit descriptorrelativem `renameatx_np(RENAME_EXCL)` bzw.
`renameat2(RENAME_NOREPLACE)` behob diesen Ablauf, bestand Basis-/ABI-Tests, wurde
aber **verworfen**: Tauscht ein anderer Prozess die Quelle zwischen Typprüfung und
Rename gegen ein Verzeichnis, verschiebt der Versuch den ganzen Ordner. Die bisherige
Link-Operation verweigert diesen Fall. Der unabhängige Review reproduzierte diese
Regression. Weder Helper noch seine vermeintliche Reparatur sind im aktiven Code.

Nächster kleiner, prüfbarer Schritt ist ein gesonderter Operationsvertrag für
Quellidentität und Konfliktbehandlung, anschließend eine abgeschirmte Transaktions-
oder Staging-Lösung mit Wiederanlauf-/Recovery-Nachweis. Eine weitere `stat`-Prüfung
vor unlink löst die Race Condition nicht atomar. Kein Copy/Delete-Fallback und kein
Lock nur zwischen KiraBridge-Aufrufern als vermeintlicher Schutz gegen externe Writer.

Erforderliche Tests: reguläre Verschiebung, vorhandenes Ziel, Austausch durch Datei,
Verzeichnis und Symlink an jeder Grenze, Absturz zwischen Schritten, volles Medium,
Dateisystemgrenze, Wiederanlauf und Konflikt ohne Datenverlust. Wegen dieses offenen
Befunds wird hier keine vollständige Fehlerfreiheit oder neue Produktionsfreigabe erklärt.

## Weitere belegte Vereinfachungen und Prüfhypothesen

Diese Punkte sind **nicht** Bestandteil des implementierten Diffs.

| Priorität / Sicherheit | Fundstelle | Beobachtung, nächster Schritt und Änderungsrisiko |
| --- | --- | --- |
| P2, statisch gesichert | `mcp_gateway/proxy.py:30,224` | Health-Aufruf listet Tools und der Monitor listet anschließend erneut, einmal pro Sekunde/Proxy. Zweites Listing mit Aufrufzähler-/Notification-/Revisionstests entfernen. Kein gemessener Latenzgewinn; Änderungen zwischen beiden Listings würden erst im nächsten Poll sichtbar. |
| P2, Race-Hypothese | `session_manager.py:609`, `platform_adapters/terminal_app.py:888` | Nichtdirekter nativer Submit prüft nach Auswahl Fenster/TTY/busy, aber nicht erneut PID/Startzeit; dazwischen liegt ein Await. Kein falsches Live-Ziel reproduziert. Erst Barrier-Test mit Prozesswechsel, dann Identität an Mutation binden. Unterstützte Automationssemantik nicht ungeprüft ersetzen. |
| P2, möglicher Hang | `integrations/desktop/main.swift:63` | Bootstrap-stderr wird nicht entleert, stdout/wait sind unbeschränkt. Tatsächlicher Start-Hang nicht reproduziert. Privaten Prozess mit viel stderr/langem stdout aufsetzen, begrenzt parallel drainen und terminieren; keine echten Nutzerprozesse beenden. |
| P3, statisch gesichert | `team_manager/dispatcher.py:124,184,293`, `message_manager/direct.py:49,68` | `_defer` und `_submitted` wachsen mit verarbeiteten IDs bis Neustart. Terminale Einträge begrenzen, dauerhafte Idempotenz aber beibehalten. Tests für viele Jobs, Backoff, Doppel-Submit und Restart vor Änderung. Kein produktiver Speicherengpass gemessen. |
| P3, statisch gesichert | `platform_adapters/terminal_app.py:233,271,314` | TTY-Duplikate und Prozesse werden wiederholt vollständig gescannt. Counter/Prozessindex vorberechnen, Kataloggleichheit bei doppelten/beendeten/fremden/Legacy-Sitzungen prüfen und erst dann große Kataloge messen. Native IO kann normale Laufzeit dominieren. |
| P3, statisch gesichert | `platform_adapters/terminal_app.py:246` | `ps.returncode` wird nicht ausgewertet, fehlerhafte Zeilen werden gefiltert. Spätere Identitätsprüfungen begrenzen das Risiko. Nonzero-/Teiloutput und reale macOS-Formatvarianten testen, dann typisierten Beobachtungsfehler liefern; kein unsicherer Schreibzugriff nachgewiesen. |
| P3, Duplikat / Sicherheitsgrenze | `literal_session_input.py:123`, `platform_adapters/terminal_app.py:454` | Codex-Wrappingregeln existieren in Python und generiertem JavaScript. Gemeinsame Spezifikation bzw. direkte Paritätstests ausbauen. Frisches Echo und vollständige Widgetprüfung behalten; Footer-/Whitespaceprüfung nicht lockern. |
| P3, Performance-Hypothese | `integrations/desktop/SystemControl.swift:104,200`, `SystemBridge.swift:39` | Wiederholte AX-Attribute und byteweises Lesen von stdin/Pipe sind mögliche Kosten. Erst AX-/Framing-Benchmarks, dann lokale Wiederverwendung bzw. begrenzt gepuffertes Lesen; keine Autorisierungsdaten über Requests cachen. |
| P3, Sicherheitsabgrenzung offen | `integrations/desktop/main.swift:120` | Navigation erlaubt file-URLs und beliebige localhost-Ports; Popupregel ist enger. Kein Exploit nachgewiesen. Pure URL-Policy-Tests und Produktvertrag vor engerem Originfilter; erlaubte lokale Ansichten nicht versehentlich aussperren. |
| P3, Semantikabwägung | `integrations/desktop/SystemControl.swift:37,374` | active/hidden gehen in Katalogrevision ein; Fokus kann Pagination invalidieren. Erst gewünschte Snapshotsemantik festlegen und Fokuswechseltest, danach strukturelle und volatile Daten trennen. |
| P3, Deadline-Hypothese | `mcp_gateway/client.py:392` | `call_timeout` beginnt nach Eintritt in den globalen 32er-Semaphor. Sättigungstest und Gesamtdeadline-Vertrag fehlen. Vor-Sende-Timeout und unbekannter Remoteausgang müssen getrennt bleiben; keine Retries. |
| P3, IO-Hypothese | `process_output_store.py:173,203,210` | SUM(bytes), Datei-fsync und SQLite-Update pro Chunk können teuer sein. Repräsentative Streams messen, ggf. O(1)-Zähler in derselben Transaktion; Crash-/ENOSPC-/Partial-write-Vertrag vor Fsync-Batching. |
| P3, Budgetabwägung | `mcp_gateway/client.py:236` | Seiten-/Toolanzahl begrenzt nicht Gesamtbytes einzelner Schemas. Konfigurierte Peers sind die Vertrauensgrenze. Übergroße Schemas/Transportpuffer testen, danach Gesamtbytebudget; kein Auth-Bypass nachgewiesen. |

Der AST-Vergleich fand keine exakt gleichen Funktionskörper ab acht Zeilen.
Das widerlegt keine semantischen Duplikate. Große Zustandsmodule wurden nicht
pauschal umgebaut; deren Aufteilung braucht eigene Verträge und aussagekräftige
Tests. Bestehende schmale Schnittstellen/PathScope/MCP-Owner wurden wiederverwendet.

## Tests und Messungen

Gezielte Tests bestanden: MCP 58, Terminal/Visible-Regression 875, macOS 97 sowie
Routing/Auth 29. Diese Auswahlen **überlappen** und werden nicht addiert. Die
unabhängigen Reviewer prüften die Änderungen gegenseitig; der zusätzliche alte-
EOF-Repro wechselte ebenfalls von rot auf grün. Die neuen Grenztests zeigten vor
der jeweiligen Reparatur reale Fehler, nicht bloß die neue Implementierung.

Gesamtsuite: **2.887 bestanden, einer übersprungen, 430,34 s**, mit strikter
Behandlung von `PytestUnraisableExceptionWarning`. Der letzte Vor-Dispatch-Guard
MCP-4 und drei zusätzliche Tests wurden nach Beginn dieses Laufs ergänzt; für
diesen abschließenden Stand bestanden danach **58 gezielte MCP-/Diagnostik-/Health-/
Lifecycle-Tests**. Der Gesamtlauf wird deshalb nicht als vollständiger erneuter
Test dieses letzten Diffs ausgegeben. Keine redundante lokale Gesamtsuite.
Ruff, Formatprüfung (489 Python-Dateien) und `git diff --check` bestanden.
Maschinenlesbare Zusammenfassung: [Test-/Reviewevidenz](evidence/reliability-review-20261101.json).
Externe Testquellen entsprechen CI: ThreadDesk `770bbc9f0c0a02699cc93cad47d2e2c3782f7080`
und TollGate `53fc57cc2e082d022e65e5929cb2a1e186fba852`, ohne fremde Worktrees zu ändern.

Isolierte Mikrobenchmarks, je fünf Stichproben, Median:

- Routenauswahl für 100 `session.catalog`-Aufrufe: 223,499 ms → 0,032 ms.
  Gemessen wird nur die Entscheidung inklusive vorheriger Metadaten-IO.
- Parsen von 21.846 kurzen Ereignissen in 64 KiB: 55,021 ms → 4,308 ms.
  Gemessen werden Trennung/Dekodierung im Speicher, ohne IO oder Callbacks.

Das sind keine End-to-End-Beschleunigungswerte für GUI, Terminal oder fremde MCP-Server.

## Betriebs- und Releasegrenze

Produktive Basis bei Beginn: RC22/`f97ab1c`, Core-PID 4837, Runtime-Start
`2026-11-01T12:31:37.605977Z`, Instanz `1018a5a4e4b44df783963c76fe6cfe87`.
Der SHA256 über 144 installierte Python-Quelldateien ist
`03bae2fd8715d4a7581e007096bf03633f7d978d6c590aec044a026512ab3986`.
Der letzte Kontrollpunkt vergleicht PID/Start/Quellidentität und Konfigurationshash.

Die lesende MCP-Kontrolle bestätigte auch ein bereits ausgeschöpftes Diagnostikbudget:
20.000 von 20.000 Einträgen, `recording=budget_exhausted`. Das ist der konfigurierte
Begrenzungspfad (`src/kirabridge/diagnostics.py:69`), kein hier nachgewiesener
Dispatcher-Ausfall. Neue Diagnosen können fehlen. Historie und Grenzen wurden nicht
gelöscht oder ungefragt geändert; Export-/Aufbewahrungskonzept bleibt Betriebsarbeit.

Private Baseline, Logs, Reviewerberichte, Reproduktionen und verworfener Versuch:
`~/.local/share/kirabridge/backups/reliability-review-20261101T134010Z/`.
Sensible Sicherungsdaten werden außerhalb des Repositorys aufbewahrt.

Die frühere tatsächliche RC24/Codex-Abnahme scheiterte an der strikten Bestätigung
einer umgebrochenen Eingabe mit zusätzlicher Cursorzeile. Dieser Review repariert
jenen Rendererfall nicht und wiederholt den ungewissen Auftrag nicht. Deshalb wird
die laufende RC22 nicht durch diesen Kandidaten ersetzt. Ein lokal gebautes und
isoliert geprüftes Paket wäre noch keine native Prompt-/Return-/Handoff-Abnahme
oder Freigabe für Apple Silicon und andere macOS-Versionen.
