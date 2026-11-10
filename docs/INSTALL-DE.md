# KiraBridge installieren und aktualisieren · 0.8.0rc36

[English](INSTALL-EN.md) · [README](../README.de.md)

Die [veröffentlichte Intel-Vorabversion](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36) stammt vom 4. November 2026.
Ihr Code ist auf `d4aebdd89a206045731f2692a3f363fddaa15ee0` festgelegt.
[Release- und Downloadprüfung](evidence/readme-current-20261107.json).
Diese Anleitung installiert dieses veröffentlichte Paket. Die getrennt installierte
lokale RC40-Laufzeit bei `d12838a` ist ein späterer Quellbuild ohne veröffentlichten RC40-Download.

## Voraussetzungen

Normales Benutzerkonto ohne sudo, Python 3.11, uv 0.11.6, GitHub-Konto mit Zugriff
auf das private Repository und Internet zu GitHub/PyPI. Der Downloadbefehl im
Terminal benötigt zusätzlich die angemeldete GitHub CLI (`gh`).
Tatsächlich geprüft: Intel x86_64, macOS15.7.4. AppleSilicon, macOS26 sowie ältere
macOS-Versionen sind nicht durch diesen Intel-Nachweis abgenommen; iMac2015
bezeichnet Hardware und ersetzt keine OS-Abnahme.

Die App ist ad-hoc-signiert, ohne Apple-Notarisierung; Gatekeeper nicht global deaktivieren.
Keine automatische Änderung von OS-/TCC-Rechten, kein versteckter
Paketmanager-/Compiler-/Pythonaufbau. Agenten/Konten separat einrichten.
Private Downloads benötigen Anmeldung und Zugriff; für `gh` nutze `gh auth login`.
Keine Tokens kopieren.

## Installation / Update

1. Lade **KiraBridge-0.8.0rc36-Intel-Installer.zip** aus der [README](../README.de.md)
   herunter und entpacke es vollständig. Das Release bietet `SHA256SUMS` zur Prüfung.
2. Öffne `KiraBridge-Installer.app`, bestätige und folge der sichtbaren
   Terminalinstallation. Keine arbeitende Codex-/Grok-Sitzung als Installationsfenster verwenden.
3. Der Installer aktualisiert Dienst und Desktop-App gemeinsam und erstellt eine
   Rückfallsicherung. Öffne nach erfolgreichem Abschluss `KiraBridge.app` in `~/Applications`.

Das ZIP enthält das App-/Dienstpaket; Python und uv bleiben Voraussetzungen.
Python 3.11 und uv 0.11.6 müssen vorher im Terminal verfügbar sein. Der Installer verbindet kein ChatGPT-Konto automatisch.
Nur bei fehlender Verbindung im lokalen Terminal
`~/.local/bin/kirabridge chatgpt setup --language de` starten und der
[Verbindungsanleitung](CHATGPT.md) folgen.

Für dieselbe App-/Dienstinstallation im Terminal ist der authentifizierte Bootstrap verfügbar:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc36 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --desktop --require-visible-terminal --language de)
```

Er lädt den Installer als Datei, prüft ihn und anschließend das festgelegte
Dienstpaket. Nach dem vollständigen Entpacken des Dienstarchivs ist der direkte Einstieg:

```sh
sh KiraBridge/install.sh --desktop --require-visible-terminal --language de --motion full
```

Reduzierte Bewegung: `--motion reduced`; Sprache: `--language de` oder `--language en`.
Diese Darstellungsschalter sind im aktuellen Paket vorhanden; für ältere Archive
nicht voraussetzen. Der Renderer wird aus dem geprüften Paket geladen; Fehler- und
Statusmeldungen haben Vorrang, statischer Text bleibt verfügbar.

Neue Installation: Benutzerdateien mit eigenem Konfigurations-/Datenpfad.
Update: dieselbe versionierte Transaktion mit Backup, Leerlauf-, Ownership-,
Integritäts- und Healthprüfungen. Vorhandene Konfiguration, Zugangsdaten,
Berechtigungen, Whiteboards, Datenbank und Nutzerdateien erhalten. Keine Rechte
ändern, keine unbekannten Jobs wiederholen und fremde Dienste nicht ersetzen.
Ausnahme ab RC46: In einem vorhandenen `[threaddesk]`-Abschnitt (Start über
`-m threaddesk.ui.mcp_stdio`) zeigen `source_root` und `command` danach auf die
mitgelieferte Bibliothek `install/shared/threaddesk-<pin>/src` und das Python der
Release. `rollback` setzt genau diese zwei Werte zurück, solange sie seitdem
niemand geändert hat.

Der launchd-Benutzerdienst läuft weiter, wenn Terminal oder Browser geschlossen
werden. Die sichtbare Installation ist kein Fenster, das den Dienst am Leben hält.

## Status und Rückweg

`~/.local/bin/kirabridge status` liest den tatsächlich antwortenden Dienst.
`python3.11 KiraBridge/installer/install.py status` nennt zusätzlich den
installierten Commit. Nach geklärter Leerlaufsituation kann der Betreiber
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge` verwenden und den
Status erneut lesen; dieser Neustart darf keine laufenden Aufträge unterbrechen.

