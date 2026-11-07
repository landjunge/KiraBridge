[English](DEVELOPERS.md) · [README](../README.de.md)

# KiraBridge: Entwicklung und Betrieb

## Quellstand und Release

Geprüft am 7. November 2026: Die Repositorybasis `d12838ae97c7efcc053c45c3bc9fba5e78f5fe5d`
führt `0.8.0rc40` in `pyproject.toml`, `uv.lock` und dem Pythonpaket.
Die installierte Intel-Laufzeit meldet diesen Quellpin. Der jüngste veröffentlichte
Intel-Download bleibt [RC36](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36),
Quelle `d4aebdd89a206045731f2692a3f363fddaa15ee0`. Sein authentifiziert geladener
Installer stimmt mit GitHubs Digest und `SHA256SUMS` überein.
[Prüfung, Quellen und verbleibende Grenzen](evidence/readme-current-20261107.json).

Die separate [Windows-Einrichtungsvorschau](WINDOWS-SETUP-20261104.md) trägt `0.8.0rc37.dev1`;
sie belegt weder Funktionsgleichstand noch einen Windows-Dienstinstaller. Laufende
Windows-/Installer- und Linux-/Debian-Serverarbeit bleibt von diesen Downloads getrennt.
RC17, RC16 und RC15 sind weiterhin Entwürfe. Releasezustand, Artefaktquelle und
antwortenden Dienst getrennt prüfen; die Versionsnummer allein identifiziert keinen Build.

## Entwicklereinstieg

Benötigt werden Git, Python **ab 3.11** (`requires-python`) und uv; CI pinnt uv **0.11.6**.
Das private Repository benötigt GitHub-Zugriff. In einem separaten Checkout:

```sh
git clone https://github.com/landjunge/KiraBridge.git
cd KiraBridge
uv sync --locked --dev
uv run --locked kirabridge --version
uv run --locked kirabridge --help
```

Die letzten beiden Befehle geben Version/Hilfe aus und konfigurieren oder starten
keinen Dienst. `uv sync` erstellt die `.venv` dieses Checkouts und aktualisiert keine
installierte KiraBridge. Laufzeitabhängigkeiten: MCP, HTTPX und Uvicorn sowie
Cryptography auf Intel-macOS. Die Dev-Gruppe ergänzt pytest, pytest-asyncio und Ruff.
Die exakten Auflösungen stehen in `uv.lock`.

| Verzeichnis | Zweck |
| --- | --- |
| `src/kirabridge/` | Pythonkern, CLI, MCP-Gateway, Manager und Plattformadapter |
| `tests/` | Unit-, Vertrags- und Integrationsprüfungen |
| `installer/` | Versionierte Installation, Update und Rollback |
| `scripts/` | Paketbau, native Abnahme und CI-Helfer |
| `docs/`, `examples/`, `integrations/` | Verträge, Beispiele und optionale Integrationen |

## Architektur und Schnittstellen

MCP und CLI verwenden denselben Bridge-Kern. Die Taskverwaltung speichert
Aufträge und deren Ergebnisse in SQLite. Manager besitzen Dateien, Prozesse,
Agenten, sichtbare Sitzungen und Berechtigungen jeweils getrennt.

- [Architektur](ARCHITECTURE.md) und [Entwicklungsplan](DEVELOPMENT_PLAN.md)
- [Vollständige Datei-/Logreads](READ-FULL-FILES.md) und [Dateiübertragung](FILE-TRANSFER.md)
- [Queuevertrag](QUEUE-MANAGEMENT.md) und [direkte Zulassung](QUEUE-DIRECT-ADMISSION-20261029.md)
- [Optionale ThreadDesk-Anbindung](DYNAMIC-THREADDESK-PROXY.md)
- [Begrenzte Whiteboard-Fortsetzung](plans/BIGPLAN-AUTONEXT-20261104.md): gepinnte READY-Aufträge, Abnahmequittungen und Aktivierungsgates; standardmäßig deaktiviert.
- [Veröffentlichte RC36-Änderungen](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc36/docs/RELEASE-0.8.0rc36.md)

Diese Detaildokumente enthalten datierte Betriebsstände; ihre alten Versionsangaben
ersetzen keinen aktuellen Release- oder Dienstnachweis.

## Konfiguration

