# KiraBridge · privater Release Candidate 0.6.0rc2

## Ergebnis

Echter privater GitHub-Entwurf, lesend bestätigt: [v0.6.0rc2](https://github.com/landjunge/KiraBridge/releases/tag/untagged-18d6efbfc90f73d90428),
`draft=true`, `prerelease=true`, Quellpin
`57bee99df829398102f8ab57c6dd845e3c8cf3aa`. Repository weiterhin privat.
Keine öffentliche Discussion, keine DNS-/Hostingänderung und keine Neueinrichtung
der gesunden Nutzerinstallation. Installierter Dienst bleibt0.5.2 mit dem
abgeschlossenen [Diagnoseausbau](DIAGNOSTICS-20261018.md).

Angehängt: je ein Startpaket für macOS15 Intel/Apple Silicon und Ubuntu24.04 x86_64,
Python-Wheel und Quellpaket, separate `LICENSE`, `SHA256SUMS`, Quell-/Prüfmanifest
und drei Plattformbelege. Lokal:
`/Users/landjunge/KiraBridge-release-20261018/dist/release-0.6.0rc2/`.
Eine Kopie unter dem bestehenden lesefreigegebenen Projektpfad liegt in
`/Users/landjunge/KiraBridge/dist/release-0.6.0rc2-57bee99/`.

Normale Installation: passendes Originalpaket prüfen und entpacken, darin
`sh install.sh`, Englisch `sh install.sh --language en`. Der Assistent führt
durch Voraussetzungen, Projektordner/Rechte, lokalen Benutzerdienst und den
wiederverwendeten ChatGPT-Einrichtungshelfer. Kontoschritte bleiben beim Nutzer;
Runtime-Schlüssel wird verdeckt eingegeben. Kein sudo und keine Shellprofiländerung.
[Vollständige Anleitung DE](INSTALL-DE.md) · [EN](INSTALL-EN.md), jeweils mit
Update, Wiederaufnahme, Erhalt bestehender Einrichtungen und Deinstallation ohne
stilles Löschen von Queue/Audit/Schlüsseln. Individuelle Entwicklerinstallationen
werden nicht automatisch in Release-Installationen umgewandelt.

## Tatsächliche Prüfungen

- Anwendung und Kompatibilität: [CI39126104619](https://github.com/landjunge/KiraBridge/actions/runs/39126104619),
  136Tests je macOS/Python3.11 und Ubuntu/Python3.11/3.13, Formatierung und Paketbau.
  Danach änderten sich ausschließlich Paket-/Prüfskripte, Releaseversion und
  Lizenz-/Dokumentationsmetadaten; kein erneuter unveränderter Gesamtlauf.
- Neuer Lizenzpaketstand: [CI39126731999](https://github.com/landjunge/KiraBridge/actions/runs/39126731999).
  Startbefehl mit `--prepare-only`, authentifizierter isolierter Dispatcher,
  konkrete Vorabprüfung mit Quellabgleich und Ablehnung beschädigter Pakete auf
  Apple Silicon und Ubuntu; dieselbe Probe lokal auf Intel. Keine persönlichen
  Dateien, Konten oder produktiven Dienste neu eingerichtet.
- Ein macOS-Job brach beim ersten Start vor der Bereitschaft ab; stderr war in
  dieser isolierten Probe verworfen. Ursache unbekannt. Ein einmaliger begrenzter
  Wiederholungslauf ausschließlich des fehlgeschlagenen Jobs bestand. Keine
  Behauptung dauerhafter Fehlerfreiheit; keine Taskausführung wiederholt.
- Lizenzdateien in Bundle, Payload, Wheel und separatem Asset bytegleich;
  Wheel-Metadaten `License-Expression=LicenseRef-Netzwerkpunkt-Personal-Use-1.0`.
  SHA-256 `3316d5eda60ac1fea355aa43d196feea3567384179b55ca88c8636c0322021ec`.
  Identisch zur aktuellen 4AllPass-LICENSE. GitHub-Assetdigests gegen lokale
  Dateien verglichen. Alte RC1-Pakete am Pin598bc1b bleiben unverändert und werden
  nicht nachträglich neu lizenziert.
- Isolierte Terminalbedienung mit Banner und Abbruch vor Dienstinstallation;
  Updateprüfung bei wartenden Tasks, fremde Launcher und vorhandene Tunnelprofile
  gezielt geprüft. Offizieller Tunnel-Client nur in temporärem Ordner geladen,
  Originalhash und `--version` geprüft; kein neues Konto oder Tunnel gestartet.

[Maschinenlesbarer Beleg](evidence/release-candidate-rc2-20261018.json).
Die bereits vom Nutzer bestätigte ChatGPT-Dateiabnahme
`chatgpt-file-verification-20261018-1311` bleibt bestehen (9117Bytes), ohne Wiederholung.

## Vor öffentlicher Freigabe offen

Die vom Betreiber übernommene individuelle Netzwerkpunkt Personal Use License1.0
ist jetzt enthalten. Deutsche Fassung maßgeblich; englische Übersetzung,
keine OSI-Standardlizenz und keine anwaltliche Prüfung. Rechte an gesonderten
Drittbestandteilen und historischen Fassungen bleiben bestehen.

Weiterhin nötig: ausdrückliche Freigabe genau dieses Veröffentlichungspakets;
Bedienabnahme auf frischer Benutzerinstallation einschließlich tatsächlicher
macOS-/Linux-Benutzerdienstintegration und neuer ChatGPT-Zielchat-Einrichtung;
Prüfung der Drittanbieterbedingungen und Wartungs-/Sicherheitsbewertung des für
Intel-macOS begrenzten cryptography48.0.1-Pins. Die automatische Konto-/Workspace-
Verfügbarkeit wird nicht behauptet. Public Release, Discussion und Subdomain
bleiben bis zur separaten Entscheidung zurückgestellt. Keine stabile1.0.
