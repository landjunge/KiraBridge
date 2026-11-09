# CLI-Discovery Phase 1: Bestandsabgleich

Stand: 08.11.2026, 17:55–18:15 Uhr (Berlin). Paket **BP-CLI-02 Phase 1**
(Discovery, Gesamtplan 9.5). Lane L2. Nur lesend.

Grundlage ist **G9.9-E2**: Acht CLIs sind verbindlich. Das sind Codex, Grok Build,
Claude Code, OpenCode, Gemini CLI, GitHub Copilot CLI, Cursor CLI und Aider.
`grok_api` ist keine CLI. Es wird hier getrennt als API-Weg geführt.
Die Kennung folgt Bauplan v2, Nachtrag N1. Gesamtplan 9.9 liegt noch als PR #94 offen.

Maschinenlesbar: [`cli-discovery-phase1-20261108.json`](cli-discovery-phase1-20261108.json).

## Rahmen der Erhebung

- Gerät: Intel-Mac, x86_64, macOS 15.7.4 (24G517). Codebasis: `origin/main` 405797c.
- Ausgeführt wurden nur `--version`, `--help`, Login-Status-Befehle und Listen.
  Dazu kam das Lesen von Konfigurationsdateien. Ausgegeben wurden nur Schlüsselnamen,
  keine Werte.
- **Keine Modellaufrufe. Keine Anmeldung angestoßen. Die KiraBridge-Runtime wurde nicht verändert.**
- Eine Nebenwirkung: `grok models` hat das gespeicherte Grok-OIDC-Token erneuert.
  Die Datei `~/.grok/auth.json` wurde dabei vom CLI neu geschrieben. Das ist normales
  CLI-Verhalten. Der Aufruf wurde nicht wiederholt.
- Der laufende Dienst (`com.kirabridge.bridge`, Port 8765) wurde nicht per MCP abgefragt.
  Ein GET ohne Anmeldung blieb nach 5 s ohne Antwort. Das Agenteninventar des Dienstes
  bleibt deshalb UNKNOWN. Die Konfiguration stammt aus `~/.config/kirabridge/config.toml`.
- Umgebungsvariablen wurden nur in der Prüfshell gelesen. Die Umgebung des Dienstes
  (launchd) bleibt UNKNOWN.

## Begriffe

| Begriff | Bedeutung |
|---|---|
| **registriert** | Die Adapterart steht im Code (`AgentManager` oder `AdapterRegistry`). |
| **verfügbar** | Das Binary ist da und der Zugang ist für die konfigurierte Route belegt. |
| **erfolgreich ausgeführt** | Im Repo liegt ein Beleg für einen echten erfolgreichen Lauf. Sonst UNKNOWN oder nein. |

## Tabelle 1: Installation, Konfiguration, Anmeldung

| CLI | Pfad (PATH → Ziel) | Version heute | Matrix 05.11. | KiraBridge-Konfig | Angemeldet | Beleg |
|---|---|---|---|---|---|---|
| Codex | `~/.local/bin/codex` → `~/.codex/packages/standalone/releases/0.167.0-…/codex` | 0.167.0 | 0.166.0 | `agents.codex` (`codex`, full access), sichtbare Bindung, Team | **ja** | `codex login status`: ChatGPT |
| Grok Build | `~/.grok/bin/grok` → `~/.grok/downloads/grok-1.0.78-macos-x86_64` | 1.0.78 | 1.0.77 | `agents.grok` (`grok_acp`, `~/.local/bin/grok` → gleiches Ziel), sichtbare Bindung, Team, Connector | **UNKNOWN** | `grok models`: „not authenticated“, gespeicherter OIDC-Login wurde aber erneuert |
| Claude Code | `~/.local/bin/claude` → `~/.local/share/claude/versions/2.1.319` | 2.1.319 | 2.1.236 | `agents.claude` (`claude_code`) nutzt **`/usr/local/bin/claude` = Cask 2.1.236**; Team mit `separate_managed_session` | **ja** (beide) | `claude auth status --json`: loggedIn, claude.ai, firstParty, pro |
| OpenCode | `/usr/local/bin/opencode` → Cellar 1.4.4 | 1.4.4 | 1.4.4 | `agents.opencode`, Modell `ollama/kirabridge-team:latest`, Loopback | für die Route nicht nötig | Ollama läuft, Modell vorhanden; 5 gespeicherte Cloud-Zugänge (Kostenwege, ungenutzt) |
| Gemini CLI | `/usr/local/bin/gemini` → Cellar 0.37.2 | 0.37.2 | 0.37.2 | `agents.gemini` (`gemini_cli`) | **UNKNOWN** | kein lokaler Statusbefehl; OAuth-Datei da, `settings.json` fehlt; 19.10.: `IneligibleTierError` |
| Copilot CLI | `/usr/local/bin/copilot` → Cask `copilot-cli@prerelease/1.0.66-1` | 1.0.67 | 1.0.67 | `agents.copilot` (`copilot_cli`) | **UNKNOWN** | keine eigene Anmeldung in `~/.copilot/config.json`; `gh` angemeldet (Scope `copilot`) |
| Cursor CLI | `~/.local/bin/cursor-agent` → `~/.local/share/cursor-agent/versions/2026.08.11-e8db854` | 2026.08.11-e8db854 | gleich | **kein Eintrag** | **ja** | `cursor-agent status`: „Logged in (unable to fetch user details)“ |
| Aider | nicht gefunden | – | – | kein Eintrag | entfällt | PATH, pipx, uv tools, Python-Modul geprüft |
| *grok_api* (API) | `https://api.x.ai/v1/chat/completions` | – | – | **kein Agent** mit `kind = "grok_api"` | entfällt | `XAI_API_KEY` in der Prüfshell nicht gesetzt; Dienst UNKNOWN |

