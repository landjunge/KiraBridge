# Windows-Kernport: native Abnahme des Auftrags vom 6. November 2026

Technisch geprüfter Code- und Paketpin:
`10ed989ae55ae8d2b38a723a903cfea8ed88c22b` (0.8.0rc40).
Abnahme in der Nacht zum 7. November auf der bereits laufenden Windows-11-
Enterprise-Evaluation-VM **KiraBridge Windows Dev Fix1**, AMD64,
UUID `2B6EE828-02F0-42AE-B4FE-BE57C448F65E`, Python 3.14.10.

Grok übernahm zuerst und implementierte den Produktcode. Modell `grok-4.7`,
Denkstufe **high** wurden als echte CLI-Argumente gesetzt und per Prozessaufruf
sowie Annahmedatei bestätigt. Eine Provider-Attestierung wird nicht behauptet.
Codex koordinierte, prüfte die Quellen unabhängig und führte die native Abnahme.
Der letzte Grok-Turn endete nach Codecommit und Paketbau als `cancelled`;
der gesicherte Stand wurde unabhängig geprüft. Ein Test verglich unzulässig den
Unterstring `old` mit dem macOS-Pfad `/var/folders`; Codex korrigierte ausschließlich
diese Pfadprüfung und wiederholte den betroffenen Fall erfolgreich.

## Tatsächlich geprüfter Umfang

| Bereich | Native Prüfung |
| --- | --- |
| Tastatur | Neun Fälle mit echten Win32-Ereignissen: US/DE, Y/Z, AltGr, Unicode, Return, Backspace, erweiterter Pfeil und Funktionstaste. |
| Text | Authentifizierter MCP-Aufruf; `Größe € 😀`, Zeilenumbruch und mehr als 32 Zeichen am eigenen WM_CHAR-Empfänger vollständig zurückgelesen. |
| Fenster | Sieben Fälle: Verschieben/Größe, Maximieren, Wiederherstellen, Minimieren, Aktivieren aus eigenem Hilfsfenster und bestätigtes Schließen. |
| Apps | Echter CreateProcess-Start einer eigenen GUI, Prozessgeneration/HWND unabhängig zugeordnet, Inventar und tatsächlicher Fokuswechsel geprüft, eigene Fenster anschließend abwesend. |
| Terminal | Neue sichtbare Konsole, sichtbares HWND unabhängig beobachtet; Befehlsausgabe und Originalreceipt verglichen. Native PowerShell-Ausgabe mit cp1252 und cp850 vollständig zurückgeliefert. |
| Status/Abschluss | Gespeicherten Originalstatus geprüft; gleiche Handoff-ID erzeugt keinen zweiten Start. Manipulierte/mehrdeutige Receipts bleiben offen; portable Regressionen prüfen diese Fälle. |
| Paket | Im Gast aus unverändertem Export gebaut, alle Paketbytes/Provenienz geprüft und als ZIP zum Host zurückgeführt. Bytegleich mit dem Hostbau. |
| Installation/Update/Rollback | Neue parallele Installation der Baseline d12838a, Update auf 10ed989, echte Importe aus den jeweiligen Releases, Rückkehr zur Baseline und Wiederaktivierung des getesteten Releases; eigene Datendatei unverändert. |

Alle elf Pipelineschritte endeten mit Exit 0. Der unabhängige E2E-Treiber prüfte
neun neue API-Tasks über einen authentifizierten lokalen MCP-Server; alle
Effekte wurden unabhängig bestätigt. Die Quellen blieben unverändert.
24 direkt betroffene portable Regressionen sind abgedeckt (23 im ersten Lauf,
der korrigierte Einzelfall separat); Ruff bestand. Frühere Setup-/Testfehler
bleiben in den ursprünglichen Berichten erhalten, Testzahlen werden nicht addiert.

UTM-Eingabe diente ausschließlich dem Staging und dem Start in einer eigenen
sichtbaren Gastkonsole. Die Produktprüfungen verwendeten Win32 und MCP im Gast.
Die PowerShell-Richtlinie war vor und nach dem Lauf **Restricted**.
Kein Richtlinienoverride, kein VM-Neustart, keine Änderung der Macinstallation.

