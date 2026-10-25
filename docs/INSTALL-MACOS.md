# Current RC17 review artifact / Aktuelles RC17-Prüfpaket

The copy command below selects **KiraBridge-macos-chatgpt-20261024b.tar.gz**, with its adjacent authenticated `.sha256` file. The embedded release.json pins
its exact source commit; the separate7725bc6 evidence remains historical.
This is a separately named private RC17 draft candidate from open PR32, not the
published RC14 and not the historical standard RC17/b54f462 assets. It is unsigned.
The base7725bc6 code passed actual Intel-macOS upgrade/data/rollback and Kira
paste/readback. The final b candidate adds the specifically tested legacy secret-error classification
and bounded launchctl bootstrap recovery. Its exact build and acceptance are recorded
in the [current continuation](RC17-RESUME-20261025.md); historical native proof remains
explicitly pinned to7725bc6.
GitHub Actions has not started due account billing; no merge/publication claimed.

Der Befehl wählt genau diesen privaten, separat benannten RC17-Kandidaten aus PR32.
Intel-macOS ist tatsächlich geprüft; Apple Silicon ist nicht ausgeführt. Die
aktuelle produktive Berechtigung wurde auf ausdrücklichen Nutzerauftrag nur für
ChatGPT vervollständigt: alle42 Operationen automatisch, andere Identitäten und
Zugangsdaten unverändert. Details: [Arbeitsnachweis](CHATGPT-BLOCKER-AUDIT-20261024.md).
Die Ein-Zeilen-Kette wurde aus dem authentifizierten Entwurf mit isolierten Pfaden
und `--service none` ausgeführt; echte launchd-Prüfungen liefen separat mit denselben
Paketbytes. Ein nachgelagerter Testpfad-Assert wurde berichtigt, ohne Installation
zu wiederholen. Versions-/Grant-/SHA-Nachprüfungen sind bestanden.

# macOS installation / Installation

**RC17 remains unpublished. The explicitly authorized operator upgrade, native paste/readback and full ChatGPT grant are verified for7725bc6; GitHub Actions remains blocked before execution by account billing. Additional review was waived.**

**RC17 ist ein unveröffentlichter Kandidat. Produktive Installation und reine native Eingabe sind für7725bc6 belegt; das Folgepaket erfordert seine eigene Prüfung. Pflicht-CI offen, zusätzliche Review auf Nutzeranweisung entfallen.**

## Deutsch

**Veröffentlicht ist [v0.8.0rc14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14).
RC17 ist ein unveröffentlichter Kandidat. Der Release-Entwurf dient ausschließlich berechtigten Reviewern; Freigabe erst nach bestandenen erforderlichen Prüfungen. Zusätzliche Review wurde abgewählt.**

Voraussetzungen: normales Benutzerkonto ohne sudo, macOS 15 (Intel x86_64 oder
Apple Silicon arm64), Python **3.11**, **uv 0.11.6**, Internet zu PyPI und Zugriff
auf dieses private GitHub-Repository. macOS 26 wird vom Einstieg akzeptiert, ist
hier aber nicht abgenommen. Ein iMac 2015 mit älterem macOS ist damit noch nicht
unterstützt; das Hardwaremodell allein belegt keine OS-Kompatibilität. Apple
Silicon wird durch dieselbe Architektur-unabhängige Wheel-/Lock-Kombination
berücksichtigt; ein echter arm64-Test bleibt notwendig.

Python und uv vorher über einen vertrauenswürdigen Paketmanager bereitstellen,
z. B. `brew install python@3.11 uv`; danach `python3.11 --version` und
`uv --version` prüfen. Der Installer verlangt die dokumentierte uv-Version und
installiert weder Compiler noch Homebrew oder Python automatisch. Für private
Downloads GitHub CLI (`brew install gh`) installieren, mit `gh auth login`
anmelden und mit `gh repo view landjunge/KiraBridge` den Zugriff prüfen.
Keine Tokens in Befehle oder Logs kopieren.

