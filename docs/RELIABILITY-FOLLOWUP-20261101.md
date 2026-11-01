# Fortsetzung des Zuverlässigkeitsreviews · 1. November 2026

Nutzerauftrag: die Befunde im Team Punkt für Punkt bis zum Abschluss bearbeiten.
Basis ist Commit `257e72221f751a06767c485ebad253203bdca121`; [Review und Evidenz](RELIABILITY-REVIEW-20261101.md).
Ein Prüfpunkt endet mit repariert/getestet oder einer belegten technischen Entscheidung.
Eine unbestätigte Hypothese wird nicht als reparierter Fehler gezählt.

Arbeitskopie: `fix/reliability-review-20261101`. Neue private Sicherung:
`~/.local/share/kirabridge/backups/reliability-continuation-20261101T144926Z/`.
Quellenarchiv und fünf geschützte Installations-/Konfigurationsdateien wurden
rückgelesen. Produktive Basis bei Wiederaufnahme: RC22, PID 4837, Instanz
`1018a5a4e4b44df783963c76fe6cfe87`, Dispatcher aktiv.

## Geordnete Arbeitspunkte

| Punkt | Zuständigkeit / Ergebnis | Status |
| --- | --- | --- |
| FS-1: `file.move` verliert konkurrierende Quelle | Sentinel-Capture und Hardlink-Pin implementiert; unabhängige Typ-/Identitäts-/Fsync-/Recoveryprüfung freigegeben. Kein öffentlicher Source-Unlink, kein Directory-Capture, kein überschreibender Rollback. 89 relevante Tests bestanden. | Code repariert / getestet |
| TERM-1: volle logische Cursorzeile | Im belegten Wortprofil wird eine unentscheidbare volle logische Zeile vor Paste verweigert. 24 neue Fälle, 335 relevante Tests, 12.670 Originalrenderer-Vektoren ohne Abweichung im begrenzten Profil; kein positiver Verifier gelockert. | Code repariert / physische Abnahme nachgeordnet |
| MCP-1: doppeltes Katalogpolling | Zweites Listing und redundanter Connection-Lock entfernt; frisches Listing pro Call und Revisionswechsel bleiben. 33 relevante Tests bestanden, unabhängig freigegeben. | Repariert / getestet |
| TERM-2: nichtdirekter Submit / Prozesswechsel | PID/UID/TTY/Start/PPID/Image vor dem wartenden Hook erfassen und im nativen JXA direkt vor doScript prüfen. Echte JS-Barriere verweigerte erst nach Fix den ausgetauschten Prozess. | Repariert / getestet |
| MAC-1: Bootstrap-Pipes / Deadline | Beide eigenen Pipes begrenzt drainieren, 60-s-Starterfrist plus höchstens 0,5 s Cleanup; kein fremder Prozessgruppen-Kill. Sieben echte Foundation-Prozessfälle und vier Builderfälle bestanden. | Repariert / getestet |
| MAC-2: wiederholte AX-Attribute / Ersttimeout | Timeout vor erstem Attribut; pro Summary einmal lesen, Secure-Value bleibt ungelesen. Neun Swift-Mock-/Revisionsfälle bestanden. | Repariert / getestet |
| MAC-3: Navigationsgrenze | Nur Console-Origin 127.0.0.1:8766 und Login-Datei aus eigenem Starterbeleg; Custom-Config-Pfade, enger Dateigrant und begrenzte frühe Open-Events. 47 reine Policy-/Sequenzfälle bestanden. | Repariert / getestet |
| MAC-4: byteweises stdin-Framing | POSIX-Reads bis 8 KiB; kurze Frames liefern vor EOF, Batchrest/Fragmentierung und 65.535-Bytegrenze bleiben. Ein Foundation-Pufferversuch wurde nach rotem echten Pipe-Test verworfen. Elf Fälle bestanden. | Repariert / getestet |
| MAC-5: volatile Katalogrevision | Vollsnapshot einschließlich active/hidden bleibt absichtlich revisionsgebunden; synthetische Fokus-/Hiddenwechsel verweigern alte Fortsetzungen. Kein belegter Engpass rechtfertigt eine Vertragslockerung. | Geprüfte Entscheidung / getestet |
| TERM-3: Prozesskatalog-Fehler | Nonzero, leere/fehlerhafte/duplizierte/ungültig UTF-8-kodierte Inventare liefern session_observation_invalid; comm-Pfade mit Leerzeichen bleiben vollständig. Reale Formatprobe plus rote/grüne Parserfälle. | Repariert / getestet |
| TERM-4: wiederholte Katalogscans | TTY-Counter und ein Prozessindex statt mehrfacher Scans. Drei vollständige Kataloghashes identisch; CPU-Median 100 Tabs/3.030 Prozesse: 58,07 → 26,40 ms. | Optimiert / geprüft |
| TERM-5: Python-/JS-Rendererduplikat | 680 tatsächliche JS-/Python-Paritätsvektoren schützen die Sprachgrenze. Frisches natives Echo und finale Widgetprüfung bleiben getrennte Gates; kein großer Renderer-Port. | Abgesichert / getestet |
| MCP-2: `_defer` / `_submitted` wachsen | Nur abgelaufene Backoffs und dauerhaft nicht mehr pristine Jobs vergessen; Storagefehler behalten den No-Replay-Tombstone. 112 relevante Message-/Team-/Receiverfälle bestanden. | Repariert / getestet |
| MCP-3: Deadline nach globalem Gate | Eine Gesamtfrist umfasst Refresh, Cataloglock, Gate und Toolantwort. Vor Dispatch lokale NoDispatch-Receipt; danach weiter UNKNOWN/noRetry. Catalog-EOF bereinigt nur den ursprünglichen Owner. | Repariert / getestet |
| MCP-5: Connection-Lock ohne Frist | Der öffentliche Proxy begrenzt auch das Warten auf den Connection-Lock. Vier neue Fälle prüfen Queue, Cancellation und begonnene Initialisierung; 48 relevante Fälle bestanden. Tool-Dispatch=no gilt nur für diesen lokalen Aufruf, nicht für mögliche Controlplane-Effekte. | Repariert / getestet |
| MCP-4: Katalog-Bytebudget | Maximal 8 MiB UTF-8-JSON über vollständige Tools/alle Seiten; NaN/Unicodefehler verweigern, Cache nur nach vollständigem Erfolg publizieren. 512/8-Grenzen bleiben. 76 relevante MCP-Fälle bestanden. | Repariert / getestet |
| IO-1: Output-SUM/fsync pro Chunk | Reale Append/fsync/SQLite-Messung mit synthetischer Historie: Indexversuch 193 statt 126 ms/100 Chunks, verworfen. Quelle bytegleich zur Baseline; keine zusätzliche Zählerschicht oder Durability-Lockerung. | Gemessen / keine Produktänderung |
| OPS-1: ausgeschöpftes Diagnostikbudget | Gewöhnliche Task-, Message- und Auditbelege bleiben nach Diagnostic-Cap nachweislich erhalten; health/Readiness zeigen Degradation. Ein zusätzlicher Integrationstest und vorhandener Boundarytest bestanden. Historie/Cap unverändert. | Vertrag geprüft / abgesichert |
| RELEASE: tatsächliche Funktion / Installation | Gezielte Tests, unabhängiger Review, abschließende Regression/CI, identitätsgeprüftes Paket; native Abnahme und unterstützte sichtbare Installation erst nach erfüllten Gates. | Nachgeordnet |

