# Automatische Abnahme: echter Codex, simuliertes Grok

**Der begrenzte automatische Demoablauf und die Browserabnahme sind bestanden.**
Die [fertige Webseite](automatic-20261019-02/site/index.html) ist lokal direkt zu öffnen.
Die Themenwahl wird gespeichert; bei gesperrtem Speicher funktioniert der Schalter weiter.

## Tatsächlich ausgeführter Ablauf

Der neue lokale Runner `kirabridge.automatic_review_demo` hat ohne manuelle
Zwischenschritte Folgendes ausgeführt:

1. Natürlichsprachigen Webseitenauftrag als echte Bridge-Nachricht gesendet und empfangen.
2. Über authentifiziertes HTTP-MCP einen echten `agent.execute`-Auftrag eingereicht.
   Der bestehende Codex-Adapter startete Codex CLI im eigenen Demo-Arbeitsverzeichnis
   mit `workspace-write`, aktiven Projektregeln, ohne MCP und ohne weitere Agenten.
3. Die tatsächlich geschriebene Erstfassung archiviert und den Prüfauftrag mit
   zugehöriger Task-ID und Datei-Hash an `grok-sim` gesendet.
4. Der isolierte **Grok-Simulator** empfing und quittierte diesen Auftrag. Seine
   deterministische, ausdrücklich als Simulation gekennzeichnete Antwort forderte
   `aria-pressed`, gespeicherte Themenwahl und Wiederherstellung nach Neuladen.
   Diese Antwort ging über denselben echten Bridge-MCP-Nachrichtenweg an Codex.
5. Einen zweiten echten Codex-Auftrag mit genau dieser empfangenen Antwort gestartet,
   seriell nach dem ersten, über `parent_id` zugeordnet. Codex änderte die Seite tatsächlich.
6. Die Endfassung in einem frischen echten Chromium-Profil geprüft, anschließend
   eine Ergebnisnachricht mit Auftrags-IDs, Prüfantwort-ID und Datei-Hash zurückgegeben
   und vom Nutzerpostfach quittieren lassen.

Keine echte Grok-Konfiguration, Grok-Zugangsdaten oder Grok-Provideraufrufe waren
beteiligt. Es gibt keinen fingierten Grok-Modellbeleg. Die Namen `user`, `codex`
und `grok-sim` sind getrennte Principals des eigenen Demo-Dispatchers. Der natürliche
Auftrag kam beim automatischen Lauf vom lokalen MCP-Testclient, nicht aus einer
separaten ChatGPT-UI-Unterhaltung. `dispatch=false` betrifft die explizite
Nachrichtenorchestrierung: Die beiden echten Codex-Ausführungen erfolgten über
`task_request`/`agent.execute`, nicht über den generischen MessageReceiver.

## Nachweise

Der erfolgreiche Lauf liegt unter [automatic-20261019-02](automatic-20261019-02/evidence.json):

- Zwei echte Codex-Abschlüsse mit `turn_completed=true`, Exitcode 0 und getrennten
  Session-IDs: `01a1516a-1022-72c3-8137-45c3c9c72216` und
  `01a1516a-6dba-7f41-af7d-0e928d68a685`.
- Vier echte Nachrichten mit Antwortreferenzen, Empfangsbelegen und Quittierungen;
  zugehörige Task-/Nachrichtenereignisse im Evidence-Export.
- [Erstfassung](automatic-20261019-02/initial.html) und [Endfassung](automatic-20261019-02/site/index.html)
  haben unterschiedliche SHA256-Hashes. Finaler Hash:
  `4171290a2ed92dd61c31fe1b8ea9b65846d19fbc064c5e1b07036f5e1ae77675`.
- [Browserbericht](automatic-20261019-02/browser/browser-checks.json): Chromium
  `151.0.7922.34`; Maus, Enter, Leertaste, tatsächlich wechselnde CSS-Farben,
  `aria-pressed`, Wiederladen beider Themen, gesperrtes localStorage,
  Mobilbreite 390px ohne horizontalen Überlauf, keine JavaScript-Ausnahme.
- Screenshots [Desktop hell](automatic-20261019-02/browser/desktop-light.png),
  [Desktop dunkel](automatic-20261019-02/browser/desktop-dark.png),
  [Mobil dunkel](automatic-20261019-02/browser/mobile-dark.png). Desktop hell und
  Mobil dunkel wurden zusätzlich visuell betrachtet.
- Gültige Demo-Auditkette mit 29 Einträgen. Lokale SQLite-Laufzeit ist ausgeschlossen
  vom Git-Tracking; exportierte Belege bleiben erhalten.
- [App-Rückgabe](automatic-20261019-02/connector-readback.json): Über das verbundene
  KiraBridge-App-Werkzeug dieser Codex-Unterhaltung wurde unter Principal `chatgpt`
  ein echter `file.read`-Auftrag abgeschlossen, einmaliger Versuch, mit Empfangsbeleg.
  Der zurückgegebene Seiteninhalt hat exakt denselben Hash wie die Browser-Endfassung.

Die Evidence-Dateien sind lesbare lokale Abnahmeprotokolle, keine signierten
Attestierungen. Tests prüfen zusätzlich die korrekte Verbindung von Task-IDs,
Nachrichten, Prüfantwort, serieller Ausführung, Artefakt-Hashes und Browserbericht.

