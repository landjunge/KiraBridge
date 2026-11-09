# Big Plan · Claude als Koordinator-Worker (BP-CLI-01)

Nutzerbeschluss vom 09.11.2026 (ThreadDesk-Board `188ce4729a62`, Eintrag `416bbdc68c43`): Der Koordinator läuft mit Claude statt Codex. Opt-in per Profil; Standard und Codex-Wege bleiben unverändert. ThreadDesk ist die Planquelle.

## Profil

| Feld | Bedeutung |
|---|---|
| `coordinator_cli` | `codex` (Standard) oder `claude` |
| `claude` | absoluter Pfad der `claude`-Datei (Pflicht bei `claude`) |

Die Rollennamen `codex` (Worker-Slot) und `codex_verify` (Verifier-Slot) bleiben als Identitäten erhalten; beide Agenten nutzen den vorhandenen Adapter `claude_code`. Grok-Review bleibt optional. Neue Felder erfordern wie alle Profilfelder einen ausdrücklichen Neustart des eigenen Dienstes.

## Adapter

Kein neuer Adapter: der vorhandene `claude_code` (`agent_manager/claude.py`) wird erweitert. Ohne `output_schema` bleibt sein Textpfad unverändert. Nur ein ausdrücklich gesetztes, gepacktes AutoNext-Schema (`team_turn` = Worker, `review_verdict` = Verifier) wählt den Koordinatorturn; die Rolle folgt allein daraus.

- `cli_adapters/claude.py`: drittes CLI-Modul (ohne Sichtterminal-Fähigkeiten) und `probe`: `claude --version` und `claude auth status --json`, kein Modellaufruf, keine Kosten, nur nicht identifizierende Felder.
- Koordinatorturn: `claude -p` mit `stream-json`, `--json-schema`, festem Arbeitsordner, Zeitlimit, `--safe-mode`, leeren Einstellungsquellen/MCP, ohne Sitzungspersistenz. API-Schlüssel/Token werden vor dem Start abgelehnt. Nur `structured_output` zählt.
- Routing: `integration.new_routed_manager(managed_only=True)` umhüllt `claude_code` wie Codex/Grok (optional, ohne Profil unverändert). Ein geroutetes Claude-Turn scheitert in `effort_shim` geschlossen, bis Zugangsnachweis und Adaptertest eine verifizierte Effort-Injektion liefern. Kein eigener Router.

## Schreibschutz des Verifiers

Drei Schichten: (1) `--tools Read,Grep,Glob` (kein Bash/Write/Edit verfügbar), (2) `--disallowedTools` mit Shell, Schreib-, Netz- und Delegationswerkzeugen bei `dontAsk`, (3) der Adapter wertet jedes `system/init` und jeden `tool_use` aus und weist Schreib- oder Shellwerkzeuge mit `agent_write_denied` ab. Das Profil des Verifiers muss `read-only` sein, sonst Abweisung vor Start. Der Worker hat nur bei `workspace-write` zusätzlich Edit/Write, nur unter dem festen Arbeitsordner, nie Bash; Prüfbefehle führt weiterhin der Koordinator aus.

## Budget (TollGate zuständig)

KiraBridge enthält keine eigene Budget- oder Kontingentlogik für Claude. `autonext/budget.py` definiert nur die schmale Schnittstelle `reserve` (vor jedem Claude-Turn) und `settle` (danach, Ergebnis `completed`/`failed`/`unknown`). Bei Ablehnung gibt es einen harten Stopp (`autonext_budget_stop`) vor dem Prozessstart; scheitert die Abrechnung, bleibt der Turn UNKNOWN. Dahinter steht bis zur Anbindung von BP-TG-01 `FailClosedBudgetGate`, das immer ablehnt. Ein Grant für das Claude-Profil wird erst erzeugt, wenn das Gate `ready` meldet. Der Codex-Weg (`account/rateLimits/read`) bleibt unverändert und nutzt die Schnittstelle nicht. `claude auth status` dient nur als Loginbeleg (`claude.ai`, keine API-Schlüssel), nie als Verbrauchsangabe. Keine Kosten außerhalb des Abos.

Gelesener Stand in TollGate (nur lesend): vorhanden ist nur `accounting.try_reserve_day_call` (Tageslimit je Anbieter/Verbraucher). Ein Vertrag für Reserve, Dispatch, Settlement und harten Stopp für Abo-CLI-Turns fehlt.

## Nachweise und Grenzen

`tests/test_claude_coordinator.py` nutzt deterministische CLI-Fixtures (Erfolg, negatives Urteil, Verifier-Schreibversuch, fehlender Login, Timeout ohne Replay, Budget/Schlüssel). Fixtures sind keine Liveabnahme: Es wurde kein echter Claude-Modellturn gestartet, das Feld `structured_output` im Resultatereignis ist gegen die dokumentierte CLI-Ausgabe, nicht live, belegt. Offen für BP-AUTO-01 (hängt an BP-TG-01): TollGate-Client hinter `BudgetGate` (Reserve/Settle je Turn, harter Stopp, Belege), Profilfelder `coordinator_cli`/`claude`, `allowed_cwds`/`checks` samt Neustart des eigenen Labels, Testkarten per `adopt`.
