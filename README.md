# KiraBridge 0.8.0rc1

Ein kompaktes Steuerfenster für Kira/ChatGPT, Grok und die angebundenen Agenten.
Auf diesem Mac startet **KiraBridge.app** die Oberfläche. Prozesse, Terminals,
Reparatur-Doktor und Rechte sind direkt erreichbar; nur das Protokoll hat ein
separates Fenster. Die Steuerung bleibt erreichbar, wenn der Bridge-Dienst aus ist.

- **Übersicht:** Kira und Grok eindeutig wählen; bestätigte und ungeprüfte Zugänge erkennen.
- **Prozesse:** tatsächlichen Zustand prüfen, starten und neu verbinden.
- **Terminals:** bestehende Terminal.app- und tmux-Sitzungen auswählen, lesen und bedienen.
- **Doktor:** Verbindungen, geladene Einstellungen und Terminalzugriff prüfen und reparieren.
- **Rechte:** genau **Voll erlaubt**, **Mittel** oder **Nur mit Erlaubnis**.
- **Protokoll:** tatsächliche Nachrichten, Ausführung, Antworten und Fehler verfolgen.

Vorhandene Sitzungen und Zugangsdaten bleiben erhalten. Ein Neustart beendet
keine beobachtete Nutzersitzung. Vollfreigaben werden genutzt; ein Wechsel der
Freigabestufe löscht bereits erteilte Zugriffsrechte nicht. Mittel erlaubt
Leseaufträge automatisch; Änderungen und Ausführung benötigen Freigabe.
Nur mit Erlaubnis lässt neue Aufträge auf die Freigabe im selben Fenster warten.

Browser, Handy, Text, Live und Sprache erreichen dieselben MCP-Werkzeuge und
Rechte, sobald der jeweilige Anbieter den Werkzeugaufruf zulässt.
`connection_check` bestätigt einen tatsächlich angekommenen Aufruf. Gerät und
Modus sind Angaben des aufrufenden Clients. Die Oberfläche zeigt ungeprüfte
Zugänge ausdrücklich als ungeprüft. Native Handy-, Live- und Sprachgespräche
wurden hier nicht direkt abgenommen. Inaktive Chats werden durch eine
Warteschlangennachricht nicht automatisch aufgeweckt.

[Reparaturursachen, tatsächliche Prüfungen und offene Punkte](docs/CONTROL-CENTER-0.8.0rc1.md).

## Starten und entwickeln

Bestehende Installation öffnen:

```sh
kirabridge approvals
```

Aus einem Checkout einrichten:

```sh
uv sync --locked
uv run kirabridge setup
uv run kirabridge service install
uv run python scripts/build_desktop_app.py  # macOS
uv run kirabridge approvals
```

`setup` überschreibt keine vorhandene private Konfiguration. Die native App ist
ein Begleitfenster zur lokalen Installation. Andere Systeme verwenden den Browser.
Konfiguration und Zugangsdaten liegen getrennt unter `~/.config/kirabridge`.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -W error::pytest.PytestUnraisableExceptionWarning
uv build
```

GitHub CI prüft macOS und Linux mit Python 3.11/3.13. Tests verwenden isolierte
Dateien und Testprozesse; sie starten keine kostenpflichtigen Provideraufträge.

## Schnittstellen und Nachweise

MCP-Clients verbinden sich mit `kirabridge --principal NAME connect`. Der lokale
Dispatcher besitzt die gemeinsame Warteschlange. Aufträge über `action_request`
liefern zunächst ihren gespeicherten Zustand; `task_get`, `task_events` und der
Abschlusskanal liefern die tatsächlichen Ausführungsbelege. `message_receive` und
`message_ack` unterscheiden Zustellung und Quittierung von der Verarbeitung.
`session_catalog` liefert konkrete Terminalziele; `session_read`, `session.input`
und `session_open` lesen, bedienen oder öffnen sie unter der aktuellen Freigabe.

- [Grok-App-Verbindung](docs/GROK-APP-CONNECTOR.md)
- [ChatGPT-Verbindung](docs/CHATGPT.md)
- [Abschlussmeldungen und Rückgabe](docs/COMPLETION-CHANNEL-20261019.md)
- [Architektur](docs/ARCHITECTURE.md)
- [Betrieb und Wiederherstellung](docs/OPERATIONS.md)
- [Agentennachrichten](docs/AGENT_CHANNEL.md)
- [CLI-Anbieter](docs/providers/README.md)
- [ThreadDesk-Anschluss](docs/THREADDESK-ADAPTER-20261018.md)

Ältere datierte Abnahmeberichte dokumentieren ihren damaligen Stand.
Aktuelle Rechte und Zustände zeigt die laufende Steuerung.
Das Repository bleibt privat. Es gilt die [Lizenz](LICENSE).