Das Paket `KiraBridge-macos-chatgpt-20261024b.tar.gz` enthält Installer, Wheel, Quellstand,
`uv.lock`, Lizenz, Anleitung und Releasehinweise. Nach Bezug eines freigegebenen
Pakets samt `KiraBridge-macos-chatgpt-20261024b.tar.gz.sha256` in einen neuen leeren Ordner:
`shasum -a 256 -c KiraBridge-macos-chatgpt-20261024b.tar.gz.sha256` prüfen und mit
`tar -xzf KiraBridge-macos-chatgpt-20261024b.tar.gz` entpacken. Nur ausführen, wenn die Prüfung
besteht. Prüfsummen vom selben authentifizierten Release schützen vor
Beschädigung; sie ersetzen keine unabhängige Herausgebersignatur.

**Für berechtigte Reviewer des RC17-Release-Entwurfs: Installation und Update
mit EINEM Befehl (angemeldete GitHub CLI erforderlich).** Der Befehl lädt Paket und zugehörige Prüfsumme authentifiziert und prüft SHA-256.
`"$@"` reicht optionale Argumente weiter; beim normalen Einfügen sind diese leer.
Dies ist ausschließlich der RC17-Reviewbefehl, tatsächlich mit isolierten Pfaden und eigener launchd-Testkennung geprüft:


```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'KiraBridge-macos-chatgpt-20261024b.tar.gz*' -D "$d" && (cd "$d" && shasum -a 256 -c KiraBridge-macos-chatgpt-20261024b.tar.gz.sha256 && tar -xzf KiraBridge-macos-chatgpt-20261024b.tar.gz && sh KiraBridge/install.sh --full-access "$@")
```

Erstinstallation: legt ausschließlich Benutzerdateien an. Dieser ausdrücklich
freigegebene `--full-access`-Befehl vergibt automatische vollständige Datei-/Befehlsrechte.
Bestehende Installationen behalten ihre eigene Konfiguration und Berechtigungen.
Ein Vollzugriffs-Label ersetzt weder installierte Agenten noch Providerkonten oder
fehlende Empfängerschnittstellen.
Konfiguration und geheime Zugangsdaten: `~/.config/kirabridge/`; Laufzeiten,
Backups und Logs: `~/.local/share/kirabridge/install/`. Der erste Start bindet
127.0.0.1:8765. Ein bereits belegter Port führt zum Fehler und Rückfall.
Danach [ChatGPT verbinden](CHATGPT.md), Agenten separat installieren/anmelden.
Eine lokale Statusprüfung belegt keinen ChatGPT-, Live- oder Handy-Aufruf.

Update: denselben Befehl aus dem neuen geprüften Paket wiederholen. Konfiguration,
Zugangsdaten, Datenbank und Nutzerdateien bleiben erhalten. Aktive Aufgaben,
Empfänger- oder Teamjobs blockieren die Umschaltung. Fremde Launcher, abweichende
Dienste, Symlinks und unsichere Berechtigungen werden mit Fehler abgelehnt;
Berechtigungen werden nicht automatisch verändert. Individuelle Altinstallationen
können eine geprüfte manuelle Migration benötigen. Keine Lösch- oder chmod-Reparatur
auf Verdacht durchführen. Alte Versionsverzeichnisse bleiben als Rückweg erhalten.

Der **launchd-Benutzerdienst läuft nach Schließen von Terminal oder Browser weiter**.
Er startet bei der Anmeldung und nach einem Prozessfehler erneut. Abmelden,
Herunterfahren oder Ruhezustand sind davon getrennt; es wird kein Systemdienst
installiert. Vorhandene Dienstoptionen bleiben beim Update erhalten.

