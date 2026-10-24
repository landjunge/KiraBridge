# KiraBridge 0.6.0: versionierte Installation und Rückweg

Status: zur sichtbaren Installation vorbereitet. Die Produktivinstallation auf
 diesem Mac wird durch diese Vorbereitung **nicht** aktiviert. Kira soll den
 untenstehenden Befehl anschließend im selben sichtbaren Terminal ausführen.
 Kein sudo, kein Force-Push, kein neuer Tunnel und keine Zugangsdaten im Repository.

## Voraussetzungen und echter Startbefehl

Python 3.11+, Git und uv. Auf diesem Intel-Mac werden mit dem vorhandenen Lockfile
cryptography-Abhängigkeiten gebaut: Rust/Cargo, Xcode-Compilerwerkzeuge, pkg-config
und OpenSSL sind hier bereits vorhanden und der Quellcodebau wurde tatsächlich
geprüft. Auf Macs mit passendem Wheel entfällt dieser Build. Der Installer installiert
keine Systempakete und öffnet keine pauschalen Rechtefreigaben. Der erste Build kann
mehrere Minuten dauern; jeder Unterbefehl ist auf zehn Minuten begrenzt. Fortschritt
und echte Fehler werden direkt ausgegeben.

Für diesen vorhandenen Checkout (der endgültige Commit wird in der Abschlussmeldung
zusätzlich ausgeschrieben):

```sh
/Users/landjunge/KiraBridge/.venv/bin/python /Users/landjunge/KiraBridge/installer/install.py install --repo /Users/landjunge/KiraBridge --ref "$(git -C /Users/landjunge/KiraBridge rev-parse HEAD)" --full-access
```

`--ref` akzeptiert ausschließlich einen vollständigen Git-Commit. Der Installer
verwendet `git archive`, kopiert also **keine** ungesicherten Arbeitskopieänderungen
oder lokalen Geheimnisse in das Versionspaket. In einem neuen Checkout kann Python
3.11+ statt des oben vorhandenen Bootstrap-Interpreters verwendet werden.

## Was der Installer tut

1. Installiert den exakten Commit mit `uv sync --frozen --no-dev --no-editable`
   nach `~/.local/share/kirabridge/install/releases/<version>-<commit>/source/.venv`.
   Das Hauptpaket benutzt weiterhin MCP 1.30.0; der optionale MCP-2-Events-Adapter
   hat ein eigenes Lockfile. Der bestehende Interpreter wird nicht umgebaut.
2. Übernimmt vorhandene TOML-Konfiguration, Tokens, Agentenprofile und volle
   Datei-/Terminalrechte bytegleich. Die bestehende Konfiguration wird auch dann
   nicht automatisch erweitert, wenn sie weniger Rechte enthält. `--full-access`
   autorisiert nur die Erstellung einer **neuen** Konfiguration, falls keine
   existiert. Neue Konfigurationen erhalten lokale und ChatGPT-Identitäten mit
   eigenen Tokens, Vollzugriffs-Policy und automatischem Modus. Providerprofile und
   Kontoverbindungen werden dabei nicht erfunden oder kostenpflichtig aufgerufen.
3. Sichert vorherigen Launcher, Dienstdefinition, Konfiguration, Zugangsdaten und
   einen konsistenten SQLite-Snapshot privat. Der Rückweg wird vor der Umschaltung
   im Terminal genannt. Eine Installersperre verhindert doppelte Installationen.
4. Prüft unter `BEGIN IMMEDIATE` 0 aktive Tasks und 0 Empfängerjobs. Bei belegter
   Bridge beendet er sich mit **BUSY** und schaltet nichts um. Er beendet keine
   beobachteten Codex-/Grok-Prozesse. Nur der eindeutig erkannte eigene launchd-Dienst
   darf umgeschaltet werden. Ein außerhalb dieses Dienstes laufendes Backend wird
   nicht übernommen.
5. Schaltet `~/.local/bin/kirabridge` und den bekannten Benutzer-LaunchAgent
   `com.kirabridge.bridge` um. Prüft Version, Authentifizierung, Konfigurationshash
   und Dispatcher-Status. Bei Startfehler versucht er den Rückweg unter erneuter
   Leerlaufprüfung. Beginnt zwischenzeitlich ein Auftrag, wird dieser nicht dafür
   abgebrochen. Der Transaktionsbeleg bleibt für die kontrollierte Fortsetzung da.

Der native Tunnel, dessen Profil, vorhandene ChatGPT-Verbindung und der getrennte
Events-Sender werden nicht neu konfiguriert oder neu gestartet. Ein kurzer Ausfall
des Bridge-Backends während der Umschaltung ist möglich. Bestehende externe
Agentenarbeiten laufen weiter. Alte Versionsverzeichnisse werden nicht automatisch
gelöscht. Ein abgebrochener Paketbau verändert keine aktive Version; ein unvollständiges
Versionsverzeichnis wird zur Prüfung erhalten und nicht blind überschrieben.

Der bisherige bearbeitbare 0.5.2-Quellstand und seine virtuelle Umgebung bleiben
auf diesem Mac erhalten. Die 0.6.0-Versionsdateien wurden für Commit/Paket isoliert
vorbereitet, damit ein vorheriger LaunchAgent weiterhin seinen alten Quellstand
starten kann. Nach dem Commit sind deshalb dort bewusste Unterschiede zwischen
Arbeitskopie und versioniertem Stand möglich. Keine Arbeitskopie bereinigen.

