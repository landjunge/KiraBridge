# KiraBridge 0.8.0 RC50

macOS-Kandidat nach RC49 (`edc4429`). Schwerpunkt: Teamkoordination mit mehreren
Agentensitzungen und zuverlässige Wiederaufnahme von Folgeaufträgen.

Neu gegenüber RC49:

- [PR #157](https://github.com/landjunge/KiraBridge/pull/157): Teamaufträge speichern
  nach einem belegten nativen Turn die Provider-Sitzung des Bearbeiters. Folgeaufträge
  an denselben Bearbeiter setzen die Sitzung fort, wenn Agent und Arbeitsverzeichnis
  unverändert sind. Codex nutzt `codex exec resume`, Grok ACP und OpenCode ACP nutzen
  `session/load`, der OpenCode-HTTP-Adapter prüft und verwendet die vorhandene
  Server-Sitzung. Die Bindung gilt nur für versiegelte Teamaufträge, überlebt einen
  Bridge-Neustart und wiederholt keinen bereits beanspruchten Core-Auftrag.
- Neue Team-Schnittstellen `team_session_get` und `team_session_clear` sowie die CLI
  `team session` und `team session-clear`. Die Sitzungsbindung ist pro Team und
  Mitglied getrennt; Eigentümer und Koordinator dürfen sie einsehen bzw. zurücksetzen.
- ACP-Verbesserungen: beratende Vendor-Notifications und Nicht-JSON-Diagnosezeilen
  werden toleriert; der einmalige Running-Übergang bleibt beim History-Replay von
  `session/load` stabil. Eine abweichende Sitzungskennung wird weiterhin verworfen.
- Live-Nachweis `docs/evidence/team-coordination-live-20261112.json`: echte Codex-,
  Grok-ACP- und OpenCode/DeepSeek-V4-Pro-Sitzungen, Runde 1 parallel, Bridge-Neustart,
  Runde 2 mit exakt derselben Sitzung und `session_resumed: true` für alle drei.

Tests: 126 gezielte Team-/ACP-/OpenCode-Tests; 237 breitere Agenten-/Team-/Session-Tests;
154 Team-/AutoNext-/Continuation-Tests; Team-Console und MCP zusätzlich grün. Ruff und
`git diff --check` sauber. Die produktive Installation wird separat nach der lokalen
Annahme dokumentiert.

Bekannte Grenzen: Die produktive KiraBridge-Konfiguration nutzt weiterhin die
vorhandenen sichtbaren Bindungen; die neuen Sitzungspfade sind im isolierten
Drei-Agenten-Lauf belegt. AutoNext behält seinen eigenen Sitzungslebenszyklus und
verwendet die Team-Sitzungsbindung nicht. Ohne belegten Turn wird keine Sitzung
gespeichert; ein unklarer Turn wird nicht automatisch wiederholt.

---

# KiraBridge 0.8.0 RC50 (EN)

macOS candidate after RC49 (`edc4429`). Focus: team coordination with multiple agent
sessions and reliable resumption of follow-up work.

Changes since RC49:

- PR #157: team assignments remember the worker's proven provider session after a
  native turn. Later work for the same worker resumes that Codex, Grok ACP or OpenCode
  session when agent and working directory are unchanged. Codex uses
  `codex exec resume`, Grok ACP and OpenCode ACP use `session/load`, and the OpenCode
  HTTP adapter verifies and reuses the existing server session. Resumption is restricted
  to sealed team work, survives a bridge restart and never replays a claimed core task.
- New `team_session_get` and `team_session_clear` team interfaces plus CLI
  `team session` and `team session-clear`. Bindings are scoped per team and member;
  owner and coordinator may inspect or clear them.
- ACP improvements: advisory vendor notifications and non-JSON diagnostic lines are
  tolerated; the one-time running transition stays stable across `session/load` history
  replay. A mismatched session id still fails closed.
- Live evidence `docs/evidence/team-coordination-live-20261112.json`: real Codex,
  Grok ACP and OpenCode/DeepSeek V4 Pro sessions; round 1 in parallel, bridge restart,
  round 2 with the exact same session and `session_resumed: true` for all three.

Tests: 126 focused team/ACP/OpenCode tests; 237 broader agent/team/session tests; 154
team/AutoNext/continuation tests; team console and MCP suites also green. Ruff and
`git diff --check` clean. The production installation is documented separately after
local acceptance.

Known limits: the production KiraBridge configuration still uses the existing visible
bindings; the new session paths are proven by the isolated three-agent run. AutoNext
keeps its own session lifecycle and does not use the team session binding. No session is
stored without a proven turn; an uncertain turn is never retried automatically.