Logs: `~/.local/share/kirabridge/install/logs/`. Backups und Laufzeiten:
`~/.local/share/kirabridge/install/`. Konfiguration und separate Zugangsdaten:
`~/.config/kirabridge/`. Kein PATH- oder Shellprofil wird für diese Installation
automatisch umgeschrieben.

Rollback aus dem erhaltenen, zuletzt installierten Paket, im sichtbaren Terminal:
`python3.11 KiraBridge/installer/install.py rollback --bundle KiraBridge --require-visible-terminal`.
Ohne `--bundle` bricht der Desktop-Schritt ab.
Vorhandene Guards und neue Daten bleiben erhalten; keine Datenbank unbesehen
zurückspielen. Erst eine erfolgreich gelesene alte Dienstversion bestätigt den
Rückweg. Ein Timeout oder nur zurückgesetzter Versionszeiger reicht nicht.

## Fehlerbehebung

- `BUSY`: gemeldete echte Arbeit prüfen und geordnet abschließen lassen. Keine
  Codex-/Grok-Sitzung töten und keine pauschale Queue-Löschung erzwingen.
- Sichtbarkeit/Fenster/TTY geändert: im einen eigenen bestätigten Arbeitsfenster
  fortsetzen; kein verstecktes Ersatzterminal. Keine fremde Session auswählen.
- Prüfsumme falsch: vor Ausführung abbrechen und autorisiertes Original beziehen.
- GitHub403/404: Anmeldung und Zugriff auf privates Repository/Entwurf prüfen.
- Bereits belegter Port oder fremde Dienstdefinition: Besitzer klären, erhalten.
- Readiness-Timeout: Exitcode/Logs/Transaktion prüfen; keinen Erfolg behaupten.

[Nachgewiesener Intel-Rollback und ursprünglicher Fehler](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC14-ROLLBACK-20261026.md).

## Bekannte Einschränkungen in RC36

RC36 repariert die Fenstererzeugung bei minimierten Terminalfenstern; spätere
native Prüfungen reproduzierten aber einen Tabwechselfehler. Die lokalen
RC37–RC40-Reparaturen sind nicht in diesem Download enthalten. Siehe [RC36-Bericht](TERMINAL-MINIMIZED-RC36-20261104.md)
und [anschließende Reparatur](TERMINAL-RECOVERY-20261104.md).
Interaktive Agentenmenüs wie `/resume` entsprechen keinem gewöhnlichen Arbeitsauftrag;
benutze bei benötigtem Menü das eigene Terminal des Agenten.

Apple Silicon, andere macOS-Versionen und andere Plattformen sind durch die
Intel-Releaseprüfungen nicht bestätigt. Eine empfangene oder freigegebene Anfrage
ist noch kein fertiger Auftrag; prüfe unklare Ergebnisse vor einer Wiederholung.
Gespeicherte Ergebnisse wecken keinen inaktiven Chat automatisch auf. Nicht jeder
Chat- oder Sprachmodus ist garantiert verfügbar.
[Releasedetails und Belege](evidence/readme-current-20261107.json).

## Wenn macOS die App blockiert

Die App hat keine Apple-Notarisierung. Prüfe die Herkunft vom verlinkten Release
und die Prüfsumme aus `SHA256SUMS`; bei Abweichung abbrechen. Wenn macOS eine
geprüfte App blockiert, der du vertraust, nutze die Freigabe für diese einzelne App
unter Systemeinstellungen → Datenschutz & Sicherheit, sofern angeboten.
Gatekeeper nicht pauschal deaktivieren. [Apples Anleitung](https://support.apple.com/en-us/102445).

## Andere Plattformen und optionale Werkzeuge

Die separate [Windows-Einrichtungsvorschau](WINDOWS-SETUP-20261104.md) bietet ein
begrenztes Tastatur-/Fenster-/MCP-Paket, keinen aktuellen macOS-Funktionsgleichstand
oder Windows-Dienstinstaller. Windows-/Installer- und Linux-/Debian-Serverarbeit
läuft weiter. Ältere veröffentlichte Linuxartefakte belegen keine Abnahme dieser
aktuellen Serverarbeit. Der Quellstand enthält einen separaten Linuxinstaller;
Paketbau und native Abnahme sind von dieser Intel-macOS-Anleitung getrennt.
ThreadDesk und Providerintegrationen sind optional, keine Kernvoraussetzungen.

[macOS-Vertrag](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INSTALL-MACOS.md),
[Teamkoordination](TEAM-ORCHESTRATION.md), [Werkzeuge und Grenzen](../README.de.md),
[ChatGPT-Einrichtung](CHATGPT.md), [RC36-Releasehinweise](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc36/docs/RELEASE-0.8.0rc36.md).