## Tabelle 2: Discovery, Code, Tests, Status

Pfadkürzel: `AM` = `src/kirabridge/agent_manager`, `UI` = `src/kirabridge/cli_adapters`.

| CLI | Maschinenlesbare Discovery | Provider (`AM`) | UI-Adapter (`UI`) | Tests | registriert | verfügbar | erfolgreich ausgeführt |
|---|---|---|---|---|---|---|---|
| Codex | `exec --json`, `app-server generate-json-schema` (experimentell), `mcp`, `doctor` | `__init__.py` `CodexAdapter` | `codex.py`, `codex_menus/return/slash/echo.py` | `test_full_access`, `test_cli_adapter_contract`, `test_codex_*`, Routing-Tests | ja | ja | **ja, historisch** (Gesamtplan §4); 0.167.0 nicht neu belegt |
| Grok Build | `--output-format json/streaming-json`, `--json-schema`, `models`, `inspect`, `mcp`, ACP (`agent stdio`) | `__init__.py` `GrokACPAdapter`, `grok_structured.py` | `grok.py`, `grok_echo.py` | `test_grok_structured`, `test_grok_protocol_probe`, `test_grok_single_row_paste`, `test_agents` | ja | UNKNOWN | **ja, historisch** (`docs/cli-routing/evidence/grok-live-receipt.json`, 05.11.) |
| Claude Code | `--output-format json/stream-json`, `--input-format stream-json`, `--json-schema`, `auth status --json`, `mcp` | `claude.py` (nur Text, Safe Mode), `full_access.py` | **keiner** | `test_claude_adapter` (10), `test_cli_provider_integration`, `test_cli_support`, `test_full_access` | ja | ja | **UNKNOWN**: kein Erfolgsbeleg im Repo |
| OpenCode | `run --format json`, `models`, `acp`, `mcp`, `serve`, `export` | `opencode.py`, `full_access.py` | keiner | `test_opencode_adapter` (18) und weitere | ja | ja | **ja, historisch** (19.10., `cli-opencode-mcp-20261019-01`, Modell `kirabridge-text`) |
| Gemini CLI | `-o json/stream-json`, `--acp`, `mcp`, `extensions`, `skills`, `hooks` | `gemini.py`, `full_access.py` | keiner | `test_gemini_adapter` (15) und weitere | ja | UNKNOWN | **nein** (19.10.: unknown, danach Kontosperre) |
| Copilot CLI | `--output-format json`, `--acp`, `mcp`, `help config/environment` | `copilot.py`, `full_access.py` | keiner | `test_copilot_adapter` (11) und weitere | ja | UNKNOWN | **nein** (19.10.: nicht angemeldet, null Prompts) |
| Cursor CLI | `--print --output-format json/stream-json`, `models`/`--list-models`, `mcp`, `create-chat`, `about` | **keiner** | keiner | nur Matrix-Eintrag in `test_capability_routing` | **nein** | ja (Binary, Login) | nein |
| Aider | – | keiner | keiner | nur Matrix-Eintrag | nein | nein | nein |
| *grok_api* | HTTP-API, kein CLI | `__init__.py` `GrokAPIAdapter` | – | `test_agents` (Fake-Server) | ja | nein (nicht konfiguriert) | UNKNOWN; nicht getestet wegen API-Kosten |