## Bereits belegte Grenzen und Zwischenstände

Die für FS-1 verworfene direkte No-Replace-Rename-Lösung bleibt verworfen.
Der neue Entwurf ersetzt nur einen eigenen regulären Sentinel. Damit erzwingt
der Kernel die Nondirectory-Grenze; anschließend wird die erfasste Identität
gegen einen privaten Hardlink geprüft. Nutzerdaten werden weder zum Pinnen
geöffnet noch über den Hardlink chmod/chown/truncate unterzogen.

Die exakte interne Recovery-Namenskomponente `.kirabridge-move-<32hex>` ist für
gewöhnliche Datei-APIs reserviert. Ähnlich benannte Nutzerdateien bleiben erlaubt.
Namespace-/Dateibereich-/Securitytests: zunächst 37 bestanden, darunter zuvor zwei
rote Zugriffstests. Der unabhängige Review belegte zusätzlich echte APFS-Aliase
über Großschreibung und das Kelvin-Zeichen K. Casefold reserviert auch diese Namen;
die abschließende 89er-Auswahl deckt Move, Namespace, Dateibereiche, Security und
Taskpersistenz ab. [Dateisystemvertrag](FILE-MOVE-CONTRACT.md) und
[maschinelle Evidenz](evidence/file-move-repair-20261101.json) halten die Grenzen fest.
Ein Recoverybeleg erlaubt keine automatische Wiederholung eines ungewissen Vorgangs.

