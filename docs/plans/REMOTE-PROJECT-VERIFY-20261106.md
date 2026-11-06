# R2: gemeinsamer Projekt-/Remotevertrag am lokalen TLS-Core

06.11.2026 · `BP-REMOTE-PROJECT-VERIFY-20261106-R2`.
Karte `188ce4729a62/edadd80ba3db`, Claim `f242895500fc`.
Codex01a1a7d1 alleiniger KB-Schreiber auf
`test/remote-project-verify-20261106-r2`, Basis
`279abc4aaf563e562a71e08b9b826c5c585ff7a6` einschließlich Produktfix `96acb71`.
Geändert sind ausschließlich Testharness und Prüfdokumentation.

## Gemeinsamer, unveränderlicher Quellstand

TD-Owner01a1ae37 lieferte den eingefrorenen Mergepin
`a0dd4c39478b031e0e31d335c2a15435dfbc52eb`. Beide tatsächlichen Eltern wurden
unabhängig gelesen: M3 `cd5c994b90acd6453ca1158e23c9887efdd19ec5` und
Remoteadapter `e90e9a6ce29c5c22b187147da35fcff40f51a790`.
Der veröffentlichte Feature-Ref stimmt unabhängig mit diesem Pin überein.

Die Prüfung verwendet ausschließlich einen eigenen schreibgeschützten
`git archive`-Export dieses Pins, 276 Quelldateien. Archiv-SHA256:
`c895d55d836555f7b79a00e16c93eb6c5af92d6d7026ee62d9973b250ba580f4`.
Manifest und Dateien wurden nach den Läufen wieder abgeglichen; Bytecode ist
deaktiviert. Kein fremder TD- oder C1-Worktree wurde beschrieben.

Die bisherige Integrationslücke ist für diesen **Quellkandidaten** geschlossen:
M3-Projektbefehle und der vorhandene optionale Handoff-HTTP-Adapter liegen im
selben geprüften Pin. Daraus folgt keine installierte oder mobile Funktion.
TD-Ergebnisbeleg `188ce4729a62/025716a693e4` berichtet 512 eigene Prüfungen und
78 unabhängige TD-Prüfungen; diese wurden hier nicht erneut ausgeführt.

## Ein neuer M3-Fall im vorhandenen Harness

Die bestehenden lokalen TLS-/TD-/MCP-/Core-Fixtures werden weiterverwendet.
Ein zusätzlicher Fall erzeugt vor dem Start des Testservers ausschließlich
eigene temporäre Tenantdaten über `project.start`, `project.plan.get` und
`project.plan.revise`. Er liest Planrevision2 und registriert deren Thread
ausdrücklich über den bestehenden `SyncStore` für den Transport.

Lokale Graphprojekt-ID, zugeordnete Thread-ID und HTTP-`server_sync.pid` behalten
ihre Rollen: der Transport verwendet die Thread-ID, nicht die Graphprojekt-ID.
Das registriert keinen produktiven Serverbereich und erweitert kein Plan-RPC.

Der Test weist nach:

- Das tatsächliche M3-Revisionsergebnis samt READY-Plantext wird als
  `remote_envelope_invalid` abgewiesen; noch kein Coretask oder Submit.
- Erst ein ausdrücklich ausgegebener Handoff und regulärer synthetischer
  Coregrant erlauben den vorhandenen Zustellweg. Echte lokale TLS-/MCP-Aufrufe
  ergeben genau einen `task_submit`, einen Coretask und einen Fixture-Agentenlauf.
- Der tatsächliche Return wird zurückgelesen: `issued_bound`, Entscheidung
  weiterhin leer, `delivered_unverified`, keine fachliche Projektabnahme.
- Eigener TLSserver und Core samt SQLiteverbindung werden geordnet geschlossen.
  Neue Core-/Datenbankobjekte öffnen dieselbe gespeicherte Datenbank, danach
  verbindet sich ein neuer Relayclient. Auch nach Ablauf des Zustellfensters
  wird derselbe Receipt gelesen, ohne weiteres Submit oder weiteren Fixturelauf.

Der Agent bleibt ein deterministisches lokales Python-Testprogramm. Kein
Codex-/Grok-Modell, bezahlter Provider oder produktiver Agent wird gestartet.
Der Core-/TLS-Neuaufbau findet **im selben Testprozess** statt; OSprozess-,
launchd-/systemd-Dienstrestart, harter Prozessabbruch und TD-Neustart sind damit
nicht nachgewiesen.

