# Windows standalone package / Eigenständiges Windowspaket

This offline x64 package contains CPython, its dependencies and the pinned KiraBridge
source. Extract the entire ZIP before running any command. A separately installed
Python, Git, pip, administrator account or PowerShell policy change is unnecessary.
This is a directory-based installer, with no Windows service or registry registration.

Das Offlinepaket für Windows x64 enthält CPython, seine Abhängigkeiten und den
gepinnten KiraBridge-Quellstand. Zuerst das gesamte ZIP entpacken. Eine zusätzliche
Python-, Git- oder pip-Installation ist nicht erforderlich. Die Installation benötigt
keine Administratorrechte und ändert weder PowerShell-Richtlinie noch Registry.

## Install / Installieren

Run `Install.cmd` in the extracted package. The default root is
`%LOCALAPPDATA%\KiraBridge`. For a different root, use Command Prompt:

`Install.cmd` aus dem entpackten Paket starten. Standardziel ist
`%LOCALAPPDATA%\KiraBridge`. Für ein anderes Ziel in der Eingabeaufforderung:

```bat
Manage.cmd --root "C:\Users\Dirk\KiraBridge" install
"C:\Users\Dirk\KiraBridge\KiraBridge.cmd" status
"C:\Users\Dirk\KiraBridge\KiraBridge.cmd" run --help
```

The installed launcher always selects the active release and its bundled runtime.
Keep configuration and persistent files under `<root>\data`; update, rollback and
uninstall preserve that directory. Existing installations require an explicit update.

Der installierte Starter verwendet die aktive Version samt gebündelter Laufzeit.
Konfiguration und dauerhafte Daten unter `<root>\data` speichern. Update, Rollback und
Deinstallation erhalten diesen Ordner. Eine bestehende Installation wird nur durch
`update` ersetzt.

## Update and rollback / Aktualisieren und zurücksetzen

Extract the new package into a new directory, then run `Update.cmd` for the default
root, or use `Manage.cmd` with your existing root. Rollback changes application files;
it does not restore an old copy of user data. Stop owned running KiraBridge processes
before updating or removing their release files.

Das neue Paket in einen neuen Ordner entpacken. `Update.cmd` verwendet das Standardziel.
Für ein eigenes Ziel `Manage.cmd` verwenden. Rollback wechselt die Programmversion,
ohne neue Nutzerdaten durch alte Kopien zu ersetzen. Eigene laufende KiraBridge-Prozesse
vor Update oder Deinstallation beenden.

```bat
Manage.cmd --root "C:\Users\Dirk\KiraBridge" update
"C:\Users\Dirk\KiraBridge\KiraBridge.cmd" rollback
```

## Uninstall / Deinstallieren

Use `Uninstall.cmd` from an extracted package for the default root, or the explicit
command below. The external runtime avoids deleting the Python executable currently
running the uninstaller. User data remains available.

`Uninstall.cmd` aus einem entpackten Paket verwendet das Standardziel. Für ein eigenes
Ziel den folgenden Befehl verwenden. Die externe Laufzeit vermeidet das Löschen des
gerade laufenden Pythonprogramms. Nutzerdaten bleiben erhalten.

```bat
Manage.cmd --root "C:\Users\Dirk\KiraBridge" uninstall
```

## Build and provenance / Build und Herkunft

`scripts/build_windows_standalone.py` exports committed source, validates the supplied
runtime and records every packaged file in `provenance.json`. Native builds can use a
source archive only with its explicit SHA256 and full Git commit. The runtime's older
development installation is removed; a relative `.pth` binds isolated child Python
processes to the same release's `src`. No host `PYTHONPATH` is required.

Der Builder exportiert committed Quellcode und erfasst alle Paketdateien in
`provenance.json`. Native Builds aus einem Sourcearchiv benötigen dessen SHA256 und
den vollständigen Git-Commit. Eine ältere Entwicklungsinstallation in der gelieferten
Laufzeit wird entfernt. Eine relative `.pth` bindet auch isolierte Python-Unterprozesse
an `src` derselben Version. Ein gesetzter `PYTHONPATH` ist nicht nötig.

The native acceptance script checks installation into a path containing spaces,
installed CLI startup, unauthenticated rejection, authenticated MCP health, update,
rollback and uninstall, preserving data created after the update. It records module
paths and checks an isolated child import. GUI/input acceptance remains a separate
Windows capability check; this installer does not claim all macOS features.

Die native Abnahme prüft Installation in einem Pfad mit Leerzeichen, CLI-Start,
unautorisierte Ablehnung, authentifizierten MCP-Healthcheck, Update, Rollback und
Deinstallation einschließlich Datenerhalt nach dem Update. Modulpfade und isolierte
Unterprozessimporte werden geprüft. GUI- und Eingabeprüfungen bleiben eine getrennte
Windowsabnahme; das Paket behauptet keine vollständige macOS-Funktionsgleichheit.