Status und Version: `~/.local/bin/kirabridge status` zeigt die Version des wirklich
antwortenden Dienstes. `python3.11 KiraBridge/installer/install.py status` zeigt
zusätzlich den installierten Commit. Neustart: erst Aufträge beenden, dann
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge` und erneut Status prüfen.
Die erste Installation nimmt keine PATH-Änderung vor; bei „command not found“ den
vollständigen Launcherpfad verwenden.

Fehler: Exitcode und `FEHLER:` beachten; Logs unter
`~/.local/share/kirabridge/install/logs/` prüfen. Netzwerkfehler: denselben Befehl
wiederholen. Falsche Prüfsumme: abbrechen und Originalpaket erneut beziehen.
Fehlende Python-/uv-Version: Voraussetzung korrigieren. Belegte 8765: Besitzer
prüfen, keine fremden Prozesse stoppen. Fehlgeschlagene Aktivierung versucht
automatisch den gesicherten alten Launcher und Dienst wiederherzustellen.
Expliziter Rückfall: `python3.11 KiraBridge/installer/install.py rollback`.
Dabei werden aktuelle Konfiguration, Zugangsdaten und Ergebnisdaten nicht durch
alte Sicherungen überschrieben. Ein veränderter Launcher/Dienst blockiert auch
Rollback; dann Transaktionsdatei und Backup manuell prüfen.

**Keine Apple-Signierung oder Notarisierung.** Das Paket enthält keine neue
signierte `.app` und benötigt keine pauschale Deaktivierung von Gatekeeper.
Abhängigkeiten werden passend zur Architektur binär aus dem Hash-Lock geladen;
das Paket ist kein Offline-Installer. Für Intel bleibt cryptography unter 49,
um die kompatiblen macOS-Wheels zu verwenden.

## English

The published release is [v0.8.0rc14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14),
which only has a wheel. RC17 remains unpublished until CI and review pass.

Requirements: a regular user account, macOS 15, Intel x86_64 or Apple Silicon
arm64, Python **3.11**, **uv 0.11.6**, Internet access to PyPI, and repository
access. macOS 26 is accepted but unverified. Older macOS on a 2015 iMac is not
validated. Apple Silicon needs an actual arm64 acceptance run. Install tools
from a trusted package manager, e.g. `brew install python@3.11 uv gh`, then check
versions. For private releases use `gh auth login` and verify repository access;
never put access tokens in commands. The installer does not install Python,
Homebrew, compilers or change permissions.

Download the approved bundle and its `.sha256` file into a new empty directory,
verify with `shasum -a 256 -c KiraBridge-macos-chatgpt-20261024b.tar.gz.sha256`, then extract using
`tar -xzf KiraBridge-macos-chatgpt-20261024b.tar.gz`. Authorized draft reviewers can run the highlighted command above for both
installation and updates; it authenticates the download and verifies the archive before execution.
After manual extraction, the equivalent local entrypoint is `sh KiraBridge/install.sh`. A checksum obtained through the same authenticated
release detects corruption; it is not an independent publisher signature.

This explicitly authorized `--full-access` command creates automatic full filesystem/
command grants on fresh installations. Existing policies remain unchanged. Agent,
provider and receiver prerequisites still need their actual setup. Config and credentials live under
`~/.config/kirabridge`; versioned runtimes, logs and backups under
`~/.local/share/kirabridge/install`. Updates preserve configuration, credentials,
database and user files, refuse active tasks or receiver/team jobs, and preserve
foreign services/launchers. Custom legacy setups may require manual migration.

The launchd user service **continues running after Terminal or browser windows
close**. It starts at login and recovers from process failure. Logout, sleep and
shutdown are separate conditions. Existing launchd options are preserved.

Use `~/.local/bin/kirabridge status` for the responding service's version, and
`python3.11 KiraBridge/installer/install.py status` for the installed commit.
After tasks finish, restart with
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge`, then check status.
No PATH changes are made. For errors inspect `FEHLER:`, exit status and the logs
under `~/.local/share/kirabridge/install/logs/`. Retry network failures; reject
checksum mismatches. Do not stop unrelated processes if port 8765 is busy.
Failed activation attempts automatic recovery. Explicit rollback:
`python3.11 KiraBridge/installer/install.py rollback`; this restores launcher and
service, preserving current configuration, credentials and new results.

This is a network installer, **without Apple signing or notarization**, and
contains no newly signed native app. Do not disable Gatekeeper globally.
Connect ChatGPT and sign in to coding assistants separately. Local health does
not prove mobile, voice or end-to-end ChatGPT acceptance.

Optional file transfer setup / optionale Dateiübertragung: [FILE-TRANSFER.md](FILE-TRANSFER.md).
It stays disabled on existing installations; existing permissions are preserved.
