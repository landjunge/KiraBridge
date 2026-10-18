# KiraBridge installieren · 0.6.0rc1

**Privater Release Candidate zur Abnahme. Noch keine öffentliche Installation oder
endgültige Lizenz.** Die spätere Projektseite `kirabridge.netzwerkpunkt.de` ist
geplant. Keine DNS-/Hostingfreigabe ist daraus abzuleiten.

KiraBridge ist speziell für Vibe Coding entwickelt: Du besprichst mit ChatGPT,
was gebaut oder geändert werden soll; ChatGPT übergibt Aufträge an Codex oder
Grok auf deinem Rechner. Beide können mit eingerichteten Berechtigungen am selben
Projekt arbeiten. Weitere CLI-Anbindungen sind geplant.

## Normaler Schnellstart

Du brauchst das freigegebene Originalpaket für deinen Rechner. Dieser RC enthält
Pakete für **macOS15 Intel x86_64** und **Ubuntu24.04 x86_64 mit systemd-Benutzersitzung**.
Windows, Apple Silicon, andere Distributionen und Server ohne Benutzersitzung
haben damit keinen vollständigen Installationsnachweis. Netzwerkzugriff auf
GitHub, PyPI und die von uv verwendete Python-Distribution wird benötigt.
Codex/Grok müssen für Agentenaufträge separat installiert und angemeldet sein;
die Bridge erstellt keine Konten und übernimmt keine bestehenden interaktiven
Sitzungen. CLI-Erkennung ist kein Login-/Modell-Funktionstest.

1. SHA-256 des Archivs gegen die mit der Freigabe bereitgestellte `SHA256SUMS`
   prüfen (`shasum -a 256 DATEI.tar.gz` auf macOS, `sha256sum DATEI.tar.gz` auf Linux).
   Eine Prüfsumme allein ist keine Signatur oder unabhängige Herkunftsgarantie.
2. Archiv entpacken, im Terminal den entpackten Ordner öffnen. Dann **ein Startbefehl**:

   ```sh
   sh install.sh
   ```

Der Assistent erkennt Voraussetzungen, beschafft nach Zustimmung eine gepinnte
Benutzerlaufzeit und führt durch lokale Einrichtung und ChatGPT-Anbindung.
Python- oder Paketmanagerkenntnisse sind für diesen Weg nicht erforderlich.
Keine Administratorrechte und keine `sudo`-Abfrage. Die Installation benutzt
uv0.11.6 (Originaldownload mit eingebettetem SHA-256), Python3.11.15 und die
gehashten Abhängigkeiten aus `uv.lock`. Bei vorhandenem passenden uv wird es
wiederverwendet. Downloads sind keine Offlineinstallation.

Wähle den konkreten Projektordner. Neue Zugänge bleiben im Modus **manual**:
Anfragen werden erst nach lokaler Freigabe ausgeführt. Der Assistent nennt den
Umfang vor der Erstellung und vor der ChatGPT-Rechteübernahme. Er erweitert keine
vorhandene Policy. Die Programm-/Ordnerfreigaben sind keine Betriebssystem-Sandbox;
ein erlaubter Interpreter oder Agent besitzt weiterhin die Rechte des Benutzers.

Programmstände liegen versioniert unter `~/.local/share/kirabridge/releases/`;
der eigene Befehl unter `~/.local/bin/kirabridge`. Falls dieser Ordner nicht im
PATH ist, denselben Befehl mit `~/.local/bin/kirabridge` aufrufen. Konfiguration
und separate Schlüssel: `~/.config/kirabridge/` (0600-Dateien). Daten, Queue und
Audit: `~/.local/share/kirabridge/` (0700). Es wird keine Shell-Konfiguration geändert.

## ChatGPT im selben Ablauf

