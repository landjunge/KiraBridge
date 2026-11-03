# RC24 auf dem Operator-Mac installiert · 1. November 2026

Der Intel-Mac läuft jetzt mit **KiraBridge 0.8.0rc24**, Quelle
`023f70feefcf8fcaa17b0637738b02644ad6b357`. Unterstützter Installer,
Freigabekonsole und Companion-App wurden in einem eigenen, physisch getrennten
Terminalfenster aktualisiert. Die Abschlussprüfung bestand. Dieser Nachweis
ersetzt frühere Aussagen „Installation offen“ in historischen Checkpoints.

## Repariertes Fensterproblem

Der alte Open-Pfad erzeugte einen logischen Terminal-Tab, ohne das versprochene
separate physische Fenster zu beweisen. Der produktive Pfad in
`platform_adapters/terminal_app.py:878` und `macos/terminal_window.py:33`
bindet genau eine Erzeugung an Nonce, TTY und App-/Worker-Generation. Er prüft
die ursprüngliche AX-/CG-Partition und erlaubt höchstens einen bestätigten
Move. Ein Befehl startet erst nach positiver physischer Zuordnung.

Zwei dabei bestätigte Fehler sind geschlossen: CG-Kennungen konnten beim
Trennen ihre Own-/Hostrolle wechseln; zudem liefen AX- und CG-Inventare kurz
auseinander. Der Code ordnet Rollen positiv zu und beobachtet ausschließlich
nach bekanntem Move diesen spezifischen Übergang begrenzt neu. Er wiederholt
keine Fensteraktion. Andere Identitäts-/Partitionsfehler bleiben Verweigerungen.
Die Creationreceipt wird vor weiteren UI-Effekten dauerhaft gespeichert.

## Tatsächlich bestandene Abnahme

Das unveränderte gebaute Paket bestand den offiziellen isolierten
Darwin-x86_64-Smoke mit Authentifizierung, geladenem Quellvergleich,
Korruptpaketverweigerung sowie Konfigurations- und Credentialerhalt.

Die reale native Abnahme `actual-codex-023f70f-01` verwendete die produktiven
APIs, einen isolierten Dispatcher und Codex 0.166.0:

- Genau ein eigenes physisches Fenster, bestätigte kontrollierte Shell,
  Codex-Start und unabhängiges Ausgabelesen.
- Beschäftigte Shell und veraltete PID vor Eingabe verweigert.
- Mehrdeutige Geometrie vor Paste verweigert; vorhandener Entwurf unverändert.
- Lange Literalnachricht mit genau einem Paste/Return und eigener Antwort.
- Unveränderter `body_only_v1`-Handoff mit unabhängig gebundener Antwort.
- Eigenes Testfenster und eigene Prozesse anschließend unabhängig abwesend;
  private Verbindung beendet, ursprüngliche drei Terminalansichten und fünf
  Agentprozessgenerationen erhalten. Kein historischer Auftrag wiederholt.

`passed`, `tests_passed`, `cleanup_complete` und `private_endpoint_absent`
sind im privaten Originalbeleg jeweils `true`. Kleine direkte Regressionstests
und ein unabhängiger Mac-Review gingen dieser Abnahme voraus. Frühere
fehlgeschlagene Läufe sind im Backup erhalten und werden nicht als bestanden
gezählt. Weitere Review-/Testdetails: [Fortsetzungsbericht](RELIABILITY-FOLLOWUP-20261101.md).

## Laufende Installation und Datenerhalt