Beim Cursorfall liefern angefragter Draft und Draft plus Leerzeichen im offiziell
gepinnten Renderer denselben Cell-Buffer. Cursorposition allein lässt sich durch
zusätzliches Left angleichen. Quartz-Keycounter zählen laut öffentlichem Header
Autorepeat nicht und sind kein eigenständiger Inhaltsbeweis. Deshalb wird keine
Whitespace-Lockerung oder unbewiesene Cursor-Freigabe eingebaut.

Die neue Vorabklassifikation gilt nur für das dokumentierte Latin1-/Identifier-
Wortprofil mit einzelnen normalen Spaces/Newlines und begrenzter Satzendepunktuation.
Hyphenation, andere Unicode-Linebreak-Formen und lange Wörter wurden nicht neu
freigegeben. Breitere Versuche wichen vom Originalrenderer ab und sind verworfen.
Außerhalb des Profils bleibt die vorherige strikte Nachverifikation zuständig;
ein unsicherer Zustand darf weiterhin UNKNOWN ohne automatische Wiederholung sein.
Direkte Message-Zustellung kennt den neuen, nachweislich vor Paste liegenden Fehlercode.

## Abschließende Codeprüfung vor Paket/Live-Abnahme

Produktbaum beim lokalen Gesamtlauf: 145 Pythondateien, SHA256
`dcbc2f9ab6c6395fb700ee35de3d62a9e9510941a45fccca61c3a78bf20959df`.
Die unabhängigen Reviews von Filesystem, Terminal, MCP und den drei geänderten
Swift-Quelldateien sind freigegeben. Der koordinierte native Nachlauf bestand
**74 Fälle in 25,17 s**; vollständiger Desktop-Typecheck exit 0 mit einer bestehenden
WebKit-/Sendable-SDKwarnung. Repo-Ruff und Formatprüfung (510 Pythondateien) bestanden.

Der eine lokale Gesamtlauf berichtete **3.075 bestanden, 24 fehlgeschlagen, einer
übersprungen (442,24 s)**. Alle 24 Fehler waren dieselbe unvollständige Testgrenze:
zwei ältere ThreadDesk-Fixtures erzeugten SimpleNamespace statt der vom SDK
gelieferten serialisierbaren Toolobjekte. Ausschließlich diese Factories wurden
auf `mcp.types.Tool`/`ToolAnnotations` umgestellt. Die betroffenen zwei Module und
direkt relevante Budgetfälle bestanden anschließend **46 Tests**. Jeder einzelne
Produktdateihash blieb gleich; es gibt keinen Produktionsfallback für ungültige
Tooltypen. Der fehlgeschlagene Gesamtlauf bleibt als solcher erhalten. Keine
redundante lokale Wiederholung; die endgültigen plattformübergreifenden CI-Gates
werden auf dem abschließenden Commit geprüft.

Das separate [Codex-Abnahmeharness](../scripts/accept_codex_handoff_intel.py) wurde
unabhängig geprüft. Ohne expliziten Ausführungsmodus druckt es nur den
[Reviewplan](../scripts/accept_codex_handoff_intel.review.json). 34 Offlinefälle
prüfen Ownership, No-Replay, Shell-/Konfigkontext und eigenes Cleanup. Der spätere
physische Lauf fordert Paket-/Interpreter-/Source-/Commit-/CLI-Pins sowie genau ein
frisches eigenes Fenster. Keine vorhandene Sitzung oder ungewisse Eingabe wird
übernommen. Invocation-Overrides und tatsächliche Konfiglistings werden vor dem
Start im nachgewiesenen Shellkontext geprüft; dynamische fremde Änderungen werden
nicht als unmöglich behauptet.

