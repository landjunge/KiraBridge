# KB-D01: lokale Auftragskonsole / local task console

## Deutsch

Geprüfter Quellstand: `d788ec2b405f3d5551daabc9c10ab6513296645e`, auf Basis
`8226763f7a48b1c00ba905960210d2419a41ded0`. Eigener Branch
`feat/seven-tools-console-20261018`; keine Laufzeitumschaltung, kein Build oder
Release. Der Coordinator integriert den aktuellen Hauptzweig separat.

Die vorhandene lokale Freigabekonsole erhält einen kompakten DE/EN-Aufbau mit
Sprachwahl, OS-abhängigem Hell/Dunkel-Modus, 40-px-Bedienelementen, sichtbarem
Tastaturfokus und reduzierter Bewegung. Der unveränderte gemeinsame Designkern
ist Git-Blob `673f4e265c8c46618ba86d9e98f8da09fd0bf107`, SHA256
`98371bd9edc96fb940a0e0de34933740fed1062b510aa516498fcb53e112591e`.
Nur Produktadapter liegen in `style.css`. Die Serveränderung aus `3972715`
fügt ausschließlich die feste Route `/networkpunkt.css` hinzu.

Automatische und manuelle Freigaben werden gleichzeitig je Zugang dargestellt.
Eine verbundene Konsole bestätigt keine vollständige Arbeitsbereitschaft.
Empfang, Ausführung, Agentendurchgangsende und Gesamtauftragsabnahme werden
sprachlich getrennt. Unbekannte Operationsnamen, Argumentfelder und strukturierte
Ergebnisse erscheinen als Text; sie erhalten keine besondere Ausführungslogik.
Technische Kennungen und Belege sind aufklappbar. Größere Werte bleiben per
Tastatur scrollbar. DE/EN wird nur als kosmetische Browserpräferenz gespeichert.

Die vorhandenen Zugriffsschranken bleiben bestehen: Loopback/Host, exakter
Origin, signierte lokale Session, einmaliges Login-Ticket, kein CORS, keine
Inline-Skripte oder HTML-Interpretation, bestehender Request-Hash und atomarer
Zustandsvergleich. Master-Schlüssel werden nicht im Browser hinterlegt. Kein
neuer Zwischenablagezugriff, keine Nutzerfreigabe oder Projektberechtigung.

Nach einer unklaren POST-Antwort bleibt der Ausgang ausdrücklich unbekannt.
Es erfolgt kein automatischer POST-Neuversand. Der bestehende 5-Sekunden-Poll
liest nur Zustände. Explizites Aktualisieren liest die Details neu; damit werden
veraltete oder nach einem Fehler deaktivierte Entscheidungselemente ersetzt.
Ein zwischen Detailabruf und Darstellung veränderter Zustand erzeugt keine
veralteten Freigabeknöpfe.

### Gezielte Nachweise

- `tests/test_approval_console.py` plus `tests/test_console_design.py`: **9 bestanden**.
  Bestehende Auth-/Origin-/Review-Hash-Gegenfälle sowie feste Designroute,
  exakter Kernhash, CSP, unauthentifizierter API-Zugriff und Pfadtraversal.
- Ruff für die betroffenen Python-Dateien, `node --check` für `app.js` und
  `git diff --check`: bestanden.
- Echte lokale Chrome-Version **155.0.8059.85**, isolierter temporärer Bridge-Store,
  eigener kurzlebiger Loopback-Port, kein Dispatcher und keine Agentenstarts.
  Zehn synthetische Zustandsdatensätze; diese sind kein echter Agentenabschluss.
- Authentifizierte DE/EN-Ansicht in Hell/Dunkel, 1180×900 und 440×760,
  keine horizontale Überbreite, 40-px-Controls, 24-px-Titel, Fokus und Reduced Motion.
- Echte synthetische Approve-/Deny-API-Aufrufe mit Request-Hash, konkurrierender
  Zustandswechsel und tatsächliche Annahme vor simulierter POST-Antwortunterbrechung:
  **genau ein POST**, Zustand danach lesend als queued bestätigt, keine Dateiwirkung.