Standardkonfiguration und getrennte Credentials liegen unter `~/.config/kirabridge/`.
Die Konfiguration bestimmt Principals, erlaubte Operationen, Dateiwurzeln,
Agentenadapter, sichtbare Zielbindungen und optionale Integrationen. Der aktuelle
Werkzeugkatalog und die Berechtigungsentscheidung der konkreten Operation sind
maßgeblich. Ein vorhandener Modulname bedeutet weder installierten Adapter noch
freigegebene Aktion. [ChatGPT-Einrichtung](CHATGPT.md).

Keine fremden Profile oder Shell-Pfade unbesehen überschreiben. Bestehende
KiraBridge-Schlüssel bleiben bis zu einer gesondert freigegebenen und geprüften
Migration erhalten. Die Betriebspfade stehen unten.

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

[Ursachen und Reparaturbelege](QUEUE-DIRECT-ADMISSION-20261029.md)
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


Für Codeänderungen die gelockte Dev-Umgebung synchronisieren, Ruff und nur die
betroffenen vorhandenen Testdateien ausführen (Testpfad passend ersetzen):

```sh
uv sync --locked --dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q tests/test_cli_support.py -W error::pytest.PytestUnraisableExceptionWarning
```

Reine Dokumentation benötigt gezielte Link-, Markdown-, Sprach- und Beispielprüfungen;
keinen Produktbuild und keinen lokalen Gesamtsuitenlauf.
Der [Verify-Workflow](../.github/workflows/ci.yml) führt bei Push/PR weiterhin die
nötigen Lint-/Testprüfungen und `uv build` aus. Automatische Jobs nutzen die bestehenden
selbstgehosteten Linux-Runner für Python 3.11/3.13; gehostete macOS- und Paketprüfungen
benötigen manuelle Auswahl. [CI-Auswahl, Kosten und Plattformgrenzen](CI-COST-GATES-20261106.md).


Die erste [PR71-Prüfung vom 7. November](https://github.com/landjunge/KiraBridge/actions/runs/42365946670)
scheiterte an abgelaufenen Routing-Testfixtures und zusätzlichen Python-3.13-Fehlern.
Die vorhandene, unabhängig geprüfte feste Testuhr aus dem Serverbranch wird jetzt
wiederverwendet; produktive Frischeprüfungen und echte Prozesszeitlimits bleiben erhalten.
Die [aktuellen PR-Checks](https://github.com/landjunge/KiraBridge/pull/71/checks) sind
weiterhin Integrationsgate. [Originalfehler, gezielte Prüfungen und Quellpins](evidence/readme-current-20261107.json).

Vollständige Integrationsreproduktion benötigt `uv sync --locked --dev --group remote-ci`
und die exakten externen Checkouts unten. CI verwendet `scripts/ci_remote_tests.py`
in getrennten frischen Legacy-/Remoteprozessen mit gebundenen Importen, Pins und Ergebnissen:

| Prüfzweig | Quellen und Umgebung |
| --- | --- |
| Legacy | ThreadDesk `770bbc9f0c0a02699cc93cad47d2e2c3782f7080`, `KIRABRIDGE_TEST_THREADDESK_SOURCE=<checkout>/src`; TollGate `53fc57cc2e082d022e65e5929cb2a1e186fba852`, `KIRABRIDGE_TEST_TOLLGATE_SOURCE=<checkout>` |
| Remote R2/R3 | ThreadDesk M4 `a0dd4c39478b031e0e31d335c2a15435dfbc52eb`; `KIRABRIDGE_TEST_THREADDESK_SOURCE` und `KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE` zeigen auf dessen `src/`; keine Legacy-TD-/TollGateimporte |

Exakte `PYTHONPATH`-, Temp-/Reportpfade und Helferargumente stehen im Workflow;
siehe außerdem [Remote-CI-Pingate](REMOTE-CI-PIN-GATE-20261106.md).
Fehlende optionale Quellen oder übersprungene Prüfungen belegen keine Integrationsabnahme.
Eine Dokumentationsprüfung braucht keinen produktiven Dienst.

## Betrieb, Updates und Wiederherstellung

[Installationsanleitung](INSTALL-DE.md) und [macOS-Vertrag](INSTALL-MACOS.md)
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
Die Veröffentlichung von RC36 ist kein neuer Nachweis für ARM, macOS 26,
gehostete macOS-CI oder alle ChatGPT-Live-/Voice-Abläufe.
