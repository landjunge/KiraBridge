# KiraBridge 0.8.0rc12

## Deutsch

Dieses Vorabrelease paketiert die bereits auf dem Betreiber-Mac aktivierten
Receiver-Reparaturen aus `41f4b891a77abd3635738d10a6c38b66efc9ff8d` unter einer
eindeutigen neuen Versionsnummer. Die Laufzeitlogik bleibt gegenüber diesem
geprüften Stand unverändert. Es ist noch keine allgemeine stabile 0.8.0-Freigabe.

### Was wurde behoben?

- Ein belegter Empfänger blockiert andere Empfänger nicht mehr; Aufträge an
  dasselbe Terminal bleiben geordnet.
- Verbindungsfehler vor der Übergabe hinterlassen einen sichtbaren Grund und
  haben eine begrenzte Wiederholung statt einer stillen Endlosschleife.
- Ein voller Gesprächsverlauf lässt die abschließende Antwort eines bereits
  angenommenen Auftrags weiterhin zu.
- Wartezustände erhalten die ursprüngliche Zeitgrenze. Ein Fehler in einem
  Empfänger beendet nicht die Arbeit anderer Empfänger.
- Der ausdrücklich angeforderte Stopp bleibt erhalten, bis wieder gestartet wird.

Der frühere Mac-Nachweis umfasst 941 Tests und die Aktivierung der Reparaturen.
Die tatsächliche Kira→Codex→Kira-Übergabe wurde getrennt bestätigt. Diese Belege
stehen in `docs/evidence/receiver-resilience-mac-20261020.json`; sie ersetzen
keinen Installationstest des neuen Pakets auf einem fremden Rechner.

### Paket und Installation

Das Runtime-Archiv enthält das Python-Wheel, Quellpaket, den gepinnten Quellstand
als Git-Bundle, Installer, Lizenz, Prüfsummen und `BUILD-INFO.json`.
Es enthält keine Konten, Schlüssel, Betreiberkonfiguration oder Arbeitsdaten.
Benötigt werden Python 3.11+, Git und uv. Abhängigkeiten werden exakt nach
`uv.lock` installiert; dafür ist beim ersten Aufbau Internetzugang erforderlich.
Der Quellstand selbst liegt vollständig im Paket, ein GitHub-Login ist unnötig.

Archiv entpacken, in den Paketordner wechseln und zunächst nur vorbereiten:

```sh
python3 install.py prepare
```

Das baut eine eigene Version auf und lässt einen bestehenden Dienst weiterlaufen.
Für eine anschließend ausdrücklich gewünschte Installation:

```sh
python3 install.py install
```

Bei einer ganz neuen Konfiguration erfordert der vorhandene Installer die
bewusste Vollfreigabe `--full-access`. Bereits vorhandene Rechte werden erhalten.
Aktive Aufgaben verhindern den Versionswechsel; sie werden nicht abgebrochen.
Auf macOS verwendet der Installer launchd. Auf Linux startet er keinen Dienst
automatisch; dort `--service none` verwenden und den Dienst getrennt einrichten.

Status und kontrollierter Rückweg:

```sh
python3 install.py status
python3 install.py rollback
```

Der Rückweg ersetzt keine Datenbank durch eine alte Kopie. Die Installation
verbindet weder Anbieter-Konten noch richtet sie einen öffentlichen Tunnel ein.
Die bestehende native macOS-Begleitapp ist kein Bestandteil dieses Runtime-Pakets;
ihre Quellen sind im Bundle enthalten und können auf macOS gebaut werden.
Windows-Desktopsteuerung und physische Handy-/Sprachwiedergabe sind hier nicht
als abgenommen ausgewiesen. Das Repository bleibt privat; die Lizenz bleibt gleich.

`SHA256SUMS` und `BUILD-INFO.json` ordnen die Dateien dem Commit zu und erkennen
Beschädigungen. Die Herkunft wird über den vertrauenswürdigen Release-Bezug
geprüft; eine Prüfsumme allein ist keine Herausgebersignatur.

## English

This release candidate packages the already activated receiver fixes under a
distinct version. Runtime logic is unchanged from the pinned reviewed source;
this is not a general stable-release claim. The archive contains a wheel, source
distribution, a self-contained Git source bundle, installer, license and hashes.
No operator configuration, credentials or work data are included.

Requirements: Python 3.11+, Git and uv. Run `python3 install.py prepare` first;
this does not switch the running service. Use `python3 install.py install` only
when activation is intended. New configurations require explicit `--full-access`;
existing policies are preserved. Busy queues prevent switching. macOS uses
launchd; Linux service setup is separate. `status` and `rollback` use the existing
guarded installer. Provider login/tunnels and a native companion build remain
separate. The repository and license remain unchanged.