## Ausführen und stoppen

Voraussetzungen: Projektabhängigkeiten, angemeldeter Codex CLI, Node und Playwright
mit Chromium. Bereits vorhandene lokale Playwright-/Browserinstallationen können
über `KIRABRIDGE_PLAYWRIGHT_MODULE` und `KIRABRIDGE_CHROMIUM` ausgewählt werden.
Es wurden hierfür keine globalen Installationen oder Einstellungen verändert.

```sh
.venv/bin/python -m kirabridge.automatic_review_demo /private/tmp/kirabridge-demo-NEU \
  --codex "$(command -v codex)" --timeout 180
```

Der Zielordner darf noch nicht existieren. Jeder Lauf bekommt einen eigenen Zustand,
einen zufälligen Loopback-Port und flüchtige eindeutige Bearer-Tokens. Es wird keine
installierte Betreiberpolicy geladen und kein vorhandener Dienst neu gestartet.
Höchstens zwei serielle Codex-Aufträge, jeweils mit Zeitlimit; keine automatische
Modellwiederholung, keine fremde Sitzungsübernahme, kein Resume und keine Kaskade.
Die `--model`-Option kann ein ausdrücklich gewähltes Codex-Modell setzen.

Zum Stoppen eine Datei `STOP` im Demoordner anlegen. Vor jeder weiteren Einreichung
und beim Warten auf Codex wird sie geprüft. Ein wartender Auftrag wird storniert;
ein laufender Auftrag wird ausschließlich über seine eigene Bridge-Auftrags-ID
beendet. Die Browserprüfung hat zusätzlich höchstens 90 Sekunden Laufzeit; vor der
Ergebnisrückgabe wird der Stopp erneut geprüft. Nur ein vollständig geprüfter Ablauf
erhält `phase=completed`. Fehler, Zeitüberschreitungen und unklare Ergebnisse werden
nicht als Erfolg ausgegeben und nicht blind wiederholt.

## Fehler und Tests

Der erste Versuch `automatic-20261019-01` deckte einen Runnerfehler auf:
`error: null` in einer gültigen Taskquittung wurde irrtümlich als Ablehnung behandelt.
Die Prüfung wurde auf ein tatsächlich gesetztes Fehlerfeld korrigiert.
[Gespeicherte Fehleranalyse](automatic-20261019-01/failure-analysis.json): erster
Task nach Dispatcher-Abschluss `unknown`, `side_effect_possible=false`, kein Start,
kein Modellabschluss und kein Ergebnis. Dieser Auftrag wurde nicht wiederholt;
der korrigierte Lauf 02 nutzte einen neuen isolierten Zustand.

Ein zusätzlicher Timeout-Gegentest deckte danach noch auf, dass ein korrekt
zurückgegebener `unknown`-Auftrag mit gespeichertem Fehler als MCP-Abruffehler
behandelt wurde. Der Runner unterscheidet jetzt einen fehlgeschlagenen Toolaufruf
von einem erfolgreich gelesenen Auftragsfehler. Tests bestätigen gespeicherten
Zustand `unknown`, genau einen Versuch und keinen verbliebenen eigenen Prozess.
Der reale Erfolgsnachweis von Lauf 02 wurde dafür nicht neu ausgeführt oder verändert.

Abschließender Testlauf:

```text
.venv/bin/pytest -q tests/test_automatic_review_demo.py tests/test_review_demo.py tests/test_messages.py tests/test_agents.py
35 passed in 25.64s
```

Ruff und Formatprüfung aller vier neuen Python-Dateien, `node --check` des
Browserprüfers sowie `git diff --check` bestanden. Die zuvor durch die Sandbox
blockierten HTTP-Tests bestehen jetzt ebenfalls.
Die gezielten Tests verwenden weiterhin ausdrücklich simulierte CLI-Prozesse;
der reale Codex-Nachweis ist separat der oben dokumentierte Lauf. Geprüft werden
unter anderem Quittungen, Rechte-/Idempotenzgrenzen, Stopp eines eigenen Prozesses,
Timeout/Fehler ohne Wiederholung und Zurückweisung falscher Belegzuordnungen.

## Verbleibende Grenzen

Ein neuer Auftrag aus einer eigenständigen **ChatGPT-UI-Unterhaltung** bis zum
fertigen Ergebnis ist weiterhin nicht nachgewiesen. Der lokale automatische
MCP-Einstieg und der echte verbundene App-Ergebnisabruf aus dieser Codex-Sitzung
sind getrennt belegt. Der installierte Betreiberbetrieb wurde nicht auf den neuen
Demorunner umgestellt. Der allgemeine MessageReceiver ist durch eigene Tests
geprüft; dieser spezifische Demoablauf verwendet die explizite Orchestrierung.

Echte Grok-Abnahme bleibt absichtlich offen. Es wurden keine Grok-Aufträge,
Dienstneustarts, globalen Rechteänderungen, Releases oder Veröffentlichungen vorgenommen.
Fremde Sitzungen, Worktrees und vorhandene ungesicherte Arbeit blieben unangetastet.
Die [erste manuelle Stufenabnahme](STAGED-ACCEPTANCE.md) ist als historischer
Zwischenstand erhalten; ihre damaligen offenen Codex-/Browserpunkte sind durch
Lauf 02 für den isolierten automatischen Demoablauf geschlossen.
