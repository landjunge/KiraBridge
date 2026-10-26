# KiraBridge

[English](#english) · [Deutsch](#deutsch) · [Published RC14 / veröffentlichtes RC14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14)

KiraBridge connects an authorized AI conversation to local files, visible agent terminals and optional project tools. KiraBridge verbindet einen berechtigten KI-Chat mit lokalen Dateien, sichtbaren Agententerminals und optionalen Projektwerkzeugen.

## Tatsächlicher Stand / Actual status

- **Published / Veröffentlicht:** `0.8.0rc14`. RC15, RC16 and RC17 remain drafts; a draft is not a published release.
- **Operator Mac / Betreiber-Mac:** `0.8.0rc17`, installed source `14468ad5e7b28be1c1c4312d2f4517582dbc7701`. The service runs independently under launchd. This is distinct from this development branch and from the published release.
- **This branch / Dieser Branch:** continues the existing Braille design and installer integration. Final package, merge and release acceptance must be recorded for its exact source commit; older test evidence does not approve a new build.
- **Real Intel proof / Echter Intel-Nachweis:** macOS 15.7.4, Python 3.11.15, source `14468ad`: 1,522 tests passed, one optional AA-source test skipped. Original RC14 package acceptance failed at rollback readiness; focused rollback tests, including restart/crash/KeepAlive history, subsequently passed. Both results remain documented. These are local Intel results, not successful hosted Actions or ARM tests.
- **Open gates / Offene Gates:** hosted macOS CI cannot start because of GitHub billing; no Apple Silicon test machine is verified. Failed/missing checks remain open. No new release or installation of the Braille design is claimed here.

[Actual Mac test evidence](docs/evidence/local-macos-acceptance-14468ad-20261026.json) · [Focused rollback evidence](docs/RC14-ROLLBACK-20261026.md) · [Braille design and limits](docs/TERMINAL-DESIGN-PREVIEW.md) · [Reuse and acceptance plan](docs/BRAILLE-INSTALLER-PLAN-20261026.md)

## Deutsch

### Was KiraBridge kann

- Berechtigte Datei-, Prozess- und Terminaloperationen aus einem verbundenen Chat ausführen, mit nachvollziehbarem Ergebnis statt bloßer Annahmebestätigung.
- Codex-, Grok- und weitere eingerichtete Agentenadapter verwenden. Anbieterzugänge, Modelle und laufende Sitzungen werden nicht durch KiraBridge ersetzt.
- Sichtbare Terminalfenster frisch katalogisieren und lesen; Eingaben an bestätigte Fenster-/Tab-/TTY-/Prozessidentitäten binden. `submit=false` bedeutet Einfügen ohne Return. Bei echter Aktivität, geänderter Zuordnung oder unbekannter Eingabe verweigert die Bridge den Eingriff.
- Berechtigte Warteschlangen vollständig einsehen und gezielt verwalten. `withdraw` nimmt unbekannte Ausführungen aus der aktiven Ansicht; ein belegter `retire` kann eine veraltete Zustellreservierung zurücknehmen. Historie bleibt erhalten, eine unbekannte Ausführung wird weder als beendet ausgegeben noch blind wiederholt.
- Werkzeuge über den Operationskatalog auffindbar machen und Freigabe, Erreichbarkeit, Ausführung und Quittierung unterscheiden. Empfangene Rückmeldungen belegen keine automatische Aufweckung eines inaktiven Chatfensters.
- Optional ThreadDesk, Wissens-/Dateiübertragung, Teamkoordination und Workflowbelege anbinden. Diese Module sind getrennt; KiraBridge benötigt ThreadDesk nicht für den lokalen Kern. Ein Dateiverweis ist kein Byteimport, eine Übertragung ohne bestätigte dauerhafte Speicherquittung kein erfolgreicher Import.

### Voraussetzungen

Normales Benutzerkonto, **Python 3.11**, **uv 0.11.6**, **GitHub CLI (`gh`)** und Internetzugriff auf GitHub/PyPI. Tatsächlich geprüft ist **Intel x86_64 mit macOS 15.7.4**. Das Modell „iMac 2015“ allein belegt keine Unterstützung eines älteren macOS. Apple Silicon wird im Paket berücksichtigt, ist ohne echte ARM-Abnahme aber nicht als geprüft freigegeben; macOS 26 wird vom Einstieg akzeptiert und bleibt unbestätigt.

Bei privaten Releases muss `gh auth login` erfolgt und der Repositoryzugriff vorhanden sein. Keine Tokens in Befehle, Protokolle oder Git schreiben. Der Installer ändert keine OS-/TCC-Rechte und installiert keinen Paketmanager oder Compiler. Agenten und ihre Konten werden separat eingerichtet. **Keine Apple-Signierung oder Notarisierung**; Gatekeeper nicht pauschal deaktivieren.

### Installation und Update: geprüfter RC17-Reviewstand

Der folgende eine Befehl lädt das **bereits vorhandene, geprüfte Paket aus Quelle `14468ad`**, nicht einen ungeprüften neuen Designbuild. Anmeldung und Zugriff auf den privaten RC17-Entwurf sind erforderlich. Im sichtbaren macOS-Terminal ausführen; der Befehl eignet sich für Erstinstallation und Update dieses Reviewstands:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'KiraBridge-macos-14468ad-review.tar.gz*' -D "$d" && (cd "$d" && shasum -a 256 -c KiraBridge-macos-14468ad-review.tar.gz.sha256 && tar -xzf KiraBridge-macos-14468ad-review.tar.gz && sh KiraBridge/install.sh)
```

Der authentifizierte Download-/Prüf-/Installationsablauf wurde auf dem Betreiber-Mac tatsächlich ausgeführt. Das gebaute Paket wurde separat isoliert geprüft. Das ist kein Nachweis eines vollständigen Neuinstallationslaufs genau dieses Einzeilers in einer frischen Maschine und keine Freigabe des neuen Designs. Prüfsummen vom selben Release erkennen Beschädigung, sind keine unabhängige Herausgebersignatur. Kein `curl | sh`.

Der neue Installer verwendet denselben versionierten Updatepfad. Nach seiner eigenen Paketabnahme ist `sh KiraBridge/install.sh --require-visible-terminal` der lokale Einstieg: bestätigtes vorhandenes sichtbares Terminal, frische Fenster-/Tab-/TTY-/Prozessprüfung vor Aktivierung, kein versteckter Ersatz. Für die Betreiberarbeit wird ein einziges eigenes bestätigtes Arbeits-/Installationsfenster wiederverwendet; keine Eingabe in laufende Codex-/Grok-Sitzungen.

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

Requirements: normal user account, **Python 3.11, uv 0.11.6, GitHub CLI**, Internet and authenticated access to this private repository/draft. Actual Intel testing used **macOS 15.7.4 x86_64**. Older macOS on a 2015 iMac, macOS 26 and Apple Silicon are not approved by that evidence. Agents and provider accounts require their own setup. No administrator/TCC grants are changed, no compiler is forced. **No Apple signing or notarization**; do not disable Gatekeeper globally.

Use the single highlighted command above for the existing reviewed `14468ad` package. It authenticates the download and checks SHA-256 before execution; it does not install the unfinished Braille candidate. The download/check/install flow really ran on the operator Mac, while built-package isolation was tested separately. No claim is made that this exact one-line command passed full fresh-machine acceptance. Published RC14, RC17 draft assets, installed RC17 and current source are different states.

Fresh installation creates user-owned state. Updates preserve configuration, credentials, permissions, database and user files. Busy tasks, foreign services and changed definitions stop activation. The future accepted design package uses the same installer and can require a freshly confirmed visible Terminal window with `--require-visible-terminal`; there is no hidden fallback. Operator work reuses one confirmed owned work/install window and never types into running agent sessions. The Braille renderer reuses the existing design; its bounded optional animation must yield to real output/prompts, with static reduced-motion and Unicode/color/plain-text fallbacks. Human presentation stays outside MCP and status JSON.

**launchd continues running when Terminal or browser windows close.** Check `~/.local/bin/kirabridge status`; the retained package's `installer/install.py status` also reports the installed source. Inspect `~/.local/share/kirabridge/install/logs/` on failure. Do not resolve `BUSY` by killing agents or replaying unknown work. Rollback uses the retained transaction backup and must confirm the responding previous version; it never blindly restores an old database over new results. The original rollback timeout and the subsequent focused passes remain distinct evidence.

[English installation](docs/INSTALL-EN.md) · [Architecture](docs/DEVELOPMENT_PLAN.md) · [Terminal safety](docs/VISIBLE-SELECTION-20261024.md) · [Release notes](docs/RELEASE-0.8.0rc17.md)

## License / Lizenz

[Netzwerkpunkt Personal Use License 1.0](LICENSE). Private non-business use is free under its terms; business use requires separate written permission. German governs. This is a source-available license, not an OSI approval or legal review. Third-party licenses remain applicable.
