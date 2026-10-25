# Aktueller Reparaturstand · 25. Oktober 2026

Dieser Einstieg ersetzt ältere Zustandsaussagen weiter unten. Die bisherigen
Abschnitte bleiben als unveränderte Entwicklungshistorie erhalten. Maßgeblicher
Arbeitsspeicher ist weiterhin Whiteboard `188ce4729a62`; keine konkurrierende Ablage.

## Erledigt und belegt

- Produktiver RC17-Stand zuletzt unabhängig bestätigt: Quelle
  `012b592caa5b6126342f9148f3b38a7d50b00379`, PID 72612, Dispatcher aktiv.
  127 installierte Paketdateien entsprechen dem geprüften Wheel; Konfiguration,
  Zugangsdaten und Dateimodi entsprechen der Sicherung. Dienstoptionen außer dem
  Programmpfad sind erhalten. Siehe [Installationsbeleg](evidence/rc17-installed-012b592-20261025.json),
  [Datenerhalt](evidence/rc17-data-preservation-20261025.json) und
  [unabhängige Prüfung](evidence/rc17-independent-review-20261025.json).
- Reines natives Einfügen ohne Return und separates Rücklesen wurden am
  unveränderten Eingabecode der Quelle `7725bc6` bestätigt. Das ist keine neue
  UI-Abnahme von `012b592`, keine Agentenausführung und keine allgemeine
  Codex-/Grok-Restartabnahme. Der Paketvergleich bestätigt unveränderte Eingabemodule.
- Whiteboard-Schreibweg und vollständiges unabhängiges Rücklesen sind belegt.
  Ein Revisionskonflikt der ergänzenden Prüfung ist mit `found=false` und fehlendem
  Marker abgeglichen; der aktualisierte Nachtrag wurde in Revision 47 bestätigt.