Der Assistent verwendet den vorhandenen Weg `kirabridge chatgpt setup` weiter.
Ein fehlender offizieller Tunnel-Client kann nach Zustimmung vom Originalanbieter
geladen und gegen den eingebetteten Hash geprüft werden. Bestehende Clients
werden nicht ersetzt. Andere Versionen: [offizielle Releases](https://github.com/openai/tunnel-client/releases/latest).

Kontoschritte führst du selbst auf den angezeigten offiziellen Seiten aus.
Benötigt wird ein **eingeschränkter Tunnel-Runtime-Schlüssel**; ein normaler
OpenAI-API-Key oder Codex-Login reicht nicht. Eingabe erfolgt verdeckt im lokalen
Terminal, Speicherung separat mit0600; nicht in Befehle, Logs oder Chats kopieren.
Die tatsächlichen Kontoberechtigungen und eventuelle Kosten musst du im Zielkonto
prüfen. Nicht jeder ChatGPT-Workspace stellt diese Verbindung bereit.
[Offizieller Tunnelweg und Berechtigungen](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Der Abschluss unterscheidet:

- Lokaler Dispatcher antwortet authentifiziert.
- Tunnelprozess/Health/Readiness sind bereit.
- **Aus dem vorgesehenen Chat** `bridge_health` aufrufen und Ergebnis prüfen.
  Erst der echte Chat-Aufruf belegt diesen Zugang; die Bridge erfindet ihn nicht.
  Für einen konkreten Arbeitsablauf anschließend `bridge_readiness` mit den
  benötigten Funktionen/Pfaden nutzen. Bei manueller Taskfreigabe lokal
  `~/.local/bin/kirabridge approvals` öffnen.

Die ChatGPT-Einrichtung legt kein öffentliches Plugin an. Ein unvollständiges
oder nicht bereites bestehendes Tunnelprofil wird erhalten und mit nächstem
Prüfschritt gemeldet, statt durch neue Schlüssel ersetzt zu werden. Ein
Verbindungsfehler ist kein Anlass, unklare Schreibaufträge neu einzureichen.

## Erneuter Aufruf und Update

Denselben Startbefehl erneut verwenden. Vorhandene Konfiguration, Schlüssel,
Berechtigungen und Daten werden erkannt und erhalten. Die gesunde Installation
auf dem Entwickler-Mac wird dafür nicht neu eingerichtet.

Bei einer **verwalteten Release-Installation**: neues Originalpaket prüfen,
entpacken und `sh install.sh` starten. Vor dem Umschalten müssen alle aktiven und
wartenden Tasks/Empfängerjobs abgeschlossen sein. Der Assistent verweigert das
Update sonst. Er ersetzt nur seinen hashgeprüften Launcher, sichert den vorherigen
Launcher und behält frühere Programmordner. Schema-/Datenrücksicherungen erfolgen
nicht automatisch. Bereits laufende fremde CLI-Sitzungen und Tunnel werden nicht
beendet. Ein vorhandener Proxy kann daher noch die bisherige Clientversion nutzen;
bei geplanter eigener Tunnel-Wiederverbindung weiterhin ursprüngliche Task-IDs
lesen und unklare Schreibaufträge nicht wiederholen.

Individuelle/Entwicklerinstallationen ohne `installation.json` werden **nicht**
automatisch umgestellt. Sie behalten ihren bisherigen Dienst-/Updateweg; die neue
Vorbereitung meldet diesen Zustand. Vor manueller Migration Konfiguration sichern,
Queues leeren, bisherigen Dienstweg dokumentieren und explizit umstellen. Keine
gesunde bestehende Einrichtung allein für den Assistenten überschreiben.

## Beenden und deinstallieren, Daten erhalten

Zuerst eigene offenen Arbeiten abschließen und `kirabridge tasks`/`pending`
prüfen; bei laufenden Empfängerjobs auch `kirabridge message status`. Eigene
Tunnel-Runtime, falls eingerichtet, mit ihrem vorhandenen `tunnel-client runtimes
stop kirabridge` beenden. Keine fremde Sitzung stoppen, keinen Remote-Tunnel oder
Schlüssel löschen. Unter macOS den eigenen Benutzerdienst entladen:

```sh
launchctl bootout "gui/$(id -u)/com.kirabridge.bridge"
```

Unter Linux: `systemctl --user disable --now kirabridge.service`. Falls die
optionale lokale Freigabeseite eingerichtet wurde, ihren eigenen Dienst ebenfalls
beenden (`com.kirabridge.approvals` unter macOS; unter Linux den selbst gestarteten
Freigabeprozess regulär beenden). Danach ausschließlich den eigenen aufgeführten
Launcher und die eigene Service-Datei entfernen: macOS
`~/Library/LaunchAgents/com.kirabridge.bridge.plist`, Linux
`~/.config/systemd/user/kirabridge.service` (danach `systemctl --user daemon-reload`).
Frühere Release-Programmordner können nach Prüfung einzeln entfernt werden.
**Nicht** pauschal `.local/share/kirabridge` oder `.config/kirabridge` löschen:
dort bleiben Daten, Audit, Queue, Konfiguration und Schlüssel für Wiederaufnahme
oder einen gesonderten bewussten Löschauftrag erhalten. OS-/uv-Caches werden nicht
automatisch entfernt. Bei individueller Einrichtung gilt deren dokumentierter
Dienstpfad, nicht blind diese Release-Anleitung.

## Fehler und Grenzen

- Falsches Paket/Prüfsumme: anderes passendes Originalpaket beziehen; nichts umgehen.
- Downloadfehler: Netzwerk/Platz prüfen, denselben Startbefehl wiederholen.
- Existierender fremder Launcher/Service: bleibt erhalten; individuellen Updateweg verwenden.
- `service_busy`: wartende/aktive Arbeit regulär abschließen; nicht Datenbank löschen.
- Kein Linux-systemd-Benutzerbus: Benutzeranmeldung prüfen; kein sudo/linger wird erzwungen.
- Fehlende Kontofunktion: Zielworkspace-/Platform-Berechtigungen durch Betreiber klären.
- Intel-Mac verwendet `cryptography48.0.1`, da ab49 keine Intel-Wheels mehr
  angeboten werden. Dieser RC begrenzt den Pin auf Intel-macOS und verhindert
  dort einen überraschenden Compilerbau. Weitere Sicherheits-/Wartungsprüfung
  dieses älteren Abhängigkeitszweigs bleibt Veröffentlichungsvoraussetzung.
- Kein unabhängiges Sicherheitsaudit, keine Garantie störungsfreier Tunnel und
  keine behauptete allgemeine Kontoverfügbarkeit. Linux-Clipboard benötigt eine
  grafische Sitzung. Automatische Mehrbenutzer-OAuth-Anbindung ist nicht enthalten.

## Optional: Entwicklerinstallation

Nur im autorisierten privaten Checkout: `uv sync --locked`, dann
`uv run kirabridge setup` und auf macOS `uv run kirabridge service install`.
Linux-Vorlagen und manuelle Konfiguration stehen im privaten Betriebsleitfaden.
Der normale Release-Schnellstart benötigt diese Repositoryschritte nicht.