## Paket und aktiver Teststand

`dist/KiraBridge-0.8.0rc40-Windows-10ed989-native.zip`, 2.609.875 Bytes.
SHA256:
`6709320ead6f5071d597e747da867de5bb85408cc5cff161e28c779c3b480ea2`.

Das ZIP enthält den geprüften Quell-/Runtimeexport, LICENSE, Abnahmeharnesses und
`provenance.json`. Es verwendet das vorhandene vorbereitete Python samt
Abhängigkeiten. Beispielbefehle aus dem entpackten Paket:

```text
python -B scripts/windows_parity_package.py build --output native.zip --provenance-export provenance.json
python -B scripts/windows_parity_package.py install --root <neuer-root> --payload <entpacktes-paket>
python -B scripts/windows_parity_package.py update --root <bestehender-testroot> --payload <entpacktes-paket>
python -B scripts/windows_parity_package.py rollback --root <bestehender-testroot>
```

Im Gast liegt der geprüfte aktivierte Dateistand unter
`C:\Users\Kiradev\AppData\Local\KiraParity20261106Grok01\install\releases\0.8.0rc40-10ed989ae55a`.
Bestehende RC31-/RC33-Installationen wurden nicht ersetzt.

## Offene Plattformabweichungen

- Kein Andocken an vorhandene Windows-Terminaltabs oder interaktive CLI-Agentensitzungen.
- ZIP mit vorbereitetem Python; eigenständiges EXE/MSI, Windows-Dienst/Autostart und Migration bestehender Setups sind offen.
- Der eingeschränkte Windows-Preview behält seine bisherigen Capabilities. Die neuen Operationen wurden mit explizit konfigurierter Bridge im lokalen MCP-E2E geprüft.
- Windows 10, Dirks Hardware und die Remote-/ChatGPT-/Handy-Verbindung zum Windows-Gateway sind nicht abgenommen.
- Vollständige AX/UIA-, Clipboard-, Sprach- und Systemtastenparität mit macOS ist nicht belegt. Windows-Text hat weiterhin die dokumentierten Größen-/Ereignisgrenzen.

Die Abnahme gilt für diesen Kernumfang, diesen Quellstand und die genannte VM.
Spätere Nachweis-/Testtreibercommits ändern das getestete Laufzeitpaket nicht.

Der gepflegte unabhängige Treiber steht unter
`scripts/accept_windows_parity_e2e.py` (Parameter `--source`, `--root`, `--output`;
neue disjunkte Testpfade verwenden). Nach dem nativen Lauf wurde er formatiert,
ein ungenutzter Import entfernt und die innerhalb der Schleife sofort
abgewartete Hilfsprozess-Closure explizit gebunden. Die exakt ausgeführten
Treiberbytes bleiben als [Rohquelle](evidence/windows-parity-native-driver-20261106.txt)
mit dem Hash aus dem nativen Bericht erhalten.

Die breite Linux-CI auf `6b282c3` deckte zusätzlich einen bestehenden
Kalenderfehler in Routingtests auf: Hook-/Launcherpfade verwendeten die reale
Uhr gegen feste, inzwischen abgelaufene Nachweise vom 5. November. Nur die
Testuhr des Routers wurde an das vorhandene `NOW` gebunden; echte Transport-
und Timeoutuhren sowie sämtliche produktiven Ablaufprüfungen bleiben erhalten.
Alle 73 Routingtests bestanden anschließend lokal mit strikter Unraisable-
Prüfung. [Fehler und Korrektur](evidence/windows-parity-ci-clock-20261107.json)
bleiben dokumentiert; die endgültige breite CI ist in den Checks von PR #70
ausgewiesen. Das nativ geprüfte Paket wird dadurch nicht verändert.

[Zusammenfassung und Fingerprints](evidence/windows-parity-native-acceptance-20261106.json)
· [Native Rohbelege](evidence/windows-parity-native-raw-20261106.json)
· [Initiale Grok-Annahme](evidence/windows-parity-grok-acceptance-20261106.json)
