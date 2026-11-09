# Big Plan · Claude als Koordinator-Worker (BP-CLI-01)

Nutzerbeschluss vom 09.11.2026 (ThreadDesk-Board `188ce4729a62`, Eintrag `416bbdc68c43`): Der Koordinator läuft mit Claude statt Codex. Opt-in per Profil; Standard und Codex-Wege bleiben unverändert. ThreadDesk ist die Planquelle.

## Profil

| Feld | Bedeutung |
|---|---|
| `coordinator_cli` | `codex` (Standard) oder `claude` |
| `claude` | absoluter Pfad der `claude`-Datei (Pflicht bei `claude`) |
| `claude_quota_unknown_acknowledged` | `true` nur nach ausdrücklicher Nutzerfreigabe, dass Claude-Verbrauch nicht abfragbar ist |

Bei `claude` ist `routing`/`worker_routing` nicht erlaubt. Die Rollennamen `codex` (Worker-Slot) und `codex_verify` (Verifier-Slot) bleiben als Identitäten erhalten; ihre Agenten sind `claude_worker` und `claude_verify`. Grok-Review bleibt optional. Neue Felder erfordern wie alle Profilfelder einen ausdrücklichen Neustart des eigenen Dienstes.

## Adapter

- `cli_adapters/claude.py`: drittes CLI-Modul (ohne Sichtterminal-Fähigkeiten) und `probe`: `claude --version` und `claude auth status --json`, kein Modellaufruf, keine Kosten, nur nicht identifizierende Felder.
- `agent_manager/claude_headless.py`: `claude -p` mit `stream-json`, `--json-schema` (Worker: `team_turn.schema.json`, Verifier: `review_verdict.schema.json`), festem Arbeitsordner, Zeitlimit, `--safe-mode`, leeren Einstellungsquellen/MCP, ohne Sitzungspersistenz. API-Schlüssel/Token werden vor dem Start abgelehnt. Nur `structured_output` zählt; Fließtext ist kein Urteil.

## Schreibschutz des Verifiers

Drei Schichten: (1) `--tools Read,Grep,Glob` (kein Bash/Write/Edit verfügbar), (2) `--disallowedTools` mit Shell, Schreib-, Netz- und Delegationswerkzeugen bei `dontAsk`, (3) der Adapter wertet jedes `system/init` und jeden `tool_use` aus und weist Schreib- oder Shellwerkzeuge mit `agent_write_denied` ab. Das Profil des Verifiers muss `read-only` sein, sonst Abweisung vor Start. Der Worker hat nur bei `workspace-write` zusätzlich Edit/Write, nur unter dem festen Arbeitsordner, nie Bash; Prüfbefehle führt weiterhin der Koordinator aus.

## Kontingentbeleg

Claude bietet keinen abfragbaren Abo-Verbrauch. `quota_evidence` bestätigt nur Login (`claude.ai`) und fehlende API-Schlüssel und liefert `usage: unknown`, nie Prozentwerte. Der Grant erhält `budget_state=user_acknowledged_unknown` und wird nur erzeugt, wenn `claude_quota_unknown_acknowledged` im Profil `true` ist. Fehlender Login oder API-Schlüssel-Route stoppt als Ressourcenstopp (Wiederholung nach 60 s). Keine Kosten außerhalb des Abos.

## Nachweise und Grenzen

`tests/test_claude_coordinator.py` nutzt deterministische CLI-Fixtures (Erfolg, negatives Urteil, Verifier-Schreibversuch, fehlender Login, Timeout ohne Replay, Budget/Schlüssel). Fixtures sind keine Liveabnahme: Es wurde kein echter Claude-Modellturn gestartet, das Feld `structured_output` im Resultatereignis ist gegen die dokumentierte CLI-Ausgabe, nicht live, belegt. Offen für BP-AUTO-01: Profilfelder setzen, Nutzerfreigabe eintragen, `allowed_cwds`/`checks` und Neustart des eigenen Labels, Testkarten per `adopt`.
