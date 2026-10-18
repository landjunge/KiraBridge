# KiraBridge

**Vibe Coding mit ChatGPT, Codex und Grok.**  
**Vibe coding with ChatGPT, Codex and Grok.**

## Download & Installation

### Deutsch

**[Zur Installation](docs/INSTALL-DE.md)** · **[ChatGPT verbinden](docs/CHATGPT.md)** · **[Versionsübersicht](https://github.com/landjunge/KiraBridge/releases)**

Noch kein Release-Download veröffentlicht. Der vereinfachte CLI-Weg ist als privater0.6.0rc2 zur Abnahme vorbereitet. Sobald geprüfte Pakete veröffentlicht sind, stehen die direkten Downloads hier oben.

| Weg | Stand |
|---|---|
| Terminal / CLI | Geführte CLI-Installation im privaten RC; kein öffentlicher Download. |
| macOS-App mit Tauri | Geplant; noch kein App-Download verfügbar. |
| Windows-App | Mögliche spätere Erweiterung; noch nicht zugesagt. |
| Linux-App | Mögliche spätere Erweiterung; noch nicht zugesagt. Der vorhandene Linux-CLI-Betrieb ist davon getrennt. |

### English

**[Installation](docs/INSTALL-EN.md)** · **[Connect ChatGPT](docs/CHATGPT.md)** · **[Releases](https://github.com/landjunge/KiraBridge/releases)**

No release download has been published yet. The simpler CLI flow is prepared as a private0.6.0rc2 for acceptance. Direct downloads will appear here at the top when verified packages are published.

| Option | Status |
|---|---|
| Terminal / CLI | Guided CLI installation in private RC; no public download. |
| macOS app with Tauri | Planned; no app download available yet. |
| Windows app | Possible future extension; not committed yet. |
| Linux app | Possible future extension; not committed yet. Existing Linux CLI operation is separate. |

---

**Vibe Coding:** Du besprichst mit ChatGPT, was gebaut oder geändert werden soll.
ChatGPT übergibt die Aufträge über KiraBridge an Codex oder Grok auf deinem
Rechner. Beide können mit eingerichteten Berechtigungen am selben Projekt
arbeiten. Weitere CLI-Anbindungen sind geplant.

**Built for Vibe Coding:** discuss what to build or change with ChatGPT.
ChatGPT delegates through KiraBridge to Codex or Grok on your computer. Both can
collaborate on the same project with configured permissions. More CLI integrations
are planned.

**0.6.0rc2 · private Release-Vorbereitung:** [Installieren DE](docs/INSTALL-DE.md) ·
[Install EN](docs/INSTALL-EN.md) · [Release Notes](docs/RELEASE-NOTES-0.6.0rc2.md).
## Lizenz / License

**Deutsch:** Es gilt die **Netzwerkpunkt Personal Use License 1.0**, eine individuelle Source-available-Lizenz. Private, nicht geschäftliche Nutzung ist kostenlos erlaubt, einschließlich privater Anpassungen und privatem Self-Hosting. Interner Firmeneinsatz, berufliche Nutzung, Weiterverkauf und kostenpflichtige Dienste benötigen eine vorherige schriftliche Erlaubnis beziehungsweise gesonderte Lizenz. Es gibt keine allgemeine Weiterverteilungserlaubnis. Historische Rechte und gesonderte Drittanbieter-Lizenzen bleiben erhalten. [Vollständige Bedingungen](LICENSE).

**English:** The **Netzwerkpunkt Personal Use License 1.0** provides custom source-available terms. Private, non-business use is free, including private modifications and private self-hosting. Internal business or professional use, resale and paid services require prior written permission or a separate license. No general redistribution permission is granted. Historical rights and separate third-party licenses remain intact. [Full terms](LICENSE); the German text governs.

Dies ist keine Open-Source-Standardlizenz; eine anwaltliche Prüfung wurde nicht durchgeführt. / This is not a standard open-source license and has not undergone legal review.

Die Projektseite `kirabridge.netzwerkpunkt.de` bleibt geplant. Noch kein öffentlicher Download und keine Sichtbarkeitsänderung. / The project site remains planned; there is no public download or visibility change.

Die nachfolgenden Betriebsdetails dokumentieren die vorhandene Entwicklerinstallation;
der neue normale Schnellstart verwendet das geprüfte Release-Paket.

Privates, modulares Desktop- und Agenten-Gateway für macOS und Linux. Python 3.11+, asyncio, SQLite und das offizielle MCP Python SDK. Version **0.5.2** ergänzt [konkrete Vorabprüfung und reduzierte Fehlerdiagnose](docs/DIAGNOSTICS-20261018.md) in der bestehenden Audit-Kette. Version0.5.1 ergänzte die begrenzte Bereitschaftsprüfung und zusätzliche reine Lesepfade; Version0.5.0 ergänzte den direkten, dauerhaften [Agentenkanal Codex ↔ Grok](docs/AGENT_CHANNEL.md) mit automatischer Empfängeranbindung. Grundlage bleibt der [Entwicklungsplan](docs/DEVELOPMENT_PLAN.md).

## Implementiert

- Alle elf Module: `bridge_core`, `task_manager`, `agent_manager`, `mcp_gateway`, `terminal_manager`, `filesystem_manager`, `clipboard_manager`, `process_manager`, `security_manager`, `platform_adapters`, `audit_manager`.
- Dauerhafte SQLite-WAL-Warteschlange mit atomarer Freigabeprüfung, Aufgaben- und Empfangs-IDs, Idempotenz, Delegationsketten, Leases, Ereignissen und nachvollziehbarer Wiederherstellung.
- Getrennte Zustände für Empfang, laufende Ausführung und belegten Abschluss. Nach einem Dispatcher-Abbruch bleiben möglicherweise ausgeführte Aufträge `unknown`; sie werden nicht erneut gestartet.
- Codex CLI mit JSONL-Nachweisen; Grok Build über ACP v1; zusätzlicher Grok-API-Adapter für reine Textantworten. Agentenidentitäten und Sitzungen bleiben getrennt.
- Terminal mit sicherem Programmlisten-Standard und ausdrücklich aktivierbarem Betreiber-Vollzugriff, Arbeitsverzeichnisprüfung, begrenzter Ausgabe, Zeitlimits und Beendigung eigener Prozessgruppen. Administratoraktionen verwenden einen gesonderten sichtbaren lokalen macOS-Freigabeweg. [Berechtigungen und Nachweise DE/EN](docs/DEVELOPMENT-ACCESS-20261018.md).
- Dateioperationen mit POSIX-Dateideskriptoren und Schutz gegen Symlink-Pfadausbrüche; atomisches Schreiben; kein rekursives Löschen.
- Unicode-Zwischenablage mit `pbcopy`/`pbpaste`, Wayland oder X11; konfigurierbare Lesefreigaben und Schreibbestätigung durch sofortiges Rücklesen. Keine Überwachung.
- MCP über stdio und Streamable HTTP; authentifizierte parallele HTTP-Clients; ausgehender MCP-Clientpool mit getrennten Verbindungen.
- Adressierte Nachrichten über sieben eigene MCP-Werkzeuge: SQLite-Postfächer, authentifizierte Absender, Gespräche, Quittungen, Idempotenz, begrenzte automatische Empfänger-Turns und keine blinden Wiederholungen nach Neustarts. Bestehende interaktive Sitzungen werden nicht übernommen; verwendet werden separate verwaltete Arbeitssitzungen.
- Optionaler fester [ThreadDesk-Fachadapter / management adapter](docs/THREADDESK-ADAPTER-20261018.md): getrennte Lese-/Schreibrechte, genaue Objektkennungen, Revisionen und wiederabgleichbare Mutationsquittungen. Verwaltung startet keinen Agenten. / Separate read/manage permissions, exact IDs, revision checks and reconcilable receipts; management does not start agents.
- [Zugeordnete Handoffs / correlated workflows](docs/HANDOFF-WORKFLOW-20261018.md) sind im privaten Entwicklungsstand implementiert: exakte Laufbindung, eigene Codex-Fortsetzung nach Rückfrage und zunächst ungeprüfte Inbox-Rückgabe. Dieser Quellstand ist noch kein aktualisierter RC2-Download. / Source-stage workflow integration preserves owned session and return IDs; it does not update the frozen RC2 artifacts.
- Rollenrechte, wahlweise Einzelauftragsfreigaben oder dauerhafte Freigabe erlaubter Funktionen je Zugang, Replay-Schutz, standardmäßig Loopback, TLS-Pflicht für andere Bindungen und verkettetes Audit-Protokoll ohne Befehlsinhalte oder Zugangsdaten.

**Betriebsnachweis:** Codex und Grok haben echte, getrennt nachgewiesene Testaufträge abgeschlossen. Ein echter Codex-MCP-Aufruf und Groks MCP-Handshake wurden geprüft. Der private ChatGPT-Tunnel läuft; der Nutzer meldet eine erfolgreiche Statusabfrage. Die neue lokale Freigabeseite wurde mit einem echten MCP-Dateilistenauftrag bis zum Abschluss geprüft. Windows hat definierte Erweiterungspunkte, noch keinen ausführbaren nativen Adapter. Bilder, Datei-Clipboard, PTY/interactive stdin, A2A und die optionalen externen Integrationen sind Erweiterungen; siehe [Status](docs/STATUS.md).

## Auf diesem Mac bereits eingerichtet

Der lokale Dienst läuft automatisch über launchd auf `127.0.0.1:8765`. Die Standardkonfiguration liegt unter `~/.config/kirabridge/config.toml`; Zugangsdaten liegen separat mit Modus 0600. Als Arbeitsbereich ist `~/workspace/KiraBridge` freigegeben. Codex und Grok sind mit eigenen Identitäten als MCP-Clients registriert.

Der Workspace ist ein Arbeits-/Austauschordner, **kein Git-Checkout**. Der auf
diesem Mac installierte bearbeitbare Quellstand liegt in `~/KiraBridge`.
Nach ausdrücklicher Betreiberfreigabe vom18.10.2026 besitzen `chatgpt` und `local`
regulären Terminal-Vollzugriff mit konfiguriertem PATH und automatischer
Auftragsgenehmigung. Dateiwerkzeuge bleiben auf die vorhandenen Projekte,
`~/Projects`, `~/threaddesk-worktrees` und registrierte Arbeitsstände begrenzt.
`policy.inspect` zeigt die tatsächlich geladene eigene Policy ohne Zugangsdaten;
`agent.status` unterscheidet eigene Bridge-Aufträge und nur beobachtete Prozesse.
Andere Identitäten erhalten dadurch keine globale Terminalfreigabe. Der sichtbare
Administratorweg ist implementiert; bestätigte Root-Ausführung steht noch aus.
[Bedienung, genaue Abnahme und Grenzen DE/EN](docs/DEVELOPMENT-ACCESS-20261018.md).
Dies gilt für den lokalen Quellstand, nicht für den eingefrorenen RC2-Downloadentwurf.

On this Mac, the owner explicitly enabled full regular terminal access for
`chatgpt` and `local`. File-tool roots and other identities remain separately
configured. Safe policy/status operations expose actual loaded settings and
observations. Administrator execution requires local macOS authorization; root
execution has not yet been confirmed. See the linked DE/EN evidence and limitations.

```sh
kirabridge status
kirabridge ls
kirabridge exec -- /bin/ls -la
kirabridge ask codex "Beschreibe deine Aufgabe in einem Satz."
kirabridge ask grok "Beschreibe deine Aufgabe in einem Satz."
kirabridge clipboard info
kirabridge pending
kirabridge approvals
kirabridge approve TASK_ID
kirabridge deny TASK_ID
```

**Aufträge im Browser:** [KiraBridge auf diesem Mac](http://127.0.0.1:8766/). `kirabridge approvals` startet die getrennte lokale Oberfläche und meldet den Browser über eine private Einmal-Anmeldedatei an. Auf macOS liegt anschließend „KiraBridge Freigaben.command“ auf dem Schreibtisch. Anfragen, Ergebnisse und echte Zustandswechsel erscheinen automatisch. Im manuellen Modus lassen sich wartende Anfragen nach dem Öffnen der Auftragsdetails freigeben oder ablehnen; im automatischen Modus ist dieser Schritt nicht nötig. Es müssen keine IDs zwischen Chats kopiert werden.

**Ohne wiederholte Freigabeklicks:** Auf diesem Mac ist für `chatgpt`, `codex`, `grok` und `local` ausdrücklich `approval_mode = "automatic"` eingerichtet. Erlaubte MCP-Anfragen über `task_request` oder `task_submit` kommen direkt in die Warteschlange, ohne Browserklick oder Freigabetoken. `bridge_health` und `operation_catalog` melden den tatsächlich eingerichteten Modus. Die Oberfläche zeigt Aufträge und Ergebnisse weiter an.

Neu angelegte Zugänge verwenden standardmäßig `approval_mode = "manual"`: Ihre Anfragen bleiben bis zur lokalen Freigabe im Zustand `created`. Der Modus wird ausschließlich in der privaten Konfiguration unter `[principals.<zugang>]` gesetzt; `"manual"` stellt die Einzelauftragsfreigabe wieder her. Nach einer Änderung wird der Dienst ohne laufende Aufträge kontrolliert neu gestartet. Anmeldung, Funktionsrechte, erlaubte Programme und Verzeichnisse, Ressourcenlimits und Schutz vor doppelter Ausführung gelten in beiden Modi. MCP-Agenten können den Modus nicht selbst ändern.

Die einmalige ChatGPT-Kontoverbindung wird über `kirabridge chatgpt setup` eingerichtet. Der Assistent öffnet die offiziellen Kontoseiten und fragt einen eingeschränkten Runtime-Schlüssel unsichtbar im lokalen Terminal ab. `kirabridge chatgpt status` unterscheidet installierten Client, Tunnel-Bereitschaft und den weiterhin separat zu prüfenden ChatGPT-Toolaufruf.

## Auf einem neuen Mac einrichten

```sh
uv sync --locked
uv run kirabridge setup
uv run kirabridge service install
uv run kirabridge approvals
```

`setup` erstellt neue private Dateien und überschreibt keine bestehende Policy. Der globale Befehl wird unter `~/.local/bin/kirabridge` angelegt. Für einen manuell begrenzten, einmaligen Betrieb:

## Manuell beginnen

```sh
uv sync --locked
mkdir -p demo-workspace
uv run kirabridge init config.local.toml --workspace "$PWD/demo-workspace"
```

`init` erstellt eine neue Konfiguration mit Modus 0600 und wenigen Rechten. Es ersetzt keine vorhandene Datei. Ohne Konfiguration sind nur Health- und eigene Statusabfragen freigegeben.

Eine konkrete Datei `request.json` anlegen; `path` muss dem absoluten Workspace-Pfad aus `config.local.toml` entsprechen:

```json
{
  "api_version": "1",
  "task_id": "list-1",
  "operation": "file.list",
  "arguments": {"path": "/absolute/path/to/demo-workspace"},
  "idempotency_key": "list-1",
  "parent_id": null
}
```

Den Auftrag lokal ausdrücklich freigeben und ausführen:

```sh
uv run kirabridge --config config.local.toml run request.json --approve
uv run kirabridge --config config.local.toml task list-1
uv run kirabridge --config config.local.toml tasks --state completed
uv run kirabridge --config config.local.toml audit
```

Die erneute Einreichung derselben Anfrage liefert denselben Auftrag zurück. Eine neue ID ist ein neuer Auftrag und benötigt eine neue Freigabe. CLI-Rückgabecodes: 0 abgeschlossener Auftrag, 1 Anfrage-/Konfigurationsfehler, 2 fehlgeschlagen/abgebrochen, 3 unbekannter Ausgang.

## MCP verwenden

```sh
uv run kirabridge --config config.local.toml serve
```

Ein MCP-Client startet diesen Befehl mit stdio; siehe [Client-Konfiguration](examples/mcp-client.json). stdout bleibt dem MCP-Protokoll vorbehalten. Ein Dispatcher besitzt exklusiv sein Zustandsverzeichnis. Für mehrere Clients mit derselben Warteschlange wird ein HTTP-Dispatcher verwendet.

Für HTTP eine eindeutige Umgebungsvariable `token_env` je Principal konfigurieren, einen zufälligen Token mit mindestens 32 Zeichen im lokalen Secret Store hinterlegen und im Prozess bereitstellen. Dann:

```sh
uv run kirabridge --config config.local.toml serve --transport http
```

Endpunkt standardmäßig `http://127.0.0.1:8765/mcp`, Header `Authorization: Bearer …`. Fernbindung erfordert `allow_remote`, Zertifikat, privaten Schlüssel und passende `allowed_hosts`/`allowed_origins`. Eine Fernfreigabe oder Veröffentlichung wurde nicht vorgenommen.

Werkzeuge: `bridge_health`, `operation_catalog`, `task_submit`, `task_request`, `task_get`, `task_list`, `task_events`, `task_cancel`, `agent_inventory`, `clipboard_read`, `clipboard_write`, `clipboard_info`.

Für Ausführungs- und Leseaufträge stellt ein lokaler Bediener eine Freigabe für die **exakte Anfrage** aus:

```sh
uv run kirabridge --config config.local.toml grant request.json
```

Den ausgegebenen Token über einen privaten Kanal an den berechtigten Client geben. Kein MCP-Werkzeug kann Freigaben ausstellen oder Rechte erweitern. `task_submit` nimmt `request` und `approval` entgegen. Die Ausgabe quittiert zunächst die Speicherung; den Ausführungsnachweis liefern `task_get` und `task_events`.

## Prüfen und erweitern

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -W error::pytest.PytestUnraisableExceptionWarning
uv build
uv run python scripts/benchmark_idle.py --seconds 5
```

Tests nutzen temporäre Dateien, eigene Testprozesse und simulierte Agenten. Sie lesen keine persönliche Zwischenablage und führen keine kostenpflichtigen Provideraufträge aus. GitHub CI prüft macOS sowie Linux mit Python 3.11/3.13.

- [Architektur und stabile Schnittstellen](docs/ARCHITECTURE.md)
- [Berechtigungen und Bedrohungsmodell](docs/SECURITY.md)
- [Betrieb, Wiederherstellung und Agentenkonfiguration](docs/OPERATIONS.md)
- [ChatGPT-Anbindung: tatsächliche Anforderungen](docs/CHATGPT.md)
- [Abnahmestand und Testnachweise](docs/STATUS.md)

Es gelten die Nutzungsrechte und Vorbehalte der [LICENSE](LICENSE); das Repository bleibt privat.
