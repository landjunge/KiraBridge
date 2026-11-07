# KiraBridge als Linux-Server

KiraBridge läuft hier als privater MCP-Dienst in einer systemd-Benutzersitzung.
Das ist die Serverfassung von KiraBridge, nicht ThreadDesk Server&Sync und nicht
die macOS-Desktopinstallation.

## Download und Voraussetzungen

RC41 verwendet das separate Prerelease `linux-v0.8.0rc41`. Das Repository ist
privat: Dirk benötigt ein GitHub-Konto mit Repositoryzugriff (`gh auth login`),
oder der Betreiber stellt ihm das unveränderte Archiv mit Prüfsummen bereit.
Das Paket enthält keine Zugangsdaten.

```sh
gh release download linux-v0.8.0rc41 -R landjunge/KiraBridge \
  -p 'KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz*' -p SHA256SUMS
```

Vorausgesetzt werden Debian 13 oder Ubuntu 24.04 x86_64, ein normaler Benutzer,
`sh`, `tar`, `curl`, CA-Zertifikate und `sha256sum`. Für den Standarddienst muss
der systemd-Benutzermanager laufen (`systemctl --user is-system-running`).
Der Bootstrap lädt uv 0.11.6 mit SHA-Prüfung, CPython 3.11.15 und gesperrte
Pythonabhängigkeiten von GitHub/PyPI. Das System-Python wird nicht ersetzt.
Das ist ein Onlineinstaller, kein vollständig offline nutzbares Paket. Keine
automatische Änderung an Administratorrechten, Paketverwaltung, Firewall,
Berechtigungen oder Linger. Bei `Linger=no` hängt die Dienstlebensdauer von der
Benutzersitzungsrichtlinie des Hosts ab; Betrieb über Logout/Neustart hinaus
benötigt einen vom Betreiber eingerichteten Benutzermanager.

## Paket prüfen

Das Archiv heißt `KiraBridge-<version>-Linux-x86_64.tar.gz`. Daneben liegt
dieselbe Prüfsumme in `SHA256SUMS` und in `<archiv>.sha256`.

```sh
sha256sum -c KiraBridge-*-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-*-Linux-x86_64.tar.gz
cd KiraBridge-*-Linux-x86_64
sha256sum -c SHA256SUMS
```

Bei einer Abweichung abbrechen. Das Paket akzeptiert Debian 13 und Ubuntu 24.04
auf x86_64.

## Installieren und aktualisieren

Als normaler Benutzer, ohne `sudo`:

```sh
sh install.sh --yes
```

Englisch: `sh install.sh --yes --language en`.
Nur die Laufzeit vorbereiten, ohne Dienst: `sh install.sh --prepare-only --yes`.
Launcher ohne Dienst: `sh install.sh --yes --service none`.

`install.sh` prüft das Paket, legt die gepinnte Laufzeit unter
`~/.local/share/kirabridge/releases/<version>-<commit>` ab und ruft
`installer/install.py` auf. Eine vorhandene Konfiguration und vorhandene
Zugangsdaten werden nicht ersetzt. Neue Aufgaben, Ergebnisse und
UNKNOWN-Zustände bleiben in der bestehenden Datenbank. Ein Rollback schreibt
kein altes Datenbankbackup darüber.

Der Dienst ist die Benutzerunit `kirabridge.service`:

```sh
systemctl --user status kirabridge.service
systemctl --user restart kirabridge.service
```

Die Unit folgt `examples/kirabridge.service`. Die optionale `secrets.env` liegt
neben der gewählten Konfigurationsdatei; eine isolierte Installation lädt nicht
die Standard-Umgebungsdatei einer anderen Installation.
Fehlt die Datei, startet der Dienst trotzdem. Es wird kein Linger gesetzt
und kein Systemdienst installiert.

## Zugang

Der Dienst spricht HTTP nur auf dem konfigurierten Loopback-Endpunkt.
Jeder Aufruf braucht `Authorization: Bearer`. Ohne oder mit falschem Token
antwortet der Dienst mit 401. `bridge_health` ist der authentifizierte
Gesundheitsaufruf. Er bestätigt den lokalen Dispatcher und nicht eine
ChatGPT-Verbindung.

Für einen vertrauenswürdigen Remoteclient die Loopbackbindung behalten und bei
Bedarf einen SSH-Tunnel nutzen, etwa
`ssh -N -L 18765:127.0.0.1:8765 benutzer@host`; der Client verwendet dann
`http://127.0.0.1:18765/mcp`. Bearer-Zugang lokal aus der privaten Datei
`~/.config/kirabridge/credentials.json` beziehen, niemals in URL, Shellverlauf
oder Bericht schreiben. ChatGPT-Verbindung, öffentlicher HTTPS-Endpunkt und
Kontoverknüpfung benötigen gesonderte Einrichtung; die Installation stellt sie
nicht automatisch her.

## Grenzen

Auf diesem Server gibt es keine macOS-GUI, kein Terminal.app, keine native
Tastatursteuerung und keine Desktop-Sitzung. Die Zwischenablage ist nur
verfügbar, wenn `wl-clipboard` oder `xclip` vorhanden ist, und der Server
braucht sie nicht. `platform.status` und `bridge_health` melden diese
Grenzen. Sie behaupten keine GUI-Parität.

Native Debian-Paketergebnisse stehen in den Evidence-/JUnit-Assets des
Prereleases und in `docs/evidence/debian-dirktest-release-20261107.json`.
Groks früherer Bericht `linux-server-grok-20261107.json` beschreibt die noch
nicht abgenommene RC40-Basis. macOS- oder Ubuntu-Containertests sind keine
native Debian-Abnahme.

## Rollback

Mit denselben Pfaden wie bei der Installation:

```sh
~/.local/share/kirabridge/releases/<version>-<commit>/.venv/bin/python3 \
  installer/install.py rollback \
  --prefix "${XDG_DATA_HOME:-$HOME/.local/share}/kirabridge/install" \
  --config "${XDG_CONFIG_HOME:-$HOME/.config}/kirabridge/config.toml" \
  --launcher "$HOME/.local/bin/kirabridge" \
  --service systemd-user
```

Zurück kommen der vorherige Launcher und die vorherige Unit. Konfiguration,
Zugangsdaten, Tasks und UNKNOWN-Zustände bleiben die aktuellen Dateien.
