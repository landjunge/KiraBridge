# Big Plan · Claude als Koordinator-Worker (BP-CLI-01)

Nutzerbeschluss vom 09.11.2026 (ThreadDesk-Board `188ce4729a62`, Eintrag `416bbdc68c43`): Der Koordinator läuft mit Claude statt Codex. Opt-in per Profil; Standard und Codex-Wege bleiben unverändert. ThreadDesk ist die Planquelle.

## Profil

| Feld | Bedeutung |
|---|---|
| `coordinator_cli` | `codex` (Standard) oder `claude` |
| `claude` | absoluter Pfad der `claude`-Datei (Pflicht bei `claude`) |

Bei `claude` ist `routing`/`worker_routing` nicht erlaubt. Die Rollennamen `codex` (Worker-Slot) und `codex_verify` (Verifier-Slot) bleiben als Identitäten erhalten; ihre Agenten sind `claude_worker` und `claude_verify`. Grok-Review bleibt optional. Neue Felder erfordern wie alle Profilfelder einen ausdrücklichen Neustart des eigenen Dienstes.

## Adapter

- `cli_adapters/claude.py`: drittes CLI-Modul (ohne Sichtterminal-Fähigkeiten) und `probe`: `claude --version` und `claude auth status --json`, kein Modellaufruf, keine Kosten, nur nicht identifizierende Felder.
- `agent_manager/claude_headless.py`: `claude -p` mit `stream-json`, `--json-schema` (Worker: `team_turn.schema.json`, Verifier: `review_verdict.schema.json`), festem Arbeitsordner, Zeitlimit, `--safe-mode`, leeren Einstellungsquellen/MCP, ohne Sitzungspersistenz. API-Schlüssel/Token werden vor dem Start abgelehnt. Nur `structured_output` zählt; Fließtext ist kein Urteil.

## Schreibschutz des Verifiers

Drei Schichten: (1) `--tools Read,Grep,Glob` (kein Bash/Write/Edit verfügbar), (2) `--disallowedTools` mit Shell, Schreib-, Netz- und Delegationswerkzeugen bei `dontAsk`, (3) der Adapter wertet jedes `system/init` und jeden `tool_use` aus und weist Schreib- oder Shellwerkzeuge mit `agent_write_denied` ab. Das Profil des Verifiers muss `read-only` sein, sonst Abweisung vor Start. Der Worker hat nur bei `workspace-write` zusätzlich Edit/Write, nur unter dem festen Arbeitsordner, nie Bash; Prüfbefehle führt weiterhin der Koordinator aus.

## Budget (TollGate zuständig)

KiraBridge enthält keine eigene Budget- oder Kontingentlogik für Claude. `autonext/budget.py` definiert nur die schmale Schnittstelle `reserve` (vor jedem Claude-Turn) und `settle` (danach, Ergebnis `completed`/`failed`/`unknown`). Bei Ablehnung gibt es einen harten Stopp (`autonext_budget_stop`) vor dem Prozessstart; scheitert die Abrechnung, bleibt der Turn UNKNOWN. Dahinter steht bis zur Anbindung von BP-TG-01 `FailClosedBudgetGate`, das immer ablehnt. Ein Grant für das Claude-Profil wird erst erzeugt, wenn das Gate `ready` meldet. Der Codex-Weg (`account/rateLimits/read`) bleibt unverändert und nutzt die Schnittstelle nicht. `claude auth status` dient nur als Loginbeleg (`claude.ai`, keine API-Schlüssel), nie als Verbrauchsangabe. Keine Kosten außerhalb des Abos.

Gelesener Stand in TollGate (nur lesend): vorhanden ist nur `accounting.try_reserve_day_call` (Tageslimit je Anbieter/Verbraucher). Ein Vertrag für Reserve, Dispatch, Settlement und harten Stopp für Abo-CLI-Turns fehlt.

## Nachweise und Grenzen

`tests/test_claude_coordinator.py` nutzt deterministische CLI-Fixtures (Erfolg, negatives Urteil, Verifier-Schreibversuch, fehlender Login, Timeout ohne Replay, Budget/Schlüssel). Fixtures sind keine Liveabnahme: Es wurde kein echter Claude-Modellturn gestartet, das Feld `structured_output` im Resultatereignis ist gegen die dokumentierte CLI-Ausgabe, nicht live, belegt. Offen für BP-AUTO-01 (hängt an BP-TG-01): TollGate-Client hinter `BudgetGate` (Reserve/Settle je Turn, harter Stopp, Belege), Profilfelder `coordinator_cli`/`claude`, `allowed_cwds`/`checks` samt Neustart des eigenen Labels, Testkarten per `adopt`.
