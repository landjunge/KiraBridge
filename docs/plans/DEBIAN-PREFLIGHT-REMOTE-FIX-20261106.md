# Debian-Bestand und begrenzte Remote-Korrektur

06.11.2026 · `BIGPLAN-DEBIAN-PREFLIGHT-20261106-V1` und daraus
`BIGPLAN-REMOTE-RESERVATION-EVIDENCE-20261106-V1`. Codex/root koordiniert und
schreibt; Grok prüft unabhängig. Fortsetzung des bestehenden
[Remote-Vertikalschnitts](REMOTE-VERTICAL-SLICE-20261105.md), kein neues Produkt.
Basis `e9f4d8d53e8fbd23565c04dfe72bc6391c169a02`, Featurebranch
`fix/remote-reservation-evidence-20261106`. Finaler Commit und Übergabe stehen
im bestehenden ThreadDesk-Board und privaten Handoff.

## Tatsächlich gelesenes Debian

Der vorhandene SSH-Alias `netcup-daniel` war mit bestehendem Schlüssel und
gespeicherten Hostkeys erreichbar: BatchMode, StrictHostKeyChecking,
UpdateHostKeys aus, kein neuer Trust und keine automatische Wiederholung.
Alle Serverkommandos lasen ausschließlich Metadaten; keine sudo-/Rootshell,
Dateiübertragung, Installation, Konfiguration, Containeränderung oder Dienständerung.

| Beobachtung | Ergebnis und Grenze |
| --- | --- |
| System | Debian GNU/Linux 13 (trixie), x86_64, SSH-UID 1000 |
| Ressourcen zur Lesezeit | 8 CPUs, etwa 16 GiB RAM, etwa 8 GiB verfügbar, etwa 305 GB freier Rootplatz; keine Zusage späterer freier Kapazität |
| Systemdienste | Agent Authority Browser und zwei bestehende KiraBridge-GitHub-Actionsrunner aktiv; nicht verändert oder als Testkapazität benutzt |
| AA-Betrieb | `agent-authority-browser.service`, Benutzer/Gruppe `aa-browser`, laufender MainPID 1678, Arbeitsverzeichnis unter `/opt/agent-authority-browser/current` |
| AA-Quellpin | Geschütztes Arbeitsverzeichnis für den SSH-Benutzer nicht lesbar. Versions-/Sourceattestierung bleibt unbekannt; kein Rechtewechsel als Abkürzung |
| Container | Bestehende 4AllPass-Backend-/Web-/Caddy-/Postgres-/Rediscontainer über ausschließlich lesendes `docker ps` sichtbar |
| Netz | 80/443 durch die Caddy-Portabbildung der bestehenden 4AllPass-Container belegt; weitere beobachtete Ports 22/8787/8796. Kein TLS-/Login-/Gesundheitsnachweis aus einer bloßen Portliste |
| TD/KB-Server | Keine passenden Namen im gelesenen System-/User-Service- und Containerinventar. Das beweist keine Abwesenheit unbenannter Prozesse oder anderer Installationen |

Die erste Detailabfrage brach an einem `PermissionError` des geschützten
AA-Verzeichnisses ab. Die korrigierte reine Metadatenabfrage bewahrt diesen
Sourcefehler ausdrücklich und liefert die übrigen Werte. Originalfehler und
beide Receipts bleiben erhalten. Keine Container-Umgebungsvariablen,
Zugangsdaten oder privaten Hostadressen werden hier veröffentlicht.

Das ist ein echter lesender Debianzugriff, **kein** TD→KB→Agent-Auftrag auf
Debian, keine produktive Stagingfreigabe und keine Handyabnahme.

## Groks unabhängiger Beitrag

Der Nutzer beauftragte passende Modell-/Denkstufenwahl und aktive Grok-Mitarbeit.
Der vorhandene Router prüfte die aktuelle ThreadDesk-Matrixrevision 5, CLI-Build
und grok.com-Abonnementroute. Für die Prüfung von Rechte-/Geräte-/Wiederaufnahme-
grenzen wurden tatsächlich `--model grok-4.7 --effort xhigh` gesetzt, keine
globalen Defaults geändert. Nur Read/Glob/Grep, keine Bash-/Schreib-/MCP- oder
Serveraktionen und keine Unterdelegation im bestehenden geprüften Leseprofil.

Erster Review `bigplan-debian-review-20261106-v1`: tatsächlich ein Modellturn,
`end_turn`, Exit 0, drei gelieferte Quelldateipins vor/nach unverändert. Die CLI
meldet `grok-4.7-build`; die effektive Denkstufe ist nicht separat attestiert.
Die Modell-Selbstaussage, selbst keinen Router geschaltet zu haben, ersetzt
weder die tatsächlichen Startparameter noch die externe Quittung.

Die Ausführung war im eigenen sichtbaren Tab. Der alte Shelltab wurde vor
Eingabe als `visible_input_unknown` abgelehnt. Die reguläre Fensteranlage erzeugte
einen Tab, endete aber UNKNOWN bei der Shared-Host-Zuordnung. Dieser Originaltask
wurde nicht wiederholt. Derselbe angelegte Tab wurde anschließend frisch
eindeutig katalogisiert und als leer gelesen; Routerreceipt und passender
Grokprozess waren noch abwesend. Erst danach erfolgte der bestätigte Erststart.
Ergebnistext und Quittung wurden im selben Tab angezeigt. Keine anderen
Grok-/Codex-Sitzungen wurden dafür umgestellt oder unterbrochen.

Root prüfte die vier Hypothesen gegen vollständige Aufrufer und Tests:

- **Bestätigt:** Nach quittierter Reservierung wurde ein verlorener oder
  abgelehnter Readback als gewöhnlicher Fehler weitergegeben. `issued=null`
  oder eine Liste führten sogar zu `AttributeError`. Der Peer meldet diese
  Fälle jetzt als `remote_delivery_unknown`; eine bereits mögliche dauerhafte
  Reservierung wird dadurch nicht zu einer sicheren Ablehnung umgedeutet.
- **Bestätigt:** Bei der Executorbindung konnten auf beiden Seiten fehlende
  oder gleichartig ungültige Requesthashes gleich vergleichen. Ein tatsächlicher
  kanonischer Core-Fingerprint mit 64 kleinen Hexzeichen ist nun erforderlich.
- **Kein erforderlicher Relayumbau:** Grantwiderruf unmittelbar vor Submit
  stoppt nachweislich vor jeder Core-Aufgabe. Ein verstärkter Test stellt den
  Grant wieder her und beweist, dass derselbe Auftrag trotzdem am vorhandenen
  Reservierungsmarker ohne Submit stoppt. Die bekannte Ablehnung bleibt erhalten.
- **Bereits im Aufrufer geschützt:** `MCPClientPool.connect` lehnt URL-Userinfo,
  Query und Fragment ab und folgt keinen Redirects. Ein MCP-Endpunkt darf einen
  Pfad besitzen; er ist deshalb nicht derselbe Vertrag wie die reine TD-Origin.

## Änderung und gezielte Prüfung

Nur `HttpHandoffPeer` wurde im Produktcode geändert. Unabhängige normale
Lese-/HTTP-Ablehnungen vor einer Reservierung, Operatorentscheidungen,
TLS-/Geräte-/Grant-/Pfadprüfungen und Default-off-Profil bleiben erhalten.
Keine neue Queue, Grantquelle, Route oder automatische Wiederaufnahme.

Am Altcode scheiterten 14 neue Peer-Negativfälle und ein zusätzlicher tatsächlicher
lokaler TLS-/TD-/Core-Fall am relevanten Fehler. Die erste TLS-Ausführung konnte
mit dem zunächst gewählten Interpreter wegen fehlendem FastAPI nicht starten;
das wurde als Umgebungsfehler erhalten. Danach wurde genau die vorher dokumentierte
kombinierte vorhandene Testumgebung wiederverwendet, ohne Installation.

Nach der Korrektur: **47 bestandene Tests in 47,61 s, null Skips**, beide betroffenen
Remote-Testdateien. Verlorener Readback nach tatsächlicher TLS-Reservierung und
erneuter Aufruf desselben Envelopes erzeugen keine Core-Aufgabe und keinen
Agentenstart. Ruff, Format- und Diffprüfung bestanden. Agenten-/Operatoraufträge
bleiben deterministische lokale Fixtures; das ist keine Provider-/Windows-/
Debian-Ausführungs- oder mobile End-to-End-Abnahme.

Der gesonderte unabhängige Grok-Diffreview
`bigplan-remote-reservation-fix-review-20261106-v1` ist mit einem Modellturn,
`end_turn` und Exit 0 abgeschlossen: **keine blockierenden P1/P2-Befunde im
gelieferten Diff**. Root hat alle drei Code-/Testdateipins danach erneut geprüft;
keine Änderung während des Reviews. Native Sitzung
`01a1aea9-8f6f-7740-8fe0-2561eb1eb2f0`, angefordert wieder 4.7/xhigh,
CLI-Modellmeldung wieder 4.7-build, effektive Denkstufe nicht separat attestiert.
Grok hat den Quellstand geprüft, nicht die 47 Tests selbst erneut ausgeführt
und keine Installations-/Mobilefreigabe erteilt. Root übernimmt nur diese
belegten Aussagen. Quellkorrektur und lokaler Prüfpunkt sind damit abgeschlossen;
Integration, Installation und Liveabnahme bleiben getrennt.

## Nächster gesicherter Einstieg

Native Windows-Kandidatenphasen bleiben 0/6, ursprünglicher Payload179bb6f
unverändert; der angefragte Prozess-Override wurde nicht angewendet. Dieser neue
optionale Remote-Fix ist nicht in jenem eingefrorenen Payload. Vor einer späteren
Lieferung geeigneten Quellstand und passende neue native Bindung bewusst wählen,
alte Berichte nicht auf diese Änderung umbeschriften.

Für BP-DEBIAN-01/REMOTE-03 fehlen weiterhin ein ausdrücklich festgelegtes
Stagingprofil samt Betreiberpfaden/Rückweg, Gerätepairing und unabhängige
Operatorbindung sowie ein erlaubter tatsächlicher Agenten-/Handyweg. Vorhandene
4AllPass-/AA-Dienste oder deren Accounts verleihen keine KB-Ausführungsrechte.
Der separate lokale Koordinator bleibt unverändert; es wurde keine neue Karte
oder Serverausführung automatisch freigegeben. Die Koordination
`482f593429ad/c154c9769e17` meldet das fremde TD-Projektstartpaket M2 auf
`54624d8` und weist Planrevision/Wiedereinstieg M3 derselben TD-Sitzung zu
(`188ce4729a62/1efb9741ba1f`). Deren Worktree bleibt unberührt.

Quellcode, lokal getestet, installiert und live abgenommen bleiben getrennt.
Keine neue RC, kein Paket-/Server-/Mac-Deployment; READMEs/Downloads behaupten
deshalb keine neu verfügbare Produktfunktion.

Private Rohbelege, anonymisierter Reviewsnapshot, Router-/CLI-Quittungen,
Testergebnisse und Handoff:
`~/.local/share/kirabridge/backups/bigplan-debian-preflight-20261106-v1/`,
Korrekturbelege im Unterordner `remote-fix/`. Keine alten UNKNOWNs gelöscht.
