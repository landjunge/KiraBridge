# KiraBridge

[RC17-Veröffentlichungsstatus](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17)

KiraBridge verbindet einen berechtigten KI-Chat mit lokalen Dateien, sichtbaren Agententerminals und optionalen Projektwerkzeugen.

## Tatsächlicher Stand

- **Paketversion:** `0.8.0rc17`. [GitHub zeigt den tatsächlichen Veröffentlichungsstatus](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17); ein Entwurf ist keine Veröffentlichung.
- **Historische vollständige Intel-Abnahme:** macOS15.7.4 x86_64, Python3.11.15, geprüfter Programmstand `20a30e8`: **1.609 Tests bestanden, 1 übersprungen**, Ruff/Format und Wheel/Source-Paketbau bestanden; **9/9 tatsächliche RC14-Pakettests** einschließlich Neustart, KeepAlive, Erstinstallation und Rollback bestanden.
- **Freigabe:** Betreiberfreigabe für Merge und sichtbare Intel-Installation nach lokaler Abnahme. Hosted-Mac-Jobs konnten wegen GitHub-Billing nicht starten; lokale Ergebnisse werden nicht als Actions-Erfolg ausgegeben. Apple Silicon und macOS26 bleiben ungeprüft.
- **Installierter Stand:** `~/.local/bin/kirabridge status` liest den tatsächlich antwortenden Dienst. `installer/install.py status` aus dem erhaltenen Paket nennt zusätzlich den installierten Quellcommit. Ein Branch, ein Release-Asset und ein laufender Dienst sind getrennte Zustände.
- **Terminal-Nachprüfung:** [Folgefehler der Prozessbereinigung und aktueller Blocker](https://github.com/landjunge/KiraBridge/blob/fde9d87a36ed6c0bdab4456c3c8812d0378d7fcd/docs/TERMINAL-CLEANUP-20261027.md). Der installierte RC17-Prüfauftrag wartet weiterhin auf Ausführung; Versionsanzeige und isolierte Tests sind kein bestandener produktiver Eingabenachweis.

[Intel-Abnahme und Freigabe](docs/INTEL-ACCEPTANCE-20261026.md) · [Historischer Rollbackfehler](docs/RC14-ROLLBACK-20261026.md) · [Braille-Implementierung](docs/BRAILLE-PARTIAL-OUTPUT-20261026.md)

## Was KiraBridge kann

- Berechtigte Datei-, Prozess- und Terminaloperationen aus einem verbundenen Chat ausführen, mit nachvollziehbarem Ergebnis statt bloßer Annahmebestätigung. [Dateien und Codex-Protokolle vollständig lesen](docs/READ-FULL-FILES.md): echte Byte-Seiten mit Offset, EOF und SHA-256, ohne Ein-Megabyte-Gesamtdateigrenze.
- Codex-, Grok- und weitere eingerichtete Agentenadapter verwenden. Anbieterzugänge, Modelle und laufende Sitzungen werden nicht durch KiraBridge ersetzt.
- Sichtbare Terminalfenster frisch katalogisieren und lesen; Eingaben an bestätigte Fenster-/Tab-/TTY-/Prozessidentitäten binden. `submit=false` bedeutet Einfügen ohne Return. Der [gezielte Terminalfix und seine Intel-Nachweise](docs/TERMINAL-CONTROL-20261027.md) ergänzen diesen Weg für bestätigte leere Shells mit einzeiligem Text und trennen sichere Vorabverweigerung von unbekanntem Transportausgang. Bei echter Aktivität, geänderter Zuordnung oder unbekannter Eingabe verweigert die Bridge den Eingriff.
- Berechtigte Warteschlangen vollständig einsehen und gezielt verwalten. `withdraw` nimmt unbekannte Ausführungen aus der aktiven Ansicht; ein belegter `retire` kann eine veraltete Zustellreservierung zurücknehmen. Historie bleibt erhalten, eine unbekannte Ausführung wird weder als beendet ausgegeben noch blind wiederholt.
- Werkzeuge über den Operationskatalog auffindbar machen und Freigabe, Erreichbarkeit, Ausführung und Quittierung unterscheiden. Empfangene Rückmeldungen belegen keine automatische Aufweckung eines inaktiven Chatfensters.
- Optional ThreadDesk, Wissens-/Dateiübertragung, Teamkoordination und Workflowbelege anbinden. Diese Module sind getrennt; KiraBridge benötigt ThreadDesk nicht für den lokalen Kern. Ein Dateiverweis ist kein Byteimport, eine Übertragung ohne bestätigte dauerhafte Speicherquittung kein erfolgreicher Import.

## Voraussetzungen

Normales Benutzerkonto, **Python 3.11**, **uv 0.11.6**, **GitHub CLI (`gh`)** und Internetzugriff auf GitHub/PyPI. Tatsächlich geprüft ist **Intel x86_64 mit macOS 15.7.4**. Das Modell „iMac 2015“ allein belegt keine Unterstützung eines älteren macOS. Apple Silicon wird im Paket berücksichtigt, ist ohne echte ARM-Abnahme aber nicht als geprüft freigegeben; macOS 26 wird vom Einstieg akzeptiert und bleibt unbestätigt.

Bei privaten Releases muss `gh auth login` erfolgt und der Repositoryzugriff vorhanden sein. Keine Tokens in Befehle, Protokolle oder Git schreiben. Der Installer ändert keine OS-/TCC-Rechte und installiert keinen Paketmanager oder Compiler. Agenten und ihre Konten werden separat eingerichtet. **Keine Apple-Signierung oder Notarisierung**; Gatekeeper nicht pauschal deaktivieren.

## Installation und Aktualisierung · RC17 Intel

**Diesen einen Befehl im eigenen sichtbaren macOS-Terminal kopieren.** Er lädt den authentifizierten RC17-Installer, prüft SHA-256 und startet erst dann die lokale Installation bzw. Aktualisierung. Die Dateien müssen im verlinkten Release tatsächlich vorhanden sein; ein privater Entwurf erfordert zusätzlich Entwurfszugriff.

```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --require-visible-terminal --motion full "$@")
```

Der Bootstrap prüft zusätzlich die fest eingebettete SHA-256 des macOS-Pakets. Prüfsummen vom selben Release erkennen Beschädigung, ersetzen keine unabhängige Herausgebersignatur. Kein `curl | sh`. Quellcommit, Prüfergebnisse und endgültige Paketwerte stehen im Release und in [PR43](https://github.com/landjunge/KiraBridge/pull/43).

Der Installer prüft das sichtbare Frontfenster, ausgewählten Tab, TTY und aktuelle Prozessidentitäten vor der Aktivierung. Genau ein eigenes Arbeitsfenster verwenden; keine Eingabe in laufende Codex-/Grok-Sitzungen. `--motion reduced` reduziert Bewegung, `--language en` wählt Englisch. Vollständiger Braille-Schriftzug und Brücke verwenden Pink und Lichtakzente; Ausgabe und Eingaben haben Vorrang, bei ungeeigneter Darstellung gilt ein Text-Fallback.

Erstinstallation legt Benutzerdateien an. Updates erhalten vorhandene Konfiguration, Zugangsdaten, Rechte, Datenbank und Nutzerdateien. Laufende Arbeit, fremde Dienste, veränderte Launcher oder nicht passende Dienstdefinitionen blockieren die Umschaltung. Solche Prüfungen nicht durch Löschen von Queues oder Prozessabbruch umgehen. Neue Berechtigungen werden nicht durch ein Designupdate erteilt.

**Der launchd-Benutzerdienst läuft nach dem Schließen von Terminal- und Browserfenstern weiter.** Anmeldung, Abmeldung, Schlafmodus und Herunterfahren bleiben eigene Systemzustände. Die sichtbare Installation ist vom späteren Hintergrunddienst getrennt. Die grafische Darstellung bleibt auf menschenlesbare Ausgaben beschränkt; MCP und Status-JSON erhalten keine Grafikausgaben.

## Status, Fehler und Rückweg

- Dienstversion und Zustand: `~/.local/bin/kirabridge status`.
- Installierter Quellcommit: `python3.11 KiraBridge/installer/install.py status` aus dem erhaltenen entpackten Paket.
- Neustart erst nach Klärung laufender Arbeit: `launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge`, danach Status erneut lesen.
- Protokolle: `~/.local/share/kirabridge/install/logs/`; Konfiguration/Zugangsdaten: `~/.config/kirabridge/`; versionierte Laufzeiten und gesicherter Rückweg: `~/.local/share/kirabridge/install/`.
- Bei falscher Prüfsumme abbrechen. Bei `BUSY` die genannten Aufträge prüfen, nicht blind löschen oder erneut senden. Bei fehlender Sichtbarkeit das eigene Arbeitsfenster prüfen. Ein Timeout ist kein erfolgreicher Start.
- Gesicherten Rückweg aus der Transaktionsmeldung verwenden: `python3.11 KiraBridge/installer/install.py rollback`. Aktuelle Nutzer-/Ergebnisdaten und Zugangsdaten werden nicht blind mit alten Datenbanksicherungen ersetzt. Ein Rückfall muss durch tatsächlich antwortende alte Version bestätigt werden.

[Ausführliche Installation](docs/INSTALL-DE.md) · [macOS-Vertrag](docs/INSTALL-MACOS.md) · [Queueverwaltung](docs/QUEUE-MANAGEMENT.md) · [Releasehinweise](docs/RELEASE-0.8.0rc17.md)

## Lizenz

[Netzwerkpunkt Personal Use License 1.0](LICENSE).

Private, nicht geschäftliche Nutzung ist nach den Lizenzbedingungen kostenlos; geschäftliche Nutzung benötigt gesonderte schriftliche Erlaubnis. Die deutsche Lizenzfassung ist maßgeblich. Dies ist eine individuelle Lizenz mit einsehbarem Quelltext, keine OSI-anerkannte Open-Source-Lizenz. Diese Zusammenfassung ist keine rechtliche Prüfung. Drittanbieter-Lizenzen bleiben anwendbar.

Lizenzreferenz: `LicenseRef-Netzwerkpunkt-Personal-Use-1.0`.
[Lizenzhistorie und bestehende Rechte](docs/LICENSE-HISTORY.md) · [Fremdlizenzen und erforderliche Hinweise](docs/THIRD-PARTY-LICENSES.md).
[Sprachfassung und dokumentierte Sprachprüfung](docs/LICENSE-LANGUAGE-CHECK.md).