- HTML-förmiger Auftragsinhalt bleibt Text. Zusätzlicher reiner Anzeigevertrag
  für unbekannte zukünftige Operation/Felder wurde per Browser-Antwortfixture
  geprüft; dieser Test behauptet keine serverseitige Unterstützung dieser Operation.
- Keine Browser-Skriptfehler. Vier Screenshots und Original-Prüfmetadaten unter
  [console-design-20261018](console-design-20261018/); Hashes in `manifest.json`.
  Originaler lokaler Lauf: `dist/console-ui-checks/20261018T181912Z-ab42a776`.

Die Browserprobe nutzt zwei **bereits vorhandene** Python-Umgebungen getrennt:
KiraBridge 3.11 für den isolierten Fixture-Server, ThreadDesk 3.12 mit bestehendem
Playwright für Chrome. Ein anfänglicher gemeinsamer Import scheiterte an der
unterschiedlichen Greenlet-ABI; es wurden keine Pakete installiert. Zwei weitere
anfängliche Harness-Fehler (Selektor und Fokusprüfung ohne Tastaturmodalität)
wurden im Prüfskript korrigiert. Historische fehlgeschlagene Läufe sind erhalten.

```sh
PYTHONPATH=src /Users/landjunge/KiraBridge/.venv/bin/python -m pytest -q tests/test_approval_console.py tests/test_console_design.py
KB_CONSOLE_TEST_PYTHON=/Users/landjunge/KiraBridge/.venv/bin/python /Users/landjunge/threaddesk/.venv/bin/python tests/console_browser_probe.py
```

Der Browseraufruf verlangt eine vorhandene kompatible Playwright-/Chrome-Umgebung;
sonst meldet er einen Einrichtungsfehler. Er installiert nichts, öffnet keine
Nutzerkonfiguration und beendet ausschließlich seinen eigenen Fixture-Prozess.

### Grenzen und Integration

Kein echter ChatGPT-Konsole-End-to-End-Test, keine Behauptung eines erfolgreich
abgenommenen Gesamtauftrags und keine Aussage über sämtliche Runtime-Fähigkeiten.
Die private Nutzerinstallation, Queue, Zugangsdaten und fremde Sitzungen wurden
nicht verändert. Neue M2-Operationen benötigen für die generische Textanzeige
keine Console-API-Erweiterung. Die Console startet auch dadurch keine neue Queue.

Integration: beide Codecommits `3972715` und `d788ec2` übernehmen; zentralen
README-/Runtime-/Release-Abgleich übernimmt der Coordinator. Rückweg: nur diese
isolierten Console-Änderungen rückgängig machen; keine Datenmigration erforderlich.

## English

This source-only change makes the existing local approval console compact and
bilingual. It reuses the byte-identical NetzwerkPunkt design core, follows the
OS light/dark preference and preserves keyboard focus, 40-pixel controls and
reduced motion. Automatic and manual approval are shown per principal.
Receipt, execution, agent-turn completion and acceptance of the overall assignment
remain separate. Unknown operation names and fields render as inert text.

The sole server addition is a fixed local stylesheet route. Existing loopback,
Host/Origin, signed session, one-time login ticket, CSP, review-hash and atomic
state checks stay in place. No runtime, grants, clipboard, release, config or
real user tasks were changed. A lost decision response never triggers an
automatic write retry; refresh reads the existing state and reloads review details.

Nine targeted console/security tests and a real isolated Chrome probe passed.
The probe covers DE/EN, dark/light, small viewport, keyboard, stale decisions,
one accepted decision with a dropped response and exactly one POST. Recorded
states are synthetic; no dispatcher or agent runs. Screenshots and asset hashes
are retained next to this report. This is not live runtime or ChatGPT acceptance.
See the commands above; existing compatible environments are required and no
packages are installed. Integration and any future deployment belong to the
coordinator. Reverting these console commits needs no data migration.