Diese Codeprüfungen ersetzen weder den physischen Ablauf noch die Installation.
Der Betriebs-/Paketnachweis wird getrennt mit dem tatsächlich geprüften Commit,
Prüfsummen und laufender Identität gespeichert. Die Testauswahlen überlappen und
werden nicht addiert. Native Rohframes, Prompts, Config-/Authdaten und Clipboard-
Inhalte bleiben in den privaten Sicherungen, nicht in Releaseassets.

Der letzte Produktdelta nach diesem Gesamtlauf ist ausschließlich der begrenzte
Connection-Schritt in `mcp_gateway/proxy.py`: zwei zuvor rote Lockfälle, vier neue
grüne Fälle und **48 relevante Tests (8,53 s)**. Root hat Diff und Fehler-/Cancellation-
Verträge unabhängig geprüft. Der endgültige 145-Dateien-Produktbaum ist
`9b3c03ccf40e13e2cfcbdeb8f89b359141455026a8620a2c3b8d8dd0a3881f36`.
[Strukturierte Abschlussprüfungen](evidence/reliability-followup-20261101.json)
enthalten die getrennten Teststände und noch ausstehenden Betriebsgates.

## Erster plattformübergreifender Endlauf und gezielte Korrekturen

Commit `f387ac9eeb310165e3e981c432717b93a7573daf`, Verify
[41328932770](https://github.com/landjunge/KiraBridge/actions/runs/41328932770):
Linux Python 3.11/3.13 jeweils **2.999 bestanden, 121 übersprungen**;
ARM-macOS **3.116 bestanden, vier übersprungen**. Intel-macOS meldete
**3.114 bestanden, zwei fehlgeschlagen, vier übersprungen (547,20 s)**.
Damit bleibt dieser Kandidat für Veröffentlichung/Installation gesperrt.

Der Fenster-Harnesstest verbot die Zeichenfolge `999` im gesamten JSON. Sie war
in einer zufälligen Fixture-UUID vorhanden, nicht in protokollierten Fremdfensterdaten.
Eine feste UUID mit derselben Kollision reproduzierte den Fehler deterministisch.
Die Korrektur prüft den tatsächlich gespeicherten `window_probes`-Whitelistblock
exakt und behält No-Poll/No-Focus sowie leere `owned_rows` bei. **50 Modulfälle
bestanden (0,43 s)**; unabhängiger macOS-Agent freigegeben.

Der zweite Fehler hatte eine nicht quittierte synthetische Prozessantwort.
Die damalige CI-Ursache ist mangels Processingdiagnose nicht eindeutig belegt.
Gesichert ist eine unbeabsichtigte Hostabhängigkeit: die drei Fake-Programme
benutzten `/usr/bin/env python3`, während der minimale Prozess-PATH auf diesem
Mac Apples Xcode-Python 3.9.6 statt des Testinterpreters 3.11 auswählt. Ein echter
gegengerichteter Test ohne PATH-Python reproduzierte unknown/AckNone; nach Pinning
auf `sys.executable` bestand er. Die reale positive Prozessrunde prüft nun ebenfalls
einen PATH ohne Python. Timeout 5 s und alle Spawn-/Reap-/No-Replay-/Altauftragsprüfungen
bleiben unverändert; bei einem Fehler zeigen die Assertions den Processingbeleg.
**14 gezielte Fälle bestanden (4,10 s)**, unabhängig von Root gelesen/freigegeben.

Diese Änderungen betreffen ausschließlich zwei Testdateien. Der Produktbaum bleibt
bytegleich bei `9b3c03cc…`. Das bereits gebaute Intelpaket bestand isolierten Smoke
und unabhängigen Manifest-/Wheel-/Git-/Signaturvergleich; ARM-Smoketest war ebenfalls
grün. Das ersetzt keine erfolgreiche End-CI. Ein neuer sauberer Commit wird erneut
mit exakten Commitpins gebaut und geprüft. Kein zusätzliches lokales Gesamtsuite-
Loop und keine produktive Umschaltung aus dem fehlgeschlagenen Kandidaten.
