# Abnahme: Codex mit simulierter Grok-Prüfung

Die fertige [Webseite](run-20261019/index.html) lässt sich direkt lokal öffnen.
Der Schalter ändert Hell/Dunkel, Beschriftung und `aria-pressed`; die Auswahl wird
bei verfügbarem localStorage gespeichert. Kein Build, keine externen Ressourcen.

## Tatsächlich ausgeführt

Diese laufende Codex-Sitzung hat die erste Seite geschrieben, die vorbereitete
Prüfantwort über echtes KiraBridge-MCP empfangen und danach den Seitencode geändert.
Es wurde **kein weiterer Codex-Agent** gestartet. Der Simulator `grok-sim` ist ein
statischer Testadapter in `kirabridge.review_demo`, kein Grok-Modell. Er empfängt
und quittiert den Prüfauftrag und sendet exakt die vorbereitete Änderungsforderung
als Antwort. Die Demo konfiguriert überhaupt keine Provider oder Agentenprogramme.

Vier echte SQLite-Nachrichten wurden über getrennte stdio-MCP-Verbindungen gesendet:
Nutzer → Codex, Codex → grok-sim, grok-sim → Codex, Codex → Nutzer. Jede wurde
zugestellt und mit ihrem Empfangsbeleg quittiert. `dispatch=false` bedeutet hier
bewusste Bearbeitung durch die laufende Sitzung, keine automatische CLI-Ausführung.
`processing=null` ist deshalb korrekt. Die Zuordnung erfolgt über Gesprächs- und
Nachrichten-IDs, Antwortreferenzen und Artefakt-Hashes; es gibt keinen fingierten
`agent.run`-Task oder CLI-Sessionnachweis.

Nachweise in `run-20261019/`:

- `initial.html`: tatsächlich vor Empfang der Prüfung geschriebene Erstfassung.
- `index.html`: tatsächlich nach Empfang überarbeitete Endfassung.
- `evidence.json`: originale Nachrichten, IDs, Empfangsbelege und beide SHA256-Hashes.
- `checks.json`: Verhaltenstests des echten Seitenskripts, mit Hash der geprüften Datei.

## Reproduzieren ohne Providerkosten

Aus dem Repository mit installierten Projektabhängigkeiten; einen neuen, noch nicht
vorhandenen absoluten oder relativen Demoordner verwenden:

```sh
.venv/bin/python -m kirabridge.review_demo start /private/tmp/kirabridge-review-NEU
# Laufende Codex-Sitzung erstellt dort index.html gemäß zugestelltem Auftrag.
.venv/bin/python -m kirabridge.review_demo review /private/tmp/kirabridge-review-NEU
# Laufende Codex-Sitzung setzt die ausgegebene Prüfantwort in index.html um.
node examples/review-demo/check-page.cjs /private/tmp/kirabridge-review-NEU/index.html
.venv/bin/python -m kirabridge.review_demo finish /private/tmp/kirabridge-review-NEU
```

`stop ORDNER` sperrt weitere Bearbeitungsstufen. Eine Prüfung, eine Nacharbeit,
eine Ergebnisrückgabe; falsche Reihenfolge und Wiederholung werden abgewiesen.
Unveränderte Ergebnisse und veraltete Prüfergebnisse werden abgewiesen. Jeder
MCP-Aufruf hat 15 Sekunden Zeitlimit, Verbindungsabbau zusätzlich höchstens fünf.
Keine automatischen Wiederholungen. Bei unterbrochenen Stufen den bestehenden
Nachrichtenbestand lesen; ein fehlendes lokales Zwischenprotokoll beweist keine
Nichtausführung. Bei unklarem Ausgang stoppen, keine blinden Neueinreichungen.
Lokale Policy/SQLite bleiben nur im jeweiligen Demoordner, ohne Betreiber-Secrets.
Die Evidence-Datei ist ein lesbares Abnahmeprotokoll, keine signierte Attestierung.

## Grenzen der Abnahme

Der Node-Test führt das echte JavaScript mit minimalem DOM-/Storage-Testadapter
aus: beide Schaltrichtungen, Status/Beschriftung, Wiederladen beider Themen,
gesperrter Speicher und ungültige Werte. Er prüft zusätzlich die CSS-Anbindung.
Eine echte Browser-Render-/Tastaturabnahme ist noch offen.

Ein neuer, von der Bridge gestarteter Codex-CLI-Durchlauf und der tatsächliche
ChatGPT-Connector-Einstieg wurden in diesem Auftrag nicht ausgeführt. Der
vorhandene automatische Receiver wird separat durch die Nachrichtentests geprüft,
dort mit simulierten CLI-Prozessen. Der unbeaufsichtigte Gesamtablauf ist damit
**noch nicht abgenommen**. Dafür ist ein eigenständig beauftragter externer Lauf
außerhalb dieser bereits laufenden Codex-Sitzung nötig. Echte Grok-Abnahme bleibt
bis zu ausdrücklich freigegebenem Zugang offen; hier entstanden keine Grok-Aufträge.

## Gezieltes Testergebnis dieses Auftrags

Ausgangsstand: Checkout `13f1cb1`, Branch `runtime/project-control-20261018`.
Im Checkout und den geprüften übergeordneten Verzeichnissen wurde keine
`AGENTS.md` gefunden. Zwei schon vorhandene unversionierte Auftrags-/Abnahmedokumente
sowie andere Worktrees blieben unangetastet. Die Änderungen dieses Auftrags sind
auf den neuen Demoadapter, neue Demotests/-dateien und kleine Dokumentations- und
Ignore-Ergänzungen begrenzt; keine andere Agentensitzung wurde übernommen.

`pytest -q tests/test_review_demo.py tests/test_messages.py tests/test_agents.py`:
**28 bestanden, 2 Setup-Fehler**. Alle drei neuen Demotests bestanden. Die beiden
bestehenden HTTP-Tests `test_real_authenticated_mcp_receiver_roundtrip_is_finite`
und `test_persisted_queue_is_resumed_by_new_receiver` scheiterten bereits beim
Socket-Binding auf `127.0.0.1:0` mit `PermissionError: Operation not permitted`
durch die Ausführungs-Sandbox. Keine Rechte wurden deshalb erweitert.

Die neuen Tests prüfen echten stdio-MCP-Verkehr, Antwortreferenzen, Quittungen,
verweigerte doppelte Stufen/Startüberschreibung, unveränderte oder veraltet geprüfte
Ergebnisse, Stopp und die gespeicherten Artefakt-Hashes. Testdateien enthalten
bewusst keine Behauptung einer echten Agentenausführung.

`node examples/review-demo/check-page.cjs examples/review-demo/run-20261019/index.html`
bestand. Ruff-Prüfung/Formatprüfung der neuen Python-Dateien und `git diff --check`
bestanden. [Nachrichtenereignisse](run-20261019/message-events.json) belegen vier
quittierte Nachrichten; Prüfung der tatsächlichen Demo-Auditkette: gültig,
24 Einträge. Die SQLite-Laufzeit bleibt lokal und ist vom Git-Tracking ausgeschlossen.

Keine Dienstneustarts, Änderungen an echter Grok-Konfiguration, Releases oder
Veröffentlichungen wurden durchgeführt. Die sichtbare Erstfassung bleibt als
Nachweis erhalten; persönliche Daten oder fremde Arbeitsdateien wurden nicht für
die Tests verwendet.
