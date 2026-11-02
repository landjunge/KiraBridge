# KiraBridge

**RC26: native macOS-Tastatur einschließlich Systemtasten und Berechtigungsprüfung.**
Apple Notizen, F1–F20, Ziffernblock, Fn, Caps Lock und konfigurierte macOS-Kombinationen
nutzen passende native Eingabewege. Die Oberfläche bietet Systemaktionen und direkte
Links zu erforderlichen macOS-Freigaben. Tatsächliche Gerätewirkungen, Testergebnisse
und Grenzen stehen im [Tastaturbericht](docs/MACOS-KEYBOARD-COMPLETE-20261102.md).

Die App aktualisiert Dienst, Bedienoberfläche und die vorhandene ChatGPT-Anbindung
über den geprüften Installer mit Sicherung und Rückweg. Einstellungen und Zugänge
bleiben erhalten. Lokale Prüfungen, Paketidentität und der tatsächliche
Installationsablauf stehen im [Wiederanlauf- und Installerbericht](docs/BOOT-RECOVERY-INSTALLER-20261102.md).

[Intel-Installationspaket und Releasehinweise](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc26) ·
[ältere Veröffentlichungen](https://github.com/landjunge/KiraBridge/releases)

Lokal auf Intel installiert und über den echten ChatGPT-Connector geprüft:
**RC26, Build `34f5e6d`**: Notizen, Return und Lautstärke über den echten Connector
bestätigt; Control-Pfeile werden automatisch als Systemkombinationen gesendet.
Desktopwechsel sind zusätzlich visuell abgenommen. Die RC25-Wiederanlaufreparatur
bleibt enthalten.
Die bisherigen [Terminal-/Return-Belege](docs/RC20-RETURN-20261031.md) und
[RC18-Installationsbelege](docs/RC18-PUBLISH-INSTALL-20261029.md) bleiben erhalten.


## Funktionen

KiraBridge verbindet einen berechtigten KI-Chat mit lokalen Dateien, Prozessen,
sichtbaren Agententerminals und optionalen Projektwerkzeugen. Der lokale Kern
funktioniert unabhängig von ThreadDesk und anderen Integrationen.

- Dateien und Logs vollständig über Byte-Seiten, Offset, EOF und SHA256 lesen;
  Dateireferenzen zählen erst nach echter Übertragung und Speicherquittung als Import.
- Codex, Grok und weitere konfigurierte Provider über vorhandene Adapter ansprechen.
  Anbieterzugänge, Modelle und laufende Sitzungen bleiben eigenständig.
- Sichtbare Terminalziele anhand aktueller Fenster-, Tab-, TTY- und Prozessidentität
  prüfen. Paste-only und Return sind getrennte Aktionen; unbekannte Wirkung bleibt geschützt.
- Neue sichtbare Arbeit einmal begrenzt zulassen und Busy-/Selectionfehler konkret
  zurückgeben. Idempotenz verhindert Doppelzustellung auch nach Reconnect und Restart.
- Aufgaben, Nachrichten, Zustellung, ACK und fachliche Ergebnisse dauerhaft getrennt
  belegen; späte Antworten können bestehende Ausführungen ohne neue Eingabe abschließen.
- Werkzeuge dynamisch über vorhandene Operations-/Modulkataloge entdecken.
  Optionale ThreadDesk-Datei-/Wissensfunktionen, TollGate-Stopbelege und neutrale
  Agent-Authority-Beobachtungen benötigen jeweils ihre tatsächliche Konfiguration.

Direkte Terminaleingaben wie `/resume` verwenden `task_request` mit
`operation="session.input"` und den aktuellen `pane_id`-/`expected_pid`-Werten.
`text` wird unverändert eingefügt; `submit=true` sendet anschließend einmal Enter,
`submit=false` belässt den Text im Eingabefeld. Eine einzelne Return-Taste nutzt
ausdrücklich `key="enter"`, leeren Text und den `next_cursor` der angezeigten
Sitzung; bei Codex gehört dessen beobachtete Agenten-PID dazu. Die Oberfläche
bietet dafür eine Return-Schaltfläche und behandelt Text, Tastenwiederholung
und unklare Zustellung getrennt. Vertrag und Prüfstand stehen im
[Return-Reparaturbericht](docs/RC20-RETURN-20261031.md). Agentenaufträge verwenden
`agent.execute` oder `message_send(kind="work")` mit Empfangs- und Ergebnisprotokoll.
Die [RC20-Reparatur und ihre Tests](docs/RC20-TERMINAL-INPUT-20261030.md) sowie die
[anschließend autorisierte Installation](docs/RC20-881A53F-INSTALL-20261031.md)
dokumentieren Quellstand und tatsächlich laufenden Dienst getrennt.

[Architektur](docs/DEVELOPMENT_PLAN.md) · [Vollständige Datei-/Logreads](docs/READ-FULL-FILES.md)
· [Queuevertrag](docs/QUEUE-MANAGEMENT.md) · [RC18-Änderungen](docs/RELEASE-0.8.0rc18.md)

## Anforderungen

Geprüfte Zielumgebung: **iMac17,1 (Intel-iMac2015), macOS15.7.4 x86_64,
Python3.11.15 und uv0.11.6**. Normales Benutzerkonto ohne sudo, GitHubCLI (`gh`),
authentifizierter Repository-/Entwurfszugriff und Internet zu GitHub/PyPI sind nötig.
Das Paket enthält Wheel, Quellstand, Lockdatei, Installer und Integritätsmanifest;
Abhängigkeiten werden beim Installieren geladen. Es ist kein Offline-Komplettpaket.

Das Hardwaremodell allein bestätigt keine älteren macOS-Versionen. **ARM, macOS26
und ältere macOS-Versionen sind nicht abgenommen.** Bezahlte GitHub-macOS-Jobs
bleiben wegen der dokumentierten externen Kontozahlungs-/Ausgabenlimitblockade
zurückgestellt; lokale Erfolge werden nicht als GitHub- oder ARM-Pass ausgegeben.
Keine Apple-Signierung/Notarisierung. Gatekeeper nicht pauschal deaktivieren.

## Betrieb

Ein veröffentlichter versionierter Befehl lädt das Bootstrap samt Prüfsumme; dieses
prüft wiederum die fest eingebettete Paket-SHA256. Keine Remote-Pipe in eine Shell.
Release oder lokaler Installationsbeleg nennen Artefakt-Quellcommit und Prüfsummen. Branch, Paket und
antwortender Dienst können unterschiedliche Stände haben und werden getrennt geprüft.

Eine produktive Installation erst nach Freigabe in einem eigenen bestätigten
sichtbaren Terminal ausführen, niemals in laufende Codex-/Grok-Sitzungen eingeben.
Bei der vom Betreiber ausgeführten produktiven Installation zusätzlich die bestehende
Option `--require-visible-terminal` verwenden. Die isolierte Abnahme verwendet
explizite Testpfade und ein eigenes Testlabel; sie ersetzt keine produktive Freigabe.
Die Optionen `--language de`, `--language en` und `--motion reduced` steuern die
Darstellung. Echte Fortschritts-/Fehlermeldungen haben Vorrang vor Animation.

Der launchd-Benutzerdienst läuft nach dem Schließen von Terminal oder Browser weiter.
`~/.local/bin/kirabridge status` liest den antwortenden Dienst. Der Installerstatus
aus dem erhaltenen Paket nennt zusätzlich den installierten Quellcommit. Ein
Neustart muss vorher laufende Arbeit und den tatsächlichen Dienstbesitz prüfen.

Updates verwenden die vorhandene versionierte Transaktion mit Backup, Ownership-,
Leerlauf-, Integritäts- und Healthprüfungen. Konfiguration, Credentials, Rechte,
Datenbank und Nutzerdateien bleiben erhalten. Der Rückweg verwendet nur die
passende gesicherte Transaktion; er ist erst durch die antwortende alte Version
bestätigt. Keine alte Datenbank über neuere Ergebnisse zurückspielen.

[Installation Deutsch](docs/INSTALL-DE.md) · [Installation English](docs/INSTALL-EN.md)
· [macOS-Vertrag](docs/INSTALL-MACOS.md)

## Konfiguration

Standardkonfiguration und getrennte Credentials liegen unter `~/.config/kirabridge/`.
Die Konfiguration bestimmt Principals, erlaubte Operationen, Dateiwurzeln,
Agentenadapter, sichtbare Zielbindungen und optionale Integrationen. Der aktuelle
Werkzeugkatalog und die Berechtigungsentscheidung der konkreten Operation sind
maßgeblich. Ein vorhandener Modulname bedeutet weder installierten Adapter noch
freigegebene Aktion. [ChatGPT-Einrichtung](docs/CHATGPT.md).

Standardlaufzeiten, Transaktionsbackups und Logs liegen unter
`~/.local/share/kirabridge/install/`; die tatsächlichen Pfade ergeben sich aus dem
installierten Paket/der Konfiguration. Keine fremden Profile oder Shell-Pfade
unbesehen überschreiben. Bestehende KiraBridge-Schlüssel bleiben erhalten, bis
4AllPass eine tatsächlich sichere, ausdrücklich freigegebene Übernahme bietet.

## Sicherheit

Berechtigung, Zulassung, Eingabeversuch, bestätigte Zustellung und Ergebnis sind
verschiedene Zustände. `unknown` ist kein sicher wiederholbarer Auftrag; `blocked`
ist keine Erlaubnis zur Freigabe. Keine historischen Nachrichten blind erneut senden,
keine Queue pauschal löschen, keine Agenten zum Erzwingen einer Installation beenden.

Terminalguards prüfen aktuelle Identität und Bereitschaft. Busy, geänderte Auswahl
oder unklare Eingabe führen zu einer konkreten Ablehnung statt beliebigem Retargeting.
Ein inaktives Chatfenster wird durch eine gespeicherte Antwort nicht automatisch geweckt.
Private Tokens gehören weder in Befehle noch Logs oder Git. Installation erteilt keine
zusätzlichen OS-/TCC-Rechte. Prüfsummen vom selben Release erkennen Beschädigungen,
ersetzen aber keine unabhängige Herausgebersignatur.

## Fehlerbehebung

| Beobachtung | Sicherer nächster Schritt |
| --- | --- |
| Release/Download nicht erreichbar | Authentifizierung, Repositoryzugriff und Entwurfs-/Veröffentlichungsstatus prüfen. |
| Prüfsumme stimmt nicht | Abbrechen und Originalartefakt prüfen; nichts ausführen. |
| `visible_target_busy` | Geschützte Handoffreservierung und ihren tatsächlichen Ausgang prüfen. |
| `session_busy` | Aktuelle Aktivität prüfen; keinen laufenden Agenten unterbrechen. |
| `session_selection_changed` | Fenster/Tab/TTY/PID neu lesen; keinen alten Auftrag wiederholen. |
| `unknown` oder verlorene Antwort | Vorhandene Receipt-/Start-/ACK-/Late-Reply-Belege abgleichen. |
| Installation meldet `BUSY` | Echte laufende Arbeit geordnet abschließen lassen; Guards nicht umgehen. |
| Start oder Rollback läuft in Timeout | Logs, Health und tatsächlich antwortende Version lesen; keinen Erfolg behaupten. |

[Ursachen und Reparaturbelege](docs/QUEUE-DIRECT-ADMISSION-20261029.md)
· [Abschlussbericht mit Rückfallplan](docs/INTEL-RELEASE-20261029.md)

## Entwicklung

Die Entwicklung erfolgt in isolierten Worktrees. Vor riskanten Änderungen lokal
sichern; passende Tests mit synthetischen Stores, Fake-Terminal-I/O und echten
lokalen MCP-Roundtrips verwenden. Integrationen werden gegen die im CI-Workflow
festgelegten Quellstände geprüft. Erst belegte Teilschritte committen und pushen;
Merge, Veröffentlichung und produktive Installation bleiben getrennte Entscheidungen.

Der deterministische Builder `scripts/build_release.py` verlangt einen sauberen
exakten Git-Commit. Zwei Builds müssen dieselben SHA256SUMS ergeben.
`scripts/accept_macos_release.py` prüft echte Installation/Upgrade, Start,
Idempotenz, Restart, KeepAlive, Rollback und Erstinstallation unter einem eigenen
Testlabel. Es ist kein Dry-run und darf keine produktiven Pfade erhalten.
Nach jeder Testdienstbereinigung muss dessen Abwesenheit unabhängig belegt sein.

| Version | Tatsächlicher Stand |
| --- | --- |
| 0.8.0rc20 / ecb76cb | Lokal auf Intel installiert; Text-Return und reales nichtleeres Codex-Menü abgenommen, Quellhash und laufende Dienste verifiziert. Kein Push oder neuer öffentlicher Release. |
| 0.8.0rc18 | Veröffentlichtes Intel-Prerelease; tatsächlicher Download, sichtbare Installation und produktive Stop-/Start-/Neustarttests bestanden. Belege im Installationsbericht. |
| 0.8.0rc17 | Separater Entwurf und gesicherter Rückweg vor RC18; authentifizierter Download und isolierter Rollback nachgewiesen. |
| 0.8.0rc16 / rc15 | Historische Entwürfe erhalten; keine neue Abnahme daraus abgeleitet. |
| 0.8.0rc14 | Veröffentlichtes Prerelease; Originalwheel als geprüfte Upgrade-/Rollbackfixture erhalten. |
| Frühere Versionen | Unter dem Link „Alle erhaltenen Versionen“ mit ihrem tatsächlichen Veröffentlichungsstatus abrufbar. |

**Lizenz:** [Netzwerkpunkt Personal Use License1.0](LICENSE). Private, nicht geschäftliche
Nutzung unter den Lizenzbedingungen kostenlos; geschäftliche Nutzung nur mit
separater schriftlicher Erlaubnis. Deutsch ist maßgeblich. Kein OSI-Standard und
keine rechtliche Prüfung; Drittanbieterlizenzen gelten weiterhin.
