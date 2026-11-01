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
| TERM-1: volle logische Cursorzeile | Terminal-Agent belegt Cell-Buffer-Mehrdeutigkeit im unveränderten Codex-/Ratatui-Code. Frühe Ablehnung vor Paste für unentscheidbare Geometrien; positive physische Abnahme mit eindeutiger Geometrie folgt. | Implementierung / Abnahme offen |
| MCP-1: doppeltes Katalogpolling | Zweites Listing und redundanter Connection-Lock entfernt; frisches Listing pro Call und Revisionswechsel bleiben. 33 relevante Tests bestanden, unabhängig freigegeben. | Repariert / getestet |
| TERM-2: nichtdirekter Submit / Prozesswechsel | Prozessidentität unmittelbar an native Mutation binden, vorhandene Automationssemantik erhalten; Barrier-Test vor Änderung. | Wartend |
| MAC-1: Bootstrap-Pipes / Deadline | Parallel begrenzt lesen und nur eigenen Prozess terminieren; private Hänger-/Stderr-Fixtures. | Wartend |
| MAC-2: wiederholte AX-Attribute / Ersttimeout | Erstzugriff begrenzen; Summary-Werte lokal einmal erfassen, spätere Zielprüfung frisch halten. | Wartend |
| MAC-3: Navigationsgrenze | Produktseitig erlaubte lokale Origin/Datei festlegen, pure URL-Policy prüfen und begrenzen. | Wartend |
| MAC-4: byteweises stdin-Framing | Begrenzten Puffer mit Fragmentierung/EOF/Übergröße prüfen; Serialisierung erhalten. | Wartend |
| MAC-5: volatile Katalogrevision | Snapshotvertrag und Fokuswechseltest entscheiden; strukturelle und volatile Felder nur nach Nachweis trennen. | Wartend |
| TERM-3: Prozesskatalog-Fehler | Nonzero/Teiloutput/ungültige Zeilen typisiert behandeln, tatsächliche Formatvarianten erhalten. | Wartend |
| TERM-4: wiederholte Katalogscans | TTY-Counter/Prozessindex nur mit identischen Katalogresultaten und repräsentativer Messung. | Wartend |
| TERM-5: Python-/JS-Rendererduplikat | Gemeinsame reine Spezifikation oder direkte Paritätsvektoren; unabhängige Echo-/Widget-Gates erhalten. | Wartend |
| MCP-2: `_defer` / `_submitted` wachsen | Endgültige IDs begrenzen, dauerhafte Idempotenz und Backoff beibehalten; Replay-/Restarttests. | Wartend |
| MCP-3: Deadline nach globalem Gate | Isolierten Sättigungsfall messen, Vor-Dispatch-Timeout und unbekannten Remoteausgang getrennt behandeln. | Wartend |
| MCP-4: Katalog-Bytebudget | Reale Größen und übergroße Schemas prüfen; bestehende Anzahl-/Cursorgrenzen erhalten. | Wartend |
| IO-1: Output-SUM/fsync pro Chunk | Repräsentativ messen; nur belegten Engpass optimieren, Crash-/Budgetvertrag erhalten. | Wartend |
| OPS-1: ausgeschöpftes Diagnostikbudget | Bestehende Begrenzungs-/Aufbewahrungspolitik prüfen; keine Audit-Historie löschen und keine unbegrenzte Speicherung einführen. | Wartend |
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
