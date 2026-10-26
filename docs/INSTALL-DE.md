# KiraBridge installieren und aktualisieren · 0.8.0rc17

RC17: Intel-Abnahme und ausdrückliche Betreiberfreigabe dokumentiert in
[Intel-Abnahme](INTEL-ACCEPTANCE-20261026.md). Der tatsächliche
[Release-Status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17)
und der antwortende installierte Dienst sind getrennt; ein Entwurf ist nicht veröffentlicht.

## Voraussetzungen

Normales Benutzerkonto ohne sudo, Python3.11, uv0.11.6, GitHubCLI mit
authentifiziertem privatem Repositoryzugriff und Internet zu GitHub/PyPI.
Tatsächlich geprüft: Intel x86_64, macOS15.7.4. AppleSilicon, macOS26 sowie ältere
macOS-Versionen sind nicht durch diesen Intel-Nachweis abgenommen; iMac2015
bezeichnet Hardware und ersetzt keine OS-Abnahme.

Keine Apple-Signierung/Notarisierung; Gatekeeper nicht global deaktivieren.
Keine automatische Änderung von OS-/TCC-Rechten, kein versteckter
Paketmanager-/Compiler-/Pythonaufbau. Agenten/Konten separat einrichten.
Private Downloads benötigen `gh auth login` und Zugriff; keine Tokens kopieren.

## Installation / Update

Der eine authentifizierte Installations-/Updatebefehl steht in der
[README](../README.md). Er prüft Bootstrap und macOS-Paket vor Ausführung.
Nach dem geprüften Entpacken ist der direkte sichtbare Einstieg:

```sh
sh KiraBridge/install.sh --require-visible-terminal --motion full
```

Reduzierte Bewegung: `--motion reduced`; Sprache: `--language de` oder `--language en`.
Die Darstellungsschalter gehören zum RC17-Paket, nicht zu älteren Reviewarchiven. Der Renderer wird aus dem geprüften Paket geladen; Fehler- und
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

[Nachgewiesener Intel-Rollback und ursprünglicher Fehler](RC14-ROLLBACK-20261026.md).

## Andere Plattformen und optionale Werkzeuge

Der eigenständige Linux-Quellinstaller bleibt erhalten. Linuxpakete werden auf
Ubuntu24.04-x86_64 getestet; dieser Mac-Lauf ist kein Linux- oder ARM-Nachweis.
Ein Linuxpaket startet über seinen eigenen `sh install.sh`-Pfad und unterstützt
`--language en`; vorhandene Guided-Setup-/ChatGPT-Konfiguration bleibt getrennt
vom macOS-Versionsinstaller. Codex/Grok und weitere Providerzugänge sind separat
einzurichten. ThreadDesk ist optional und keine Installationsvoraussetzung.

[Teamkoordination](TEAM-ORCHESTRATION.md), [Werkzeuge und Grenzen](../README.md),
[ChatGPT-Einrichtung](CHATGPT.md), [Releasehinweise](RELEASE-0.8.0rc17.md).