Keine der acht CLIs hat eine offizielle JSON-Hilfe für ihre Befehle. Maschinenlesbar
sind die Ausgabeformate, MCP, ACP und bei Codex ein Protokollschema. Discovery
für den Werkzeugkatalog muss deshalb versionsgebunden pro Adapter erfolgen.
Freie Help-Texte werden nicht ausgeführt (Gesamtplan 9.4 Nr. 1).

## Klärung W2: Wie viele Adaptertypen?

- `AgentManager` registriert **acht Arten**: `codex`, `grok_api`, `grok_acp`,
  `grok_structured`, `opencode`, `gemini_cli`, `claude_code`, `copilot_cli`
  (`AM/__init__.py`). Die Angabe „sieben“ in 9.7 W2 ist veraltet.
  `grok_structured` kam dazu.
- Diese acht Arten decken **sechs CLIs** ab. Grok hat drei Wege. Cursor und Aider fehlen.
- `AdapterRegistry` für die sichtbare UI-Semantik kennt nur **Codex und Grok** (`UI/__init__.py`).
- Der Router (`src/kirabridge/capability_routing/router.py`) kennt alle acht CLI-Namen.
  Die native Routingtabelle kennt nur Codex und Grok (`capability_routing/native.py`).
- Die „neun“ vom 07.11. bleiben unbelegt. Das passt zu „acht CLIs plus `grok_api`“.

## Befunde und Lücken

1. **Claude Code hat zwei Installationen.** KiraBridge startet die Cask-Version 2.1.236
   (`/usr/local/bin/claude`). Auf dem PATH liegt 2.1.319. Alle Adapterflags gibt es in
   beiden Versionen (`--help` geprüft). Beide melden dieselbe Anmeldung.
2. **Claude Code hat keinen Erfolgsbeleg.** Am 19.10. war der Status `loggedIn=false`.
   Commit 47ea958 (08.11.) behebt „Not logged in“ bei verwalteten Läufen über USER/LOGNAME.
   Ob der laufende Dienst diesen Fix schon geladen hat, ist UNKNOWN.
3. **Der Grok-Login ist widersprüchlich.** `grok models` meldet „not authenticated“.
   Gleichzeitig wurde der gespeicherte Login erneuert. Ein Folgelauf ohne Modellkosten
   (z. B. `grok usage`) könnte das klären. Er wurde bewusst nicht ausgeführt, um nicht
   erneut Credentials zu schreiben.
4. **Der PATH-Name `agent` gehört Grok, nicht Cursor.** `~/.grok/bin/agent` steht vor
   `~/.local/bin/agent`. Ein Cursor-Adapter muss den expliziten Pfad zu `cursor-agent` nutzen.
5. **OpenCode hat gespeicherte Kostenwege.** Hinterlegt sind OpenCode Zen, DeepSeek,
   OpenRouter, MiniMax und Nvidia. Die KiraBridge-Route nutzt nur lokales Ollama.
   Ein Adapter darf keinen dieser Cloudwege implizit wählen.
6. **Gemini ist kontobedingt gesperrt** (Stand 19.10.). Es gibt keinen lokalen Statusbefehl.
   Eine Prüfung ohne Modellturn ist nur über die native Null-Turn-Diagnose möglich.
   So war es am 19.10.
7. **Copilot hat keine eigene Anmeldung.** Ein `gh`-Token mit Scope `copilot` existiert.
   Ob er für das isolierte Profil verwendet werden darf, ist eine Freigabefrage.
8. **Full-Access-Pfad** (`AM/full_access.py`): Für Claude läuft er mit
   `bypassPermissions` und KiraBridge-MCP im echten Arbeitsordner. Er lädt Nutzer-
   einstellungen. Die konfigurierten Agenten haben `bridge_tools` und `allow_local_tools`.
   Mit einem Principal mit Berechtigungsstufe wird dieser Weg statt des Textadapters gewählt.
9. **Lokale Testläufe sind instabil.** Zwei Läufe der zehn Adapter-/Routingtestdateien
   ergaben 202/11 und 201/12 (bestanden/fehlgeschlagen). Die Fehlschläge wechseln.
   Ursache ist `process_cleanup_unknown` („Owned process session cannot be confirmed“)
   bei einer Load Average von 80–120. Isoliert besteht `test_grok_structured` 10/10.
   Das ist umgebungsbedingt. Maßgeblich ist CI.
