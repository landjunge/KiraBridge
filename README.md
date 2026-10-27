# KiraBridge

[English](#english) · [Deutsch](#deutsch) · [RC17 release / Release-Status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17)

KiraBridge connects an authorized AI conversation to local files, visible agent terminals and optional project tools. KiraBridge verbindet einen berechtigten KI-Chat mit lokalen Dateien, sichtbaren Agententerminals und optionalen Projektwerkzeugen.

## Tatsächlicher Stand / Actual status

- **Paketversion / Package version:** `0.8.0rc17`. [GitHub zeigt den tatsächlichen Veröffentlichungsstatus / actual publication status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17); ein Entwurf ist keine Veröffentlichung / a draft is not a publication.
- **Historische vollständige Intel-Abnahme / Historical full Intel acceptance:** macOS15.7.4 x86_64, Python3.11.15, geprüfter Programmstand `20a30e8`: **1.609 Tests bestanden, 1 übersprungen / 1,609 passed, 1 skipped**, Ruff/Format und Wheel/Source-Paketbau bestanden; **9/9 tatsächliche RC14-Pakettests** einschließlich Neustart, KeepAlive, Erstinstallation und Rollback bestanden.
- **Freigabe / Approval:** Betreiberfreigabe für Merge und sichtbare Intel-Installation nach lokaler Abnahme. Hosted-Mac-Jobs konnten wegen GitHub-Billing nicht starten; lokale Ergebnisse werden nicht als Actions-Erfolg ausgegeben. Apple Silicon und macOS26 bleiben ungeprüft / unverified.
- **Installierter Stand / Installed state:** `~/.local/bin/kirabridge status` liest den tatsächlich antwortenden Dienst. `installer/install.py status` aus dem erhaltenen Paket nennt zusätzlich den installierten Quellcommit. Ein Branch, ein Release-Asset und ein laufender Dienst sind getrennte Zustände.
- **Terminal-Nachprüfung / Terminal acceptance:** [Cleanup-Folgefehler und aktueller Blocker / cleanup follow-up and current blocker](docs/TERMINAL-CLEANUP-20261027.md). Der installierte RC17-Prüfauftrag wartet weiterhin auf Ausführung; Versionsanzeige und isolierte Tests sind kein bestandener produktiver Eingabenachweis. / The deployed probe remains accepted; version and isolated tests do not prove productive input.

[Intel-Abnahme und Freigabe](docs/INTEL-ACCEPTANCE-20261026.md) · [Historischer Rollbackfehler](docs/RC14-ROLLBACK-20261026.md) · [Braille-Implementierung](docs/BRAILLE-PARTIAL-OUTPUT-20261026.md)

## Deutsch

### Was KiraBridge kann

- Berechtigte Datei-, Prozess- und Terminaloperationen aus einem verbundenen Chat ausführen, mit nachvollziehbarem Ergebnis statt bloßer Annahmebestätigung. [Dateien und Codex-Protokolle vollständig lesen](docs/READ-FULL-FILES.md): echte Byte-Seiten mit Offset, EOF und SHA-256, ohne Ein-Megabyte-Gesamtdateigrenze.
- Codex-, Grok- und weitere eingerichtete Agentenadapter verwenden. Anbieterzugänge, Modelle und laufende Sitzungen werden nicht durch KiraBridge ersetzt.
- Sichtbare Terminalfenster frisch katalogisieren und lesen; Eingaben an bestätigte Fenster-/Tab-/TTY-/Prozessidentitäten binden. `submit=false` bedeutet Einfügen ohne Return. Der [gezielte Terminalfix und seine Intel-Nachweise](docs/TERMINAL-CONTROL-20261027.md) ergänzen diesen Weg für bestätigte leere Shells mit einzeiligem Text und trennen sichere Vorabverweigerung von unbekanntem Transportausgang. Bei echter Aktivität, geänderter Zuordnung oder unbekannter Eingabe verweigert die Bridge den Eingriff.
- Berechtigte Warteschlangen vollständig einsehen und gezielt verwalten. `withdraw` nimmt unbekannte Ausführungen aus der aktiven Ansicht; ein belegter `retire` kann eine veraltete Zustellreservierung zurücknehmen. Historie bleibt erhalten, eine unbekannte Ausführung wird weder als beendet ausgegeben noch blind wiederholt.
- Werkzeuge über den Operationskatalog auffindbar machen und Freigabe, Erreichbarkeit, Ausführung und Quittierung unterscheiden. Empfangene Rückmeldungen belegen keine automatische Aufweckung eines inaktiven Chatfensters.
- Optional ThreadDesk, Wissens-/Dateiübertragung, Teamkoordination und Workflowbelege anbinden. Diese Module sind getrennt; KiraBridge benötigt ThreadDesk nicht für den lokalen Kern. Ein Dateiverweis ist kein Byteimport, eine Übertragung ohne bestätigte dauerhafte Speicherquittung kein erfolgreicher Import.

### Voraussetzungen

Normales Benutzerkonto, **Python 3.11**, **uv 0.11.6**, **GitHub CLI (`gh`)** und Internetzugriff auf GitHub/PyPI. Tatsächlich geprüft ist **Intel x86_64 mit macOS 15.7.4**. Das Modell „iMac 2015“ allein belegt keine Unterstützung eines älteren macOS. Apple Silicon wird im Paket berücksichtigt, ist ohne echte ARM-Abnahme aber nicht als geprüft freigegeben; macOS 26 wird vom Einstieg akzeptiert und bleibt unbestätigt.

Bei privaten Releases muss `gh auth login` erfolgt und der Repositoryzugriff vorhanden sein. Keine Tokens in Befehle, Protokolle oder Git schreiben. Der Installer ändert keine OS-/TCC-Rechte und installiert keinen Paketmanager oder Compiler. Agenten und ihre Konten werden separat eingerichtet. **Keine Apple-Signierung oder Notarisierung**; Gatekeeper nicht pauschal deaktivieren.

### Installation und Update · RC17 Intel

**Diesen einen Befehl im eigenen sichtbaren macOS-Terminal kopieren.** Er lädt den authentifizierten RC17-Installer, prüft SHA-256 und startet erst dann die lokale Installation bzw. Aktualisierung. Die Dateien müssen im verlinkten Release tatsächlich vorhanden sein; ein privater Entwurf erfordert zusätzlich Entwurfszugriff.

```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh --require-visible-terminal --motion full "$@")
```

Der Bootstrap prüft zusätzlich die fest eingebettete SHA-256 des macOS-Pakets. Prüfsummen vom selben Release erkennen Beschädigung, ersetzen keine unabhängige Herausgebersignatur. Kein `curl | sh`. Quellcommit, Prüfergebnisse und endgültige Paketwerte stehen im Release und in [PR43](https://github.com/landjunge/KiraBridge/pull/43).

Der Installer prüft das sichtbare Frontfenster, ausgewählten Tab, TTY und aktuelle Prozessidentitäten vor der Aktivierung. Genau ein eigenes Arbeitsfenster verwenden; keine Eingabe in laufende Codex-/Grok-Sitzungen. `--motion reduced` reduziert Bewegung, `--language en` wählt Englisch. Vollständiger Braille-Schriftzug und Brücke verwenden Pink und Lichtakzente; Ausgabe und Eingaben haben Vorrang, bei ungeeigneter Darstellung gilt ein Text-Fallback.

Erstinstallation legt Benutzerdateien an. Updates erhalten vorhandene Konfiguration, Zugangsdaten, Rechte, Datenbank und Nutzerdateien. Laufende Arbeit, fremde Dienste, veränderte Launcher oder nicht passende Dienstdefinitionen blockieren die Umschaltung. Solche Prüfungen nicht durch Löschen von Queues oder Prozessabbruch umgehen. Neue Berechtigungen werden nicht durch ein Designupdate erteilt.

**Der launchd-Benutzerdienst läuft nach dem Schließen von Terminal- und Browserfenstern weiter.** Anmeldung, Abmeldung, Schlafmodus und Herunterfahren bleiben eigene Systemzustände. Die sichtbare Installation ist vom späteren Hintergrunddienst getrennt.

### Status, Fehler und Rückweg

- Dienstversion und Zustand: `~/.local/bin/kirabridge status`.
- Installierter Quellcommit: `python3.11 KiraBridge/installer/install.py status` aus dem erhaltenen entpackten Paket.
- Neustart erst nach Klärung laufender Arbeit: `launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge`, danach Status erneut lesen.
- Protokolle: `~/.local/share/kirabridge/install/logs/`; Konfiguration/Credentials: `~/.config/kirabridge/`; versionierte Laufzeiten und gesicherter Rückweg: `~/.local/share/kirabridge/install/`.
- Bei falscher Prüfsumme abbrechen. Bei `BUSY` die genannten Aufträge prüfen, nicht blind löschen oder erneut senden. Bei fehlender Sichtbarkeit das eigene Arbeitsfenster prüfen. Ein Timeout ist kein erfolgreicher Start.
- Gesicherten Rückweg aus der Transaktionsmeldung verwenden: `python3.11 KiraBridge/installer/install.py rollback`. Aktuelle Nutzer-/Ergebnisdaten und Zugangsdaten werden nicht blind mit alten Datenbanksicherungen ersetzt. Ein Rückfall muss durch tatsächlich antwortende alte Version bestätigt werden.

[Ausführliche Installation](docs/INSTALL-DE.md) · [macOS-Vertrag](docs/INSTALL-MACOS.md) · [Queueverwaltung](docs/QUEUE-MANAGEMENT.md) · [Releasehinweise](docs/RELEASE-0.8.0rc17.md)

## English

KiraBridge connects an authorized chat to local files, processes and visible agent terminals, with separate durable task, delivery and result evidence. It supports configured Codex/Grok and other provider adapters, discoverable operations, scoped queue management and optional project integrations. ThreadDesk and other vendors are optional. A queued task is not proof of execution; unknown work is never silently replayed or declared stopped. File transfer requires actual bytes and a verified durable receiver receipt before it counts as an import.

[Complete authorized file/log reads](docs/READ-FULL-FILES.md) use original byte pages, offsets, EOF and SHA-256; there is no one-megabyte cap on the overall file.

[Targeted terminal repair and actual Intel evidence](docs/TERMINAL-CONTROL-20261027.md) cover guarded single-line paste into a confirmed empty shell without Return. Definite pre-transport refusal and uncertain transport outcomes remain distinct; busy or changed targets are preserved.

Requirements: normal user account, **Python 3.11, uv 0.11.6, GitHub CLI**, Internet and authenticated access to this private repository/draft. Actual Intel testing used **macOS 15.7.4 x86_64**. Older macOS on a 2015 iMac, macOS 26 and Apple Silicon are not approved by that evidence. Agents and provider accounts require their own setup. No administrator/TCC grants are changed, no compiler is forced. **No Apple signing or notarization**; do not disable Gatekeeper globally.

**Use the single highlighted command above in your own visible macOS Terminal** for first installation or update. It authenticates the private release download, verifies the bootstrap checksum, then verifies the bootstrap's embedded package checksum before local execution. Release notes identify the exact integrated package/source and final acceptance. A draft remains unpublished until GitHub actually publishes it.

Fresh installation creates user-owned state. Updates preserve configuration, credentials, permissions, database and user files. Busy tasks, foreign services and changed definitions stop activation. The installer requires a freshly confirmed visible front window, selected tab, TTY and process identities; reuse one owned window and never type into agent sessions. Full Braille wordmark and bridge use pink/light accents; bounded optional animation yields to real output and prompts. Use `--motion reduced`, `--language en` and Unicode/color/plain-text fallbacks as needed. Human graphics stay outside MCP and status JSON.

**launchd continues running when Terminal or browser windows close.** Check `~/.local/bin/kirabridge status`; the retained package's `installer/install.py status` also reports the installed source. Inspect `~/.local/share/kirabridge/install/logs/` on failure. Do not resolve `BUSY` by killing agents or replaying unknown work. Rollback uses the retained transaction backup and must confirm the responding previous version; it never blindly restores an old database over new results. The original rollback timeout and the subsequent focused passes remain distinct evidence.

[English installation](docs/INSTALL-EN.md) · [Architecture](docs/DEVELOPMENT_PLAN.md) · [Terminal safety](docs/VISIBLE-SELECTION-20261024.md) · [Release notes](docs/RELEASE-0.8.0rc17.md)

## License / Lizenz

[Netzwerkpunkt Personal Use License 1.0](LICENSE).

**Deutsch:** Private, nicht geschäftliche Nutzung ist nach den Lizenzbedingungen kostenlos; geschäftliche Nutzung benötigt gesonderte schriftliche Erlaubnis. Die deutsche Lizenzfassung ist maßgeblich. Dies ist eine individuelle Source-available-Lizenz, keine OSI-anerkannte Open-Source-Lizenz. Diese Zusammenfassung ist keine rechtliche Prüfung. Drittanbieter-Lizenzen bleiben anwendbar.

**English:** Private non-business use is free under the license terms; business use requires separate written permission. The German license text governs. This is a custom source-available license, not an OSI-approved open-source license. This summary does not constitute legal review. Third-party licenses remain applicable.

Lizenzreferenz / Package license reference: `LicenseRef-Netzwerkpunkt-Personal-Use-1.0`.
[License history and existing rights / Lizenzhistorie und bestehende Rechte](docs/LICENSE-HISTORY.md) · [Third-party license inventory and notice requirements / Fremdlizenzen und erforderliche Hinweise](docs/THIRD-PARTY-LICENSES.md).
[DE/EN-Sprachabgleich / Language comparison](docs/LICENSE-LANGUAGE-CHECK.md).