Ein zusätzlicher Parameterfall im vorhandenen Negativtest verändert den
kanonisch geformten Requesthash. Die bestehenden Fälle für Reservierungsverlust,
verlorene Antwort, falsche Quellen/Geräte/Grants, direkte Coreumgehung,
UNKNOWN und den unveränderten Visible-Gate bleiben Teil derselben gezielten Datei.
Keine neue Queue, kein Dispatcher und keine Änderung an Produktcode oder Rechten.

## Ergebnisse und Review

Erster Lauf am gemeinsamen Pin: 26 bestanden, 0 Skips, 51,20s; dieser Stand
belegte noch ausschließlich Relayclient-Reconnect. Nach der konkreten
Lifecycle-Ergänzung wurde die betroffene Fixturedatei erneut geprüft:
**26 bestanden, 0 Skips, 52,76s**. Ruff, Format- und Diffprüfung bestanden.
Kein wiederholter allgemeiner Produkt-Suitenlauf.

Zusätzlich wurde der gespeicherte Corebeleg ausschließlich aus dem eigenen
M3-Testverzeichnis mit SQLite `mode=ro` gelesen: ein Task `remote-m3-plan`,
`completed`, Receipt `fd684916-6d3b-4618-9b61-e23712bcbcdc`. Rohbeleg und
Requesthash stehen privat in `persisted-core-receipt.json`; keine Tokenexporte.

Ein getrennter nativer Codex-Lesereviewer prüfte Testdiff, Lifecycle/Cleanup und
acht relevante Dateien des gemeinsamen TD-Snapshots gegen Manifest und Gitpin.
Abschluss: keine Blocker, keine Freigabe-/Idempotenzschwächung erkennbar.
Er führte keine eigenen Tests aus. Finaler überprüfter Testdatei-SHA256:
`6d3698eaf1345cbc448fe99b2236624e5cfd3012da184ac4cf258171e05ef252`.
Die beiden Reviewstände bleiben getrennt: `source-freeze.json` enthält den
ersten KB-Testhash `fc2983f7…`, der Anschlussreview/finale Nachweis den neuen Hash.
Der TD-Pin und sein vollständiges Exportmanifest blieben in beiden Fällen gleich.

Vorhandene Testumgebung, keine Installation zusätzlicher Abhängigkeiten:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE=/PFAD/ZUM/GEPRUEFTEN/M4-SNAPSHOT/src \
/Users/landjunge/KiraBridge/.venv/bin/python -c \
'import sys; sys.path.append("/usr/local/lib/python3.11/site-packages"); import pytest; raise SystemExit(pytest.main(["-q", "tests/test_remote_relay.py"]))'
```

## Übergabe und verbleibende Grenzen

R2 liefert einen geprüften gemeinsamen lokalen Vertrags-/TLS-/Corepfad.
Produktive Geräte-/Operatorbindung, Stagingprofil, Handy-/Browseranzeige,
Mehrbenutzerbetrieb und tatsächlicher Remote-/Debianauftrag bleiben offen.
Interaktive Remote-Selbstabnahme bleibt gesperrt; die sichtbare produktive
Terminalroute wurde nicht auf einen strukturierten Ersatzweg umgestellt.

Keine neue RC, kein Paket, Mainmerge/PR, Deployment, Dienst-/VM-/Profilwechsel
oder Cloudbuild. Windows für Dirk bleibt priorisiert; R2 verändert weder
Restricted/0 von6 noch den eingefrorenen Payload `179bb6f`. NativeKoordinationC1
und fremde Agentensitzungen bleiben in ihrer eigenen Zuständigkeit.

Nächster begrenzter Schritt der Koordination: diesen gemeinsamen Quellnachweis
mit TD-M4 verknüpfen, dann das passende genehmigte native Windows-/Stagingpaket
unter seinen bestehenden Gates auswählen. Keine automatische Aktivierung aus R2.

Quellstände, Logs, beide lesenden Reviews, Manifest, Corebeleg und Handoff:
`~/.local/share/kirabridge/backups/bigplan-remote-project-verify-20261106-r2/`.
Finaler KB-Commit/Push und zurückgelesene Boardbelege stehen im Handoff.