10. **Die Matrix vom 05.11. läuft am 12.11. ab.** Die Versionen von Codex, Grok und
    Claude haben sich seitdem geändert.
11. **Zwei Pakete heißen BP-CLI-02.** Im Gesamtplan 9.5 ist es die Discovery. Im
    Bauplan v2 ist es Welle 2 (Gemini, Cursor). Vorschlag: Die Discovery-Stufen heißen
    **BP-CLI-02-DISC-1/2/3**. Die Wellen behalten BP-CLI-01/02/03.

## Nächste Adapterpakete (priorisiert)

Reihenfolge nach Bauplan v2 und G9.9-E6. Kein Paket ist damit gestartet.
Jedes braucht seine eigene Freigabe.

| Nr. | Paket | Inhalt | Abnahme | Schätzung |
|---|---|---|---|---|
| 1 | **BP-CLI-01 Welle 1: Claude Code** | Pfad festlegen: `agents.claude.executable` auf die gepflegte Version (2.1.319) oder bewusst Cask pinnen. Version und Login automatisch ohne Modellkosten erfassen (`--version`, `auth status --json`). Kleinste echte Route: ein text-only-Turn über den verwalteten Weg, mit Freigabe. UI-Adapter in `cli_adapters` als drittes Modul (Eingabe, Return, Antwort, Abbruch, Rückkehr). | Ein belegter Lauf je Route. Negativtests. Kein Full-Access-Lauf ohne eigene Freigabe. | 1,5–2,5 Tage |
| 2 | **BP-CLI-02-DISC-2 Discovery mit Schema** | Gemeinsame Abfrage `cli.describe` je Adapter: Version, Pfad, Login (nur offizielle Statusbefehle), Ausgabeformate, MCP/ACP, Status registriert/verfügbar/ausgeführt. Versionsgebundene Befehlslisten mit Policy statt Help-Parsing. Matrix `c9a396be4081` daraus erneuern. | Schema plus Tests. Katalog zeigt alle acht CLIs und `grok_api` getrennt. | 1,5–2 Tage |
| 3 | **BP-CLI-02 Welle 2: Cursor** | Neuer Provider über `cursor-agent --print --output-format stream-json` mit explizitem Pfad. Konfigeintrag, Text-only-Profil, Tests nach dem Muster der übrigen Provider. | Fake-Tests, danach ein freigegebener echter Lauf. | 1,5–2 Tage |
| 4 | **BP-CLI-02 Welle 2: Gemini** | Nur Zugang klären (Nutzerentscheidung). Adapter ist vorhanden. Ohne Zugang bleibt Gemini „registriert, nicht verfügbar“. | Belegte Entscheidung. Kein API-Ersatz. | 0,5 Tage (blockiert) |
| 5 | **BP-CLI-03 Welle 3: OpenCode, Copilot** | OpenCode: heutige Route mit `kirabridge-team` neu belegen, Cloudwege sperren. Copilot: Tokenweg freigeben oder als nicht verfügbar führen. | Je ein belegter Lauf oder belegte Absage. | 1–1,5 Tage |
| 6 | **BP-CLI-03 Welle 3: Aider** | Installation nach Freigabe, Wrapper über `--message-file`, Auto-Commits aus, Provider plus Tests. | wie oben | 1,5–2 Tage |
| 7 | **BP-CLI-02-DISC-3 Publikation und E2E** | Automatische Veröffentlichung im Werkzeugkatalog für Kira/ChatGPT. End-to-End-Test je Fähigkeit. | Realer Test je Fähigkeit. | 1–1,5 Tage |

## Schätzung neu

- Discovery allein (DISC-1 bis DISC-3): **3,5–5 Entwicklungstage**.
  Die Board-Schätzung lag bei 2–5 Tagen. Der untere Wert ist nicht haltbar.
  Grund: Keine CLI hat eine JSON-Hilfe, deshalb braucht jeder Adapter eine eigene
  versionsgebundene Beschreibung.
- Alle drei Adapterwellen plus Discovery: **8,5–12,5 Entwicklungstage**.
  Dazu kommen Wartezeiten auf Zugangs- und Kostenfreigaben (Gemini, Copilot, Aider).
- Annahmen: Nur Claude steht als Autor zur Verfügung (Bauplan N1). Die lokale
  Testinstabilität wird nicht im selben Paket behoben.