| Bestandteil | Bestätigter Zustand |
| --- | --- |
| Core | PID **78414**, Start **2026-11-01T21:58:48.712921+00:00**, Dispatcher aktiv |
| Instanz | `6c6077f4315f4fe59b1379cea2d8670e` |
| Quellbaum | **146 Pythondateien**, SHA256 `5dcf092905b1f89db76439d12b8a93039e1f5d4d479baf9ddf91f74c229beb25` |
| Companion-App | PID **78865**, Start **23:00:06 CET**, Codesign und Dateien gegen Stage geprüft |
| Native Binärdatei | SHA256 `bd1d85664810ed319b084e5268bcb809ff398de80c7746c93c723b54a5ecb8db` |
| Freigabekonsole | PID **78630**, authentifizierte Instanz geprüft |
| Tatsächlicher MCP-Anschluss | Neue Core-Identität und Ausgabe des eigenen Installationsfensters gelesen |
| macOS | Core meldet Accessibility und Screen-Capture erteilt; keine Rechte angefordert |

Core, Konsole, App und gemeinsame Verifikation besitzen getrennte erfolgreiche
Installationsbelege. Installierte Pythondateien wurden zusätzlich nach Start
gehasht; Versionslabel allein war kein Erfolgsmaßstab. Konfiguration,
Zugangsdaten, Dateimodi und geschützte Agent-/Tunnel-/Proxyprozessgenerationen
blieben erhalten. Historische 88 unbekannte Tasks, 10 Handoffs, 23 geschützte
Nachrichtenjobs, 30 Holds und 28 Withdrawals wurden unverändert rückgelesen.
Nur der vorgesehene Konsolenstarter wurde aktualisiert und das App-Login-Ticket
regulär erneuert.

Das eigene Installationsfenster `terminal:1470:ttys004` wurde einmal geschlossen.
Zwei Controllerprüfungen und eine unabhängige Katalogabfrage über den aktuellen
MCP-Anschluss bestätigten die Abwesenheit. Die drei ursprünglichen Ansichten
231/327/590 sind erhalten. Ein Rollback war nicht nötig; RC22, alte App,
Konfiguration und konsistente SQLite-Sicherung bleiben als Rückrollpunkt liegen.

## Lieferung und Grenzen

Installer und Prüfsummen liegen lokal in
`~/Downloads/KiraBridge-RC24-Intel-023f70f/`.

- `KiraBridge-0.8.0rc24-Intel-macOS.zip`: SHA256
  `ba68a3f42b09abf7c7aec11eaf913a994d5bfe2ed6036fe5c61d9a70e033dcd9`.
- Runtime-Bundle: SHA256
  `ec72a0796f7160887a335a32d5564f28601eafb937e9d33a2387532da5d10800`.
- `PACKAGE-ACCEPTANCE-INTEL.json` und `SHA256SUMS-INTEL` enthalten den aktuellen
  lokalen Abnahmebeleg. Ältere Kandidatenhinweise im unveränderten Paket sind
  historische Checkpoints.

Private Originalbelege und Sicherung:
`~/.local/share/kirabridge/backups/reliability-continuation-20261101T144926Z/`.
Die frische Vorinstallation liegt unter
`visible-product-install-023f70f-01/baseline/`, die einzelnen Installationsbelege
unter `productive-023f70f/*-install-b540378548c52160.*.json`.

Keine weiteren GitHub Actions, Pushes oder GitHub-Veröffentlichungen wurden
gestartet. Der letzte gepushte Commit bleibt `154d77fd4df8d8fdddd6818b6ca55236e1a8dfcd`;
die finalen lokalen Änderungen haben keinen neuen Vierplattform-CI-Nachweis.
Die reale Codex-Abnahme lief mit exakt derselben Paketquelle im isolierten
Dispatcher; die produktive Instanz wurde danach gesondert mit Quellidentität,
MCP-Verbindung, Terminallesen und Statusabfragen ohne Berechtigungsdialog geprüft.

Die vorhandene Diagnosehistorie bleibt am Kapazitätslimit; Task-, Nachrichten-
und Auditbelege arbeiten unabhängig davon. tmux ist auf diesem Mac nicht
verfügbar; die erfolgreiche Abnahme gilt für Terminal.app. Ein unbeobachtbarer
anderer Desktop bleibt eine sichere Verweigerung. Daraus folgt keine Garantie
für alle Desktopzustände oder eine abgeschlossene Apple-Silicon-Abnahme.