## Status und Rückkehr zur vorherigen Version

Nach der sichtbaren Installation:

```sh
/Users/landjunge/.local/bin/kirabridge status
/Users/landjunge/KiraBridge/.venv/bin/python /Users/landjunge/KiraBridge/installer/install.py status
```

Erwartet: Dienstversion 0.6.0, `dispatcher_active=true`, `approval_mode=automatic`
und weiterhin die vorhandene Authentifizierung. Die tatsächlichen Rechte können
über `policy_inspect` im MCP-Anschluss geprüft werden.

Rückkehr ausschließlich im erneut geprüften Leerlauf:

```sh
/Users/landjunge/KiraBridge/.venv/bin/python /Users/landjunge/KiraBridge/installer/install.py rollback
```

Der vorherige Launcher und die vorherige Dienstdefinition werden exakt restauriert;
bei vorher laufendem Dienst wird dessen Version wieder geprüft. Konfiguration,
Zugangsdaten und Datenbank werden **nicht** aus dem Backup zurückgespielt: neu
entstandene Ergebnisse bleiben erhalten. Nachträglich veränderte installierte
Launcher-/Dienstdefinitionen werden nicht überschrieben. Die getestete Migration
fügt nur Completion-Tabellen hinzu; der ältere 0.5.2-Code kann die Daten weiterhin
lesen. Kein allgemeiner Rollback zu beliebigen zukünftigen Schemata wird versprochen.
Bei einer ersten Neuinstallation ohne Vorgänger entfernt der Rückweg den neuen
Launcher/Dienst, erhält aber Konfiguration, Zugangsdaten und Ergebnisse.

## Datei-/Terminalzugriff ohne Events

`task_request`, `task_submit`, `action_request` und `action_submit` benötigen kein
Events-Abonnement. Ergebnisse werden per `task_get`/`task_events` abgerufen.
`read_query` liefert autorisierte begrenzte Leseantworten direkt. Der dauerhafte
Completion-Consumer und der optionale Events-Adapter bleiben davon getrennt.

Eine alte ChatGPT-Werkzeugbindung kann weiter das frühere Feld
`completion_subscription` fordern; dort bedeutet der leere Root-Wert `""` explizit
**kein** Abonnement. Für neue Werkzeuge braucht der Host seinen Metadatenrefresh;
der Installer kann den ChatGPT-Cache nicht löschen und behauptet das nicht.
Eine frische lokale Neuinstallation verbindet ChatGPT noch nicht mit einem Konto.
Die vorhandene Kontoverbindung auf diesem Mac wird erhalten.

Der Test `chat-events-receipt-20261019-01` bleibt gesperrt, bis der ursprüngliche
Chat eine echte bestätigte Subscription erhält. Kein simuliertes Host-Ereignis,
kein Codex-/Grok-Auftrag und keine automatische Chat-Zustellung gehören zur
Installationsprüfung. Für beliebige GUI-Terminals wird keine Sitzungssteuerung
behauptet; gezielter tmux-Zugriff und Bridge-eigene Prozesse behalten ihre bisherigen
Zuordnungen und Zugriffskontrollen.

## Echte Systemdialoge und Abnahmegrenze

Für den vorbereiteten Upgrade auf diesem Mac sind keine neuen Administrator-,
Schlüsselbund- oder Browserdialoge erforderlich. Vorhandene lokale Token-Dateien
werden weiterverwendet. macOS kann einen Hinweis zu einem Hintergrundobjekt zeigen;
falls es den Benutzer-LaunchAgent tatsächlich blockiert, wird dies als Startfehler
sichtbar. Der Installer umgeht diese Sperre nicht. Für spätere Zugriffe auf durch
macOS geschützte Ordner oder Automation können echte macOS-Freigaben erforderlich
sein; Vollzugriffs-Policy ersetzt keine Betriebssystemfreigabe. Die temporären
Installationsprüfungen verlangen solche Freigaben nicht.

Die Tests verwenden echte Pakete, private Testpräfixe und authentifizierte
HTTP-Backends auf zufälligen Ports. Die echte Produktiv-Umschaltung in launchd bleibt
bis zum von Kira sichtbaren Start ausstehend. Der Fehlerrückweg von launchd wird
zusätzlich deterministisch getestet und als solcher ausgewiesen.

## Vorbereitungsnachweise vom 19.10.2026

[Isolierte Installation/Upgrade/Rollback](../examples/installation/run-20261019-01/evidence.json),
[separater Neuinstallationsstart](../examples/installation/run-20261019-01/fresh-start-evidence.json),
[224 bestandene Tests am exportierten Paketstand](../examples/installation/run-20261019-01/suite.json),
[Wheel-Prüfung](../examples/installation/run-20261019-01/wheel.json) und
[erhaltener Produktivstand](../examples/installation/run-20261019-01/production-preserved.json).

Die Belege nennen den temporären lokalen Testcommit. Die Laufzeitdateien im Wheel
wurden byteweise mit dem vorgemerkten Release verglichen;
[Dateihashes](../examples/installation/run-20261019-01/runtime-source-manifest.json).
Der später ausgegebene endgültige Installationsbefehl pinnt den gepushten Commit.
Der erste Paketexport hatte eine fehlende historische Testnachweisdatei; sie wurde
ergänzt und der vollständige korrigierte Lauf bestand 224 Tests in 73,62 Sekunden.
Der launchd-Fehlerrückweg ist ein expliziter deterministischer Test, keine Behauptung
einer bereits erfolgten Produktivinstallation.