- Separate Braille-/Pink-Vorschau liegt in [Draft-PR34](https://github.com/landjunge/KiraBridge/pull/34);
  sie ist nicht in den produktiven Dienst eingebaut.

Die drei früher wartenden Nachrichten wurden regulär empfangen und quittiert,
mit `externally_acknowledged=true`, `run_id=null` und ohne CLI-Ausführung.
Das belegt **keinen** Bibliotheksimport. Alte unsichere Übergaben und ihre Historie
bleiben erhalten. Keinen alten Library-Auftrag erneut einreichen oder ausführen.

## Getrennte Änderungen in Arbeit

- [PR32](https://github.com/landjunge/KiraBridge/pull/32): integrierte RC17-Reparaturen;
  Kandidateninstallation ist belegt, reguläre main-/Releaseintegration bleibt offen.
- [PR33](https://github.com/landjunge/KiraBridge/pull/33) und
  [PR35](https://github.com/landjunge/KiraBridge/pull/35): vorhandener Library-Adapter
  und Legacy-Checkpointkompatibilität auf getrennten Branches. Whiteboardrevision 46
  dokumentiert deren gezielte Nachweise; diese Änderungen sind nicht produktiv aktiviert.
- [Draft-PR36](https://github.com/landjunge/KiraBridge/pull/36): Abnahmeharness verlangt
  nach der Bereinigung eine unabhängige Abwesenheitsprüfung seines Testdienstes.
  Vorher reproduzierter falscher Erfolg, danach vier gezielte simulierte Fälle
  bestanden. Keine Runtime- oder Installationsänderung.
  [Prüfbeleg](evidence/acceptance-cleanup-20261025.json).

Der Longread-/Upgradebeleg bestätigt Überlappung mit dem Installerstart, keinen
exakt instrumentierten bootout-Zeitpunkt und keine abschließende Ursache des alten
allgemeinen EIO. Fehlgeschlagene oder unterbrochene Läufe bleiben als solche sichtbar.

## Offen und nächster konkreter Schritt

GitHub Verify und macOS-Paketprüfung von PR36 starteten laut ihren Annotationen
wegen Kontozahlung/Ausgabenlimit nicht. Lokale Erfolge ersetzen keine Pflichtchecks.
RC17 bleibt Entwurf, veröffentlicht bleibt zuletzt RC14; keine Veröffentlichung
oder Zusammenführung aus dieser Dokumentationsänderung ableiten. Zusätzliche
Review war vom Nutzer abgewählt; sie darf weder als erfolgt noch pauschal als
neuer offener Auftrag dargestellt werden. Apple-Silicon-Abnahme bleibt offen.

Das aktive ThreadDesk-Profil verwendet zuletzt den alten Quellpin `6c7d578a` ohne
Dateiempfänger. Der getrennt getestete Empfänger `770bbc9f` ist dadurch nicht aktiviert.
Dateimodul, autorisierte Exportquelle und konkrete Ziele fehlen weiterhin.
Vollständige ChatGPT-Fähigkeiten ersetzen diese Voraussetzungen nicht.

Als Nächstes bestehende PRs koordiniert prüfen und CI-Abrechnung/Pflichtchecks
ermöglichen; erst mit ihren tatsächlichen Ergebnissen regulär integrieren und aus
finalem main bauen. Library-Arbeit benötigt zuvor eine bereitgestellte autorisierte
Exportquelle sowie eine getrennt geprüfte Receiver-/Profil- und Datenmigration.
Keinen zweiten Adapter, keine erneute Queueausführung und keinen blinden Profilwechsel.

Ausführliche zeitlich geordnete Belege:
[Fortsetzungsbericht](RC17-RESUME-20261025.md).
Die folgenden RC14-, Review- und Installationsaussagen beschreiben ihren damaligen
Zeitpunkt und sind keine aktuellen Freigaben oder Sperren.

---

# Ordered repair status · 2026-10-24

User-mandated order: queue → current terminal binding/input → Whiteboard validation
→ Library import/knowledge organization. No duplicate execution of the queued request.

## Phase 1: queue

Live read-only RC14 diagnosis confirms a queued new message without terminal input,
blocked by an old uncertain handoff. Its original failure/receipt history is preserved.
No production queue, installation, configuration or permissions were modified.

Implementation is separate modules: `queue_management/schema.py` (additive holds),
`views.py` (owner scope, pagination, revisions/content), `control.py` (CAS/withdrawal/
restore/retirement), `models.py` (strict contract), `mcp_gateway/queue_tools.py`
(MCP registration), `event_queue.py` (independent webhook outbox). Existing task,
approval, stop, receiver and audit owners are reused. No new scheduler or token store.

Executed on actual Intel macOS 15.7.4: 1069 full regression tests passed before final
hardening. Subsequent focused checks cover sender-only restoration, late receipts,
lossless Unicode content and the installer downgrade guard. A final full-suite run
and its exact evidence are recorded with the PR after source pinning.
Real isolated HTTP MCP proves discovery, authenticated queue inspection, cancellation,
restoration, snapshot clear and actual owned-process stop with exit code. Unit/contract
cases exercise unknown handoff readiness refusal/retirement, no duplicate dispatch,
restart persistence, capacity recovery, foreign scope, manual exact approval and races.
Readiness success for an uncertain handoff in these unit cases is simulated; it is not
a live production Codex receipt. Production RC14 exposes no `queue.control` operation.

**Deployment/production gate remains open:** new tools are not installed into RC14.
Its old unknown and queued Library message are not claimed removed, delivered or run.
A safe older-runtime refusal is distinct from a successful rollback. Required GitHub
checks/review and explicit installation acceptance/authorization remain necessary.

Phases 2–4 must not be represented as completed while this production gate remains.
The existing Whiteboard `f014aeed7384` is not duplicated. No Library files were
transferred or interpreted by this queue-repair work. OpenAI/ThreadDesk access and
actual source data must be verified only after the ordered prerequisite is satisfied.

## Reproduce (isolated development)

`uv sync --locked --dev`, then `uv run pytest -q`.
Focused: `uv run pytest -q tests/test_queue_management.py tests/test_event_push.py tests/test_installer.py`.
The real HTTP fixture uses random local ports, synthetic credentials, private temp
stores and one owned short-lived sleeper. It never types into a user's Terminal.
No source body or secret is included in the tracked live diagnostic evidence.

## Verification timing failure

One full run reported 1071 passed and one failure in the existing child-cleanup test:
its 300-ms execution budget elapsed before any child PID was captured. The unchanged
focused test immediately passed. The test fixture now allows 3 seconds for interpreter/
child startup; timeout and observed child disappearance assertions are retained. No
production timeout, cleanup code or security check was relaxed. The final suite must
pass with that unchanged cleanup assertion; the failed run is retained as evidence.

## Final scoped checks and user testing constraint

The final message-job/content revision correction passed **66 directly related tests**
(queue management, event push, installer). Earlier the broad suite passed **1074 tests**;
that broad success precedes the last revision-binding correction. A later broad retry
was interrupted on the user's explicit instruction to avoid additional whole-suite
repetitions; it is **not** counted as passing. No further broad tests were launched.
The final targeted selection is necessary for the changed queue state/rights/readback,
webhook cancellation/authorization race and downgrade protection. Logs and source-tree
fingerprint: [test evidence](evidence/queue-phase1-tests-20261024.json).

The actual isolated RC14 wheel was also probed: a held-delivery downgrade is refused
without switching/stopping a service or modifying the store. The compatible comparison
uses the editable development runtime, not an installer/package acceptance claim.

No new release or production installation is approved. The queued Library request
has not been resent, acknowledged as executed or run in parallel. The user subsequently explicitly authorized a status append to the existing work-memory
Whiteboard 188ce4729a62 while Phase 1 remains gated; this is recorded below.

## Canonical work-memory Whiteboard (latest user instruction)

Use **188ce4729a62**, “ThreadDesk und KiraBridge – Wechselentwicklung durch Codex”.
No competing Whiteboard was created. Existing f014aeed7384 and other user Whiteboards
remain intact; they are not duplicate work-memory targets.

A 3002-character status note was appended using existing authorized RC14 tools and a
stable operation ID, expected revision 2. ThreadDesk returned a validated mutation
receipt for revision **3**; a separate `get_thread` task confirmed the entire note and
exactly one marker. The original description is unchanged. This proves this particular
status append/readback, **not** a repair or broad acceptance of longer Whiteboard inputs.

Evidence: [stored/readback confirmation](evidence/whiteboard-memory-188ce4729a62.json).
The note contains the source commit/branch, PR26, completed code/tests, in-progress
review/acceptance, pending terminal/Whiteboard/import work, CI billing blocker and
immediate next step. Future meaningful milestones and project switches update this
same Whiteboard with confirmed readback. No further tests were run for this
status/documentation update.

PR26 source check [40101832381](https://github.com/landjunge/KiraBridge/actions/runs/40101832381)
failed before steps: recent account payments failed or the spending limit must increase.
Review and deployment acceptance remain open; no merge or release publication occurred.

## Native-team milestone and corrected scope

The user's later explicit team instruction authorized independent terminal/Whiteboard
development and a read-only receiver audit while production gates remain open.
No queue repair was duplicated. `/root/terminal_repair` and `/root/whiteboard_repair`
worked in their own KiraBridge worktrees; `/root/receiver_contract_audit` independently
reviewed the terminal safety contract and receiver/index boundaries. Root reviewed
the results before cherry-picking. No ThreadDesk source was changed.

The accidentally pasted Codex-3 Server & Sync instruction was withdrawn. This session
created no Server & Sync source, branch, worktree or project entry and did not touch
Codex-2/3 sessions. Only a temporary internal steering message was sent and rescinded.

**Completed in isolated code:** fresh task-owned explicit window/TTY/process binding;
old unknown handoffs never migrate. `submit=false` now supports permission-checked pure
Paste without Return, with durable uncertain-state/no-replay protection. Source commits
`2c1c7af`, `ae5f0fd` map to integrated `099ddd5`, `eab1b1e`. Independent C review found
no remaining identified safety blocker; it is not positive native acceptance.
The reported Terminal 38077 / ttys001 / expected_pid 12591 was catalogued and read
successfully again without input. Its agent process was an OS observation, not a
cryptographic identity. No user terminal was typed into or stopped.

**Required targeted evidence:** 90 affected selection/handoff cases, then three changed
raw-image capture cases; four added paste-only cases and six direct regressions passed.
Two paste-only test fixture cleanup failures were corrected and only those cases rerun.
Native Intel-macOS negative guards and actual JavaScriptCore Unicode check passed.
Positive native Paste/Return did NOT pass: the focus guard refused. Actual Codex/Grok
end-to-end input/restart remains open. See [terminal report](VISIBLE-SELECTION-20261024.md).

Whiteboard source `cc0201b` maps to `691e78d`: fresh peer preflight, bounded schema
validation, safe character/byte diagnostics, no truncation or blind create replay.
39 new cases were covered incrementally, not a repeated complete suite. A separate
single real pinned ThreadDesk64353be MCP/private-store run validated 10,000-character
description, 100,000-emoji note and independent raw/readback equality; 10,001-description
preflight left the store unchanged. Source `4ee96f3` maps to `c60c1d3`; later harness-only
HOME correction `fb08f90` maps to `2a57605`, linted but not rerun. Historical evidence
states the original child environment. No product profile was changed.
See [Whiteboard report](WHITEBOARD-BOUNDARIES-20261024.md).

**Concrete work-memory failure:** `team-interop-plan-188-20261024-01` returned peer
`tool_error`, details `{}`. Operation status was `found=false`; its marker was absent
from revision11. No blind retry and no unproved size-limit cause claimed. A subsequent
distinct correction/status note `[KB-CODEX1-CORRECTION-20261024-01]` saved revision12;
separate readback confirmed the entire note and exactly one marker. Earlier plan/team/
audit notes were independently confirmed at revisions5,6,9. Existing content preserved.

**Open / blocked:** positive controlled native input acceptance, required GitHub checks
and review, explicit production acceptance/deployment. Current TD64353be lacks the
negotiated receiver/index MCP operations; selected authorized Library file bytes are
not supplied. No import, indexing or duplicate queued Library execution was performed.
The [receiver/index contract](RECEIVER-INDEX-CONTRACT-20261024.md) describes concrete
missing boundaries. Published release remains RC14; RC15/RC16 are drafts. No new
package acceptance or installation command for this unreleased patch is claimed.

**Next step:** push reviewed integration, open a stacked PR above PR26, retain required
CI/review gates and report their actual outcomes. Do not repeat passed suites merely
because commits were cherry-picked unchanged. Production RC14, credentials, files,
permissions and launchd lifetime remain unchanged.

Integration Ruff passed on the changed Python files. Format checking initially found
two test signature layouts; formatting moved their existing F811 comments. The two
comments were placed on the corresponding fixture parameters and only that file's
Ruff/format checks were repeated: passed. No behavior changed or test suite repeated.
Work-memory/target-read evidence: [correction confirmation](evidence/codex1-correction-20261024.json).

## GitHub integration gate

Reviewed changes pushed as `ca0ad0123c9f92374ad35a01d825faaa59f2fd78` on
`fix/terminal-whiteboard-20261024`; local and remote SHA equality confirmed.
[PR27](https://github.com/landjunge/KiraBridge/pull/27) is OPEN/DRAFT above
`fix/queue-recovery-20261024` (PR26), not merged. Independent external review remains
outstanding. Internal native C security review is not a GitHub approval.

[Verify run40106477951](https://github.com/landjunge/KiraBridge/actions/runs/40106477951)
and [macOS package run40106477987](https://github.com/landjunge/KiraBridge/actions/runs/40106477987)
failed before any job step. Intel verify check120909110502 and package check120909110683
annotations both state: "The job was not started because recent account payments have
failed or your spending limit needs to be increased."
These checks did not execute and are not passes. No merge, package/release publication
or check bypass was attempted. Fix billing/start required checks and obtain review,
then complete controlled positive native acceptance before treating this as working.
