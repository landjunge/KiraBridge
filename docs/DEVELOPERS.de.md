[English](DEVELOPERS.md) · [README](../README.de.md)

# KiraBridge: Entwicklung und Betrieb

## Quellstand und Release

Der jüngste veröffentlichte Download ist das Intel-Prerelease
[0.8.0rc20 vom 30. Oktober 2026](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20),
Quellpin `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4`. Die READMEs in diesem Arbeitsordner beschreiben diesen veröffentlichten Download.
Der lokale Arbeitszweig `fix/visible-busy-idle-20261021` steht bei `dfbae48` und
ist älter als RC20. Diese Dokumentationsänderung ersetzt oder aktualisiert seinen
Programmcode nicht. Spätere lokale Reparaturzweige sind keine veröffentlichten Downloads.
[Prüfbericht und Belegzuordnung](README-REVIEW-20261031.md).

RC18 bleibt ein veröffentlichtes älteres Prerelease. RC17, RC16 und RC15 sind
Entwürfe; ihre historischen Nachweise bleiben erhalten. GitHub-Release,
Artefakt-Quellpin und tatsächlich antwortender Dienst sind getrennt zu prüfen.

## Architektur und Schnittstellen

MCP und CLI verwenden denselben Bridge-Kern. Die Taskverwaltung speichert
Aufträge und deren Ergebnisse in SQLite. Manager besitzen Dateien, Prozesse,
Agenten, sichtbare Sitzungen und Berechtigungen jeweils getrennt.

- [Architektur](ARCHITECTURE.md) und [Entwicklungsplan](DEVELOPMENT_PLAN.md)
- [Vollständige Datei-/Logreads](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/READ-FULL-FILES.md) und [Dateiübertragung](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/FILE-TRANSFER.md)
- [Queuevertrag](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-MANAGEMENT.md) und [direkte Zulassung](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-DIRECT-ADMISSION-20261029.md)
- [Optionale ThreadDesk-Anbindung](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/DYNAMIC-THREADDESK-PROXY.md)
- [RC20-Änderungen am veröffentlichten Quellpin](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc20/docs/RELEASE-0.8.0rc20.md)

Diese Detaildokumente enthalten datierte Betriebsstände; ihre alten Versionsangaben
ersetzen keinen aktuellen Release- oder Dienstnachweis.

## Konfiguration

Standardkonfiguration und getrennte Credentials liegen unter `~/.config/kirabridge/`.
Die Konfiguration bestimmt Principals, erlaubte Operationen, Dateiwurzeln,
Agentenadapter, sichtbare Zielbindungen und optionale Integrationen. Der aktuelle
Werkzeugkatalog und die Berechtigungsentscheidung der konkreten Operation sind
maßgeblich. Ein vorhandener Modulname bedeutet weder installierten Adapter noch
freigegebene Aktion. [ChatGPT-Einrichtung](CHATGPT.md).

Standardlaufzeiten, Transaktionsbackups und Logs liegen unter
`~/.local/share/kirabridge/install/`; die tatsächlichen Pfade ergeben sich aus dem
installierten Paket/der Konfiguration. Keine fremden Profile oder Shell-Pfade
unbesehen überschreiben. Bestehende KiraBridge-Schlüssel bleiben bis zu einer gesondert freigegebenen
und geprüften Migration erhalten.

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

[Ursachen und Reparaturbelege](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/QUEUE-DIRECT-ADMISSION-20261029.md)
· [Abschlussbericht mit Rückfallplan](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INTEL-RELEASE-20261029.md)

## Tests und Builds

Die Entwicklung erfolgt in isolierten Worktrees. Vor riskanten Änderungen lokal
sichern; passende Tests mit synthetischen Stores, Fake-Terminal-I/O und echten
lokalen MCP-Roundtrips verwenden. Integrationen werden gegen die im CI-Workflow
festgelegten Quellstände geprüft. Review, Merge, Veröffentlichung und produktive Installation bleiben getrennte
Entscheidungen.

Der deterministische Builder `scripts/build_release.py` verlangt einen sauberen
exakten Git-Commit. Zwei Builds müssen dieselben SHA256SUMS ergeben.
`scripts/accept_macos_release.py` prüft echte Installation/Upgrade, Start,
Idempotenz, Restart, KeepAlive, Rollback und Erstinstallation unter einem eigenen
Testlabel. Es ist kein Dry-run und darf keine produktiven Pfade erhalten.
Nach jeder Testdienstbereinigung muss dessen Abwesenheit unabhängig belegt sein.


Für lokale Quellprüfungen gelten `pyproject.toml`, `uv.lock` und
[der CI-Workflow](../.github/workflows/ci.yml):

```sh
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -W error::pytest.PytestUnraisableExceptionWarning
uv build
```

Nur für die Änderung nötige Tests ausführen. Integrationsfälle benötigen die im
Workflow gepinnten externen Quellen über `KIRABRIDGE_TEST_THREADDESK_SOURCE` und
`KIRABRIDGE_TEST_TOLLGATE_SOURCE`; fehlende optionale Abhängigkeiten sind kein
Integrationsnachweis. Eine Dokumentationsprüfung braucht keine produktiven Dienste.

## Betrieb, Updates und Wiederherstellung

[Installationsanleitung](INSTALL-DE.md) und [macOS-Vertrag](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INSTALL-MACOS.md)
enthalten Status-, Log- und Rückwegbefehle. Der launchd-Benutzerdienst läuft nach
dem Schließen von App, Terminal oder Browser weiter. Standarddaten, Laufzeiten,
Backups und Logs liegen unter `~/.local/share/kirabridge/`, die versionierte
Installation unter `install/`. Maßgeblich sind die tatsächlich konfigurierten Pfade.

Der Updater prüft Besitzer, Leerlauf, Integrität und den antwortenden neuen Dienst.
Konfiguration, Credentials, Rechte, Datenbank und Nutzerdateien bleiben erhalten.
Rollback muss die passende Transaktion verwenden und durch die antwortende alte
Version bestätigt sein; keine alte Datenbank über neuere Ergebnisse kopieren.
Prüfsummen aus demselben Release erkennen Beschädigung und ersetzen keine
unabhängige Herausgebersignatur.

Historische Belege: [RC18-Veröffentlichung und Installation](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC18-PUBLISH-INSTALL-20261029.md),
[Intel-Bericht](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/INTEL-RELEASE-20261029.md), [RC14-Rollback](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/docs/RC14-ROLLBACK-20261026.md).
Die Veröffentlichung von RC20 ist kein neuer Nachweis für ARM, macOS 26,
gehostete macOS-CI oder alle ChatGPT-Live-/Voice-Abläufe.
