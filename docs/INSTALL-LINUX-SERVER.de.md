# KiraBridge als Linux-Server

KiraBridge läuft hier als privater MCP-Dienst in einer systemd-Benutzersitzung.
Das ist die Serverfassung von KiraBridge, nicht ThreadDesk Server&Sync und nicht
die macOS-Desktopinstallation.

## Paket prüfen

Das Archiv heißt `KiraBridge-<version>-Linux-x86_64.tar.gz`. Daneben liegt
dieselbe Prüfsumme in `SHA256SUMS` und in `<archiv>.sha256`.

```sh
sha256sum -c KiraBridge-*-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-*-Linux-x86_64.tar.gz
cd KiraBridge-*-Linux-x86_64
sha256sum -c SHA256SUMS
```

Bei einer Abweichung abbrechen. Das Paket ist für Ubuntu 24.04 auf x86_64
gebaut. Andere Distributionen sind damit nicht bestätigt.

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

Die Unit folgt `examples/kirabridge.service`. `secrets.env` ist optional.
Fehlt die Datei, startet der Dienst trotzdem. Es wird kein Linger gesetzt
und kein Systemdienst installiert.

## Zugang

Der Dienst spricht HTTP nur auf dem konfigurierten Loopback-Endpunkt.
Jeder Aufruf braucht `Authorization: Bearer`. Ohne oder mit falschem Token
antwortet der Dienst mit 401. `bridge_health` ist der authentifizierte
Gesundheitsaufruf. Er bestätigt den lokalen Dispatcher und nicht eine
ChatGPT-Verbindung.

## Grenzen

Auf diesem Server gibt es keine macOS-GUI, kein Terminal.app, keine native
Tastatursteuerung und keine Desktop-Sitzung. Die Zwischenablage ist nur
verfügbar, wenn `wl-clipboard` oder `xclip` vorhanden ist, und der Server
braucht sie nicht. `platform.status` und `bridge_health` melden diese
Grenzen. Sie behaupten keine GUI-Parität.

Ein Test auf macOS ist kein Linux-Nachweis. Die native Abnahme steht separat
in `docs/evidence/linux-server-grok-20261107.json`.

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
