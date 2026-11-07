[English](README.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-256.png">
  <img src="assets/design/icons/light/KiraBridge-light-256.png" alt="KiraBridge" width="160" height="160">
</picture>

# KiraBridge

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/design/wordmarks/KiraBridge-dark.svg"><img src="assets/design/wordmarks/KiraBridge-light.svg" alt="KiraBridge" width="312"></picture></p>

<!-- AUTO-DOWNLOADS:START -->
<p align="center">
  <a href="https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36"><img src="assets/readme/download-macos-intel.svg" alt="macOS Intel 0.8.0rc36" width="170"></a>
  &nbsp;
  <a href="https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc37.dev1"><img src="assets/readme/download-windows-preview.svg" alt="Windows Preview 0.8.0rc37.dev1" width="170"></a>
</p>
<!-- AUTO-DOWNLOADS:END -->

**Du redest mit der KI. Die Arbeit landet auf deinem Rechner.**

KiraBridge verbindet ChatGPT mit **Grok Build und Codex, die in Terminalfenstern
auf deinem Computer laufen**. Besprich im Chat, was du erledigen möchtest, gib die
Arbeit an diese Terminalagenten weiter und verfolge ihre Antworten — mit den von dir erlaubten Zugriffen.

**Entwicklungs- und Installationsstand (7. November 2026):** Debian-Serverquelle **0.8.0rc41** (`350d368`); auf dem Intel-Mac installierte Laufzeit **0.8.0rc40** (`d12838a`). Diese Stände sind nicht mit einem veröffentlichten macOS-Download gleichzusetzen.

**Veröffentlichter macOS-Intel-Download:** [0.8.0rc36](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36) · 4. November 2026 · Vorabversion.

### [KiraBridge herunterladen — App und Installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc36/KiraBridge-0.8.0rc36-Intel-Installer.zip)

[Prüfsummen](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc36/SHA256SUMS)
· [Alle Versionen](https://github.com/landjunge/KiraBridge/releases)

Für die Downloads brauchst du ein GitHub-Konto mit Zugriff auf dieses private Repository.
Dies ist eine Vorabversion; eine stabile Version gibt es noch nicht. RC36 ist für Intel-Macs verfügbar.

Das frühere RC33-Release enthält eine [Windows 11-Entwicklungsvorschau](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc33/KiraBridge-0.8.0rc33-Windows-Dev-Kit.zip)
mit nativer Tastatur, Shortcuts und abgesicherter Fenstersteuerung. Es ist ein
separates Entwicklungspaket; allgemeine Windows-Datei-, Prozess- und Terminaltools
gehören nicht zu seinem Umfang. Siehe [RC33-Paketprüfung, Installationsstand und Grenzen](docs/RC33-DELIVERY-20261104.md).

Der veröffentlichte [Windows-Einrichtungsassistent 0.8.0rc37.dev1](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc37.dev1)
hat Belege für Download und getrennte Windows-Installation.
Alle sieben nativen Prüfphasen dieser begrenzten Entwicklungsvorschau bestanden. Entpacke das Paket und öffne
**Einrichtung-starten.cmd** für die vier Schritte. Kontoanmeldung und der echte
ChatGPT-Verbindungstest mit deinem Konto bleiben bei dir.
[Prüfstand und Grenzen](docs/WINDOWS-SETUP-20261104.md) · [Anleitung](docs/WINDOWS-SETUP.md).

Der oben verlinkte Intel-Download basiert auf RC36 (`d4aebdd`); die getrennten Quell- und Installationsstände stehen in der Übersicht am Anfang.
[Release-, Artefakt- und Installationsquellnachweis](docs/evidence/readme-current-20261107.json).
Der [frühere PR61-Installationsbericht](docs/RC40-PR61-SHIM-INSTALL-20261106.md)
beschreibt den vorherigen RC40-Quellstand `a5d381a`.

Windows-Funktionsgleichstand und eigenständiger Installer bleiben Entwicklungsarbeit. Die veröffentlichte Windows-Vorschau
enthält keine allgemeinen Datei-, Prozess- oder Terminaltools und keine
Windows-Dienstinstallation. Hier wird kein neues Paket dieser laufenden Projekte
und kein veröffentlichter RC40-Download angeboten.

## Wobei KiraBridge dir hilft

- **An lokalen Projekten arbeiten:** Lass deine verbundene KI Projektdateien und
  Protokolle lesen, Dateien bearbeiten oder Befehle ausführen — im erlaubten Rahmen.
- **Mit Terminalagenten arbeiten:** Schicke Aufträge an Grok Build und Codex
  in ihren eingerichteten Terminalsitzungen auf deinem Computer.
- **Die Arbeit verfolgen:** Sieh Anfragen, Nachrichten und Ergebnisse im lokalen Steuerfenster.
- **Den Zugriff bestimmen:** Lege fest, welche Ordner und Aktionen erlaubt sind
  und wann ein Auftrag deine Freigabe braucht.

ThreadDesk und andere Integrationen sind optional. Der Kern von KiraBridge funktioniert eigenständig.

## Loslegen

1. **Installieren oder aktualisieren.** Lade das Intel-Installer-ZIP herunter und
   entpacke es vollständig. Öffne `KiraBridge-Installer.app` und folge der Bestätigung
   und sichtbaren Terminalinstallation. Verwende ein separates Terminalfenster;
   laufende Agentensitzungen erhalten.
2. **App öffnen.** Der Installer aktualisiert Dienst und Desktop-App gemeinsam.
   Öffne `KiraBridge.app` in `~/Applications`. Vorhandene Einstellungen und Zugänge
   bleiben erhalten; der Installer erstellt eine Rückfallsicherung.
3. **Chat verbinden.** Folge der [ChatGPT-Verbindungsanleitung](docs/CHATGPT.md).
   Bitte ihn zum Einstieg, eine kleine Datei aus einem erlaubten Ordner zu lesen.
   Gib die Anfrage bei Bedarf frei und prüfe das Ergebnis in deinem Chat.

**Voraussetzungen:** Intel-Mac, geprüft mit macOS 15.7.4; Python 3.11 und uv 0.11.6
bereits im Terminal verfügbar; Internet zum Laden von Abhängigkeiten.
Installiere mit deinem normalen Benutzerkonto. KI-Konten und mögliche Anbieterkosten
bleiben getrennt; die Chatverbindung braucht die passenden Kontoberechtigungen.
Für Terminalaufträge müssen Grok Build oder Codex installiert und angemeldet sein.
Richte ihre Terminalsitzung in KiraBridge als Ziel ein.

Diese Vorabversion hat bekannte Einschränkungen bei der Terminalbedienung; die App
ist nicht von Apple notarisiert. Der [RC36-Nachweis](docs/TERMINAL-MINIMIZED-RC36-20261104.md)
beschreibt das veröffentlichte Paket; siehe [Installation, Prüfung und Hilfe](docs/INSTALL-DE.md).


## Linux-/Debian-Server

Die [in Main integrierte Serverimplementierung aus PR72](https://github.com/landjunge/KiraBridge/pull/72)
bietet einen privaten HTTP-MCP-Dienst auf Loopback mit Bearer-Authentifizierung
und Healthprüfung sowie Installation, Update und Rollback über `systemd --user`.
Zielplattformen sind Debian 13 und Ubuntu 24.04 x86_64. Der Onlineinstaller benötigt
einen laufenden Benutzermanager; die Laufzeit über Logout/Neustart folgt der Sitzungspolitik
des Hosts. Linger, Administratorrechte, Firewall und öffentliches HTTPS werden nicht eingerichtet.

Der Server läuft ohne macOS-GUI, Terminal.app oder native Tastatursteuerung.
Zwischenablage ist optional (`wl-clipboard`/`xclip`). ChatGPT-/Kontoverknüpfung und
Fernzugriff benötigen eigene Konfiguration.

Das 0.8.0rc41-Archiv ist nativ auf Debian 13.6 x86_64 abgenommen und
[im getrennten Serverrelease veröffentlicht](https://github.com/landjunge/KiraBridge/releases/tag/linux-v0.8.0rc41). Der echte Download
stimmt mit GitHubs Digest und den Releaseprüfsummen überein. Ubuntu 24.04 ist ein
unterstütztes Ziel; eine neue native Ubuntu-Abnahme wird hier nicht behauptet.
[Linux-x86_64-Archiv](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz) ·
[Prüfsummen](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/SHA256SUMS).
[Installation, Update und Rollback](docs/INSTALL-LINUX-SERVER.de.md) ·
[Quell-, Abnahme- und Downloadbelege](docs/evidence/readme-current-20261107.json).

[Finale native Releasebelege](docs/evidence/debian-dirktest-release-20261107.json).
[Archiv-SHA-256](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256).

```sh
gh release download linux-v0.8.0rc41 -R landjunge/KiraBridge -p 'KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz*'
sha256sum -c KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz
cd KiraBridge-0.8.0rc41-Linux-x86_64
sh install.sh --yes
```

Für ein Update das neue Release in ein frisches Verzeichnis laden, prüfen und dort
`sh install.sh --yes` mit denselben Zielpfaden ausführen. Die bisherige Laufzeit für
Rollback behalten; [explizite Pfade und Rollbackbefehle](docs/INSTALL-LINUX-SERVER.de.md)
decken auch Hosts mit gemeinsam beschreibbaren übergeordneten Verzeichnissen ab.

## Tastenfolgen und weniger Cloudaufrufe

`keyboard_sequence` führt bis zu 32 echte Key-down/Key-up-Paare ohne Zwischenablage
seriell in einem idempotenten Task aus. Wenn die nächste Taste von der Rückmeldung
der vorigen abhängt, bleiben einzelne Aufrufe erforderlich. Blocktext ist ein
eigener Vorgang und ersetzt keine verlangten einzelnen Tastenereignisse.

Bekannte Lesewerkzeuge teilen eine Übergabe über
`read_query(query={"operation":"tool.batch","calls":[...],"result_format":"structured"})`.
Das optionale strukturierte Format entfernt ausschließlich bewiesene äquivalente
JSON-Textkopien; alle strukturierten Werte, Fehler und Metadaten bleiben.
Der Default ist `full`. Rechte werden frisch geprüft. Bei ungewissem Ausgang
denselben Task lesen, statt die Eingabe erneut auszuführen.

[RC28-Tastenfolgen](docs/RC28-E2E-LATENCY-20261103.md) ·
[RC29-Aufrufreduktion](docs/RC29-CLOUD-CALL-REDUCTION-20261103.md) ·
[RC30-Messungen, Installation und Grenzen](docs/RC30-HOTPATHS-20261103.md).
Dieselben acht großen Leseergebnisse benötigten im gemessenen RC30-Vergleich einen
statt zwei Apps-Aufrufe; Median 22,72 → 13,02 Sekunden bei je drei Gruppen.
Cloudlatenz bleibt; das ist kein neuer physischer Tasten- oder Voicevergleich.

RC31 ergänzt direkte native JSON-Reads über `read_query` mit `operation="native.read"`
und begrenzte Accessibility-Unterbäume mit `max_depth>0`. Dadurch sinken wiederholte
UI-Leseaufrufe und persistente Taskdaten. Ereignisabrufe laden große Ausgaben nicht
mehr mit. Siehe [RC31-Umsetzung, Messungen und Auslieferungsstand](docs/RC31-NATIVE-READS-20261103.md).

RC32 bündelt zusätzlich Attribute innerhalb optionaler UI-Unterbäume. Dieselben
zwölf eigenen AppKit-Buttons benötigten im kontrollierten nativen Test 8,14 statt
16,86 ms Median bei zwanzig abwechselnden Runden. Siehe [RC32-Messungen und Grenzen](docs/RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md).

## Lizenz

Private, nicht geschäftliche Nutzung ist unter der
[Netzwerkpunkt Personal Use License 1.0](LICENSE) kostenlos. Geschäftliche Nutzung
benötigt eine gesonderte schriftliche Erlaubnis. Der deutsche Lizenztext ist maßgeblich.

[Entwicklerdokumentation](docs/DEVELOPERS.de.md): Python ab 3.11, gelockte
uv-Umgebung, CLI-Einstieg, Quellverzeichnisse und gezielte Prüfungen. Ausgangspunkt
ist ein Repositorycheckout; veröffentlichter Installer und Entwicklungsumgebung sind getrennt.

Lokaler CLI-Modulkandidat: [Terminal-/Codex-/Grok-Grenzen und Prüfgrenzen](docs/plans/TERMINAL-CLI-MODULES-20261104.md).
Dieses Entwicklungspaket ist vom veröffentlichten RC36-Download getrennt; die
echte Browserchat-Abnahme steht noch aus.

Lokaler Big-Plan-Koordinatoradapter: [freigegebener Aufgaben-Loop, Codex/Grok-Prüfung und Agentenberichte](docs/COORDINATOR-LOOP.md). Eigenes Opt-in-Profil; bestehende sichtbare Sitzungen und veröffentlichte Pakete behalten ihren bisherigen Stand.

Der [Supervisor mit bestehendem Nutzerauftrag](docs/COORDINATOR-CONTINUATION-20261106.md) führt zugeordnete ThreadDesk-Aufgaben ohne weitere Nutzerfreigabe fort. Er gleicht vorhandene Claims und Ergebnisse ab, überspringt erledigte Arbeit und hält unabhängige Aufgaben bei einem Einzelfehler weiter bearbeitbar.

Der [Integrationscheckpoint vom 6. November](docs/BIGPLAN-INTEGRATION-STATUS-20261106.md) bündelt angenommene Pakete, gemeinsame Remote-/Absturztests und die damals offenen Gates. Für geprüfte Quelle und installierten Pin gilt der [Abgleich vom 7. November](docs/evidence/readme-current-20261107.json); datierte Checkpoints behalten ihre historischen Ergebnisse.

Der integrierte Koordinatorquellstand unterstützt außerdem native Core-Aktivierung, den auf den Eigentümer begrenzten MCP-Aufruf `coordinator_status` und dauerhafte Angenommen-/Stoppmeldungen im vorhandenen Completion-Postfach. Nach erfolgreichem Review und Prüfungen setzt er gepinnte Aufgaben ohne Laden eines Skills fort. [Nativer Vertrag und Prüfnachweise](docs/COORDINATOR-NATIVE-20261106.md) beschreiben den Stand; Desktop- und Liveabnahme bleiben gesondert.

Sein Status zeigt gespeicherte Warte-, Ausführungs- und Abnahmezeiten aus dem gebundenen Core und Receipt. Fehlende oder ungültige Zeitwerte bleiben unbekannt; das Lesen startet keine Arbeit.

Das optionale [native Worker-Routing](docs/COORDINATOR-NATIVE-ROUTING-20261106.md) verwendet die geprüfte CLI-Matrix für versiegelte Managed-Aufträge; sichtbare Sitzungen und das eigene strukturierte Grok-Reviewprotokoll bleiben erhalten. Angeforderte Modell-/Effortwerte und beobachtete Metadaten bleiben getrennt; lokale Fixturetests sind keine Provider- oder Deploymentabnahme.

[CLI-Rückgabe und reine Postfachzustellung](docs/NATIVE-COMPLETION-RETURNS-20261106.md): Der integrierte Quellstand belässt Antworten/Ergebnisse im Postfach des anfragenden Clients. `--inbox-only` vermeidet Terminalzustellung; Completionquittungen benötigen keinen weiteren Agententurn.

[Frühere Windows-Vorschau dev2](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev2):
Native Tastatur und lokales MCP haben die Abnahme in einer eigenen Windows 11-VM bestanden.
[Ergebnisse und Grenzen](docs/WINDOWS-DEVELOPMENT-20261103.md); macOS bleibt getrennt.

[Frühere Windows-Desktop-Vorschau dev3](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev3): Alle sechs nativen
Gastprüfungen bestanden, einschließlich Ctrl-/Alt-/Shift-Kombinationen und
abgesicherter Fenstersteuerung. Veröffentlichte Downloads und die getrennte
Windows 11-Installation sind geprüft. [Belege und Grenzen](docs/WINDOWS-DESKTOP-20261104.md);
dev2 bleibt als Rückfallmöglichkeit erhalten.
