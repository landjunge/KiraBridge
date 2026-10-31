# KiraBridge installieren und aktualisieren · 0.8.0rc20

[English](INSTALL-EN.md) · [README](../README.de.md)

Die [veröffentlichte Intel-Vorabversion](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20) stammt vom 30. Oktober 2026.
Ihr Code ist auf `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4` festgelegt.
[Release- und Downloadprüfung](README-REVIEW-20261031.md).

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

1. Lade das ZIP **App und Dienst-Installer** aus der [README](../README.de.md)
   herunter und entpacke es vollständig. `INSTALLIEREN-DE.txt` enthält die Paketanleitung.
2. Öffne `KiraBridge-Installieren.command`. Sie startet den Dienst-Installer in
   einem sichtbaren Terminalfenster. Nicht in einer arbeitenden Codex-/Grok-Sitzung ausführen.
3. Kopiere nach erfolgreicher Installation `KiraBridge.app` nach `~/Applications`
   (Ordner bei Bedarf anlegen) und öffne sie. Eine vorhandene App vor dem Ersetzen schließen.

Das separate ZIP **Nur die App** benötigt einen bereits installierten Dienst.
Python und uv liegen keinem der ZIPs bei; Python 3.11 und uv 0.11.6 müssen vorher
im Terminal verfügbar sein. Der Installer verbindet kein ChatGPT-Konto automatisch.
Nur bei fehlender Verbindung im lokalen Terminal
`~/.local/bin/kirabridge chatgpt setup --language de` starten und der
[Verbindungsanleitung](CHATGPT.md) folgen.

Für die Installation im Terminal bleibt der authentifizierte Bootstrap verfügbar:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc20 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --require-visible-terminal --language de)
```

Er lädt den Installer als Datei, prüft ihn und anschließend das festgelegte
Dienstpaket. Nach dem vollständigen Entpacken des Dienstarchivs ist der direkte Einstieg:

```sh
sh KiraBridge/install.sh --require-visible-terminal --language de --motion full
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

Rollback aus dem erhaltenen Paket: `python3.11 KiraBridge/installer/install.py rollback`.
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

## Bekannte Einschränkungen in RC20

Interaktive Agentenbefehle wie `/resume` können über KiraBridge als Arbeitsauftrag
ankommen, statt das Menü des Agenten zu öffnen. Gib sie direkt im Terminal des
Agenten ein. Manche bereiten Codex-Sitzungen können außerdem als nicht verfügbar
erscheinen. Spätere lokale Reparaturen sind nicht im veröffentlichten RC20-Download enthalten.

Apple Silicon, andere macOS-Versionen und andere Plattformen sind durch die
Intel-Releaseprüfungen nicht bestätigt. Eine empfangene oder freigegebene Anfrage
ist noch kein fertiger Auftrag; prüfe unklare Ergebnisse vor einer Wiederholung.
Gespeicherte Ergebnisse wecken keinen inaktiven Chat automatisch auf. Nicht jeder
Chat- oder Sprachmodus ist garantiert verfügbar.
[Releasedetails und Belege](README-REVIEW-20261031.md).

## Wenn macOS die App blockiert

Die App hat keine Apple-Notarisierung. Prüfe die Herkunft vom verlinkten Release
und die Prüfsumme aus `SHA256SUMS-INTEL`; bei Abweichung abbrechen. Wenn macOS eine
geprüfte App blockiert, der du vertraust, nutze die Freigabe für diese einzelne App
unter Systemeinstellungen → Datenschutz & Sicherheit, sofern angeboten.
Gatekeeper nicht pauschal deaktivieren. [Apples Anleitung](https://support.apple.com/en-us/102445).

## Andere Plattformen und optionale Werkzeuge

RC20 veröffentlicht kein direkt installierbares Linux-, Windows- oder Apple-Silicon-Paket.
Der eigenständige Linux-Quellinstaller bleibt erhalten. Linuxpakete werden auf
Ubuntu24.04-x86_64 getestet; dieser Mac-Lauf ist kein Linux- oder ARM-Nachweis.
Ein Linuxpaket startet über seinen eigenen `sh install.sh`-Pfad und unterstützt
`--language en`; vorhandene Guided-Setup-/ChatGPT-Konfiguration bleibt getrennt
vom macOS-Versionsinstaller. Codex/Grok und weitere Providerzugänge sind separat
einzurichten. ThreadDesk ist optional und keine Installationsvoraussetzung.

[Teamkoordination](TEAM-ORCHESTRATION.md), [Werkzeuge und Grenzen](../README.de.md),
[ChatGPT-Einrichtung](CHATGPT.md), [RC20-Releasehinweise](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc20/docs/RELEASE-0.8.0rc20.md).
