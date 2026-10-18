# Auftragseigener CLI-Stopp / Owned CLI workflow stop

## Stand und Grenzen / State and limits

Quellpaket KB-C04/TG-C02, nicht automatisch aktivierte Laufzeit. KiraBridge bleibt
privat; das unverändert öffentliche TollGate-Repository enthält den nötigen Core
in [PR35](https://github.com/landjunge/tollgate/pull/35), Commit
`e382f4784543b1b62c3a238dd6c924b1e7d93ecb` (Basis `c1aa247`).

**Kosten unbekannt, kein harter Dollarcap.** Dieser Anschluss ist ausdrücklich
`stop_only`, ohne Nullkostenquote, Geldreservat oder globale CLI-Kostenbehauptung.
Budgetierte Workflows dürfen nicht auf diesen Weg zurückfallen. Andere Programme,
fremde Sitzungen und nicht angeschlossene Aktionen sind davon nicht kontrolliert.
Ein eigener Prozessgruppenabbruch macht eine bereits externe Wirkung nicht rückgängig.

## Betreiberanschluss – nicht als Task-Payload

Die zugehörige TollGate-Version muss in einer vom Betreiber geprüften Installation
verfügbar sein. Keine implizite Installation, kein Download beim Taskstart, kein
Mandatory-Cross-Repo-Checkout oder neues CI-Token. Vor Aktivierung Quellpin und
Dateifingerprints gegen die tatsächlich importierten Modulpfade prüfen:

| Modul bei genanntem Pin | SHA256 |
| --- | --- |
| `src/tollgate/workflow_control.py` | `4a7180f3fa4a1a49ae55ea9cc98125ed89bd90cbc852510443911b0286f6cfb8` |
| `src/tollgate/filelock.py` | `4e1306d6069ef1619414e004a52a3345e68d1f00a1fc3c410227755e59ceda43` |

Schematischer **Host-Code**, kein neuer CLI-/Config-Vertrag und hier nicht im
laufenden Dienst ausgeführt:

```python
from tollgate.workflow_control import WorkflowControl
from kirabridge.workflow_control_adapter import WorkflowControlAdapter

control = WorkflowControl(
    root=existing_operator_tollgate_root,
    registered_process_actors={"codex": "existing-codex-consumer"},
    lock_timeout_s=1.0,
)
bridge.workflow_control = WorkflowControlAdapter(
    bridge, control,
    project_id=explicitly_configured_project_id,
    actor_id="codex", consumer_id="existing-codex-consumer",
)
```

Projekt, Actor und Consumer kommen ausschließlich aus dieser vertrauenswürdigen
Assembly. Kein Task-Boolean schaltet den Modus frei, kein Caller tauscht einen
Consumer aus. TG verwendet als workflow_id die beständige technische Handoff-
Binding-ID, die Principal, lokalen Operator und Handoffrevision enthält. Das
ersetzt keine externe Businessidentität. original_task_id bleibt inklusive
Doppelpunkt erhalten; Bridge-Step-ID/Receipt/Requesthash bilden eine getrennte
Versuchsreferenz. Source-/Handoff-/Threadrevisionen werden nicht vermischt.

Root integriert separat die validierten Inputs, Policy-/Kontrollworker-Einordnung
und optionale Konfiguration. `async stop(principal, handoff_id, revision, stop_id)`
ist der stabile direkte Hostaufruf. Root reicht beim öffentlichen Kontrollweg
zusätzlich `task_id=task["id"]` als Keyword. Dieser muss eine aktive eigene
`workflow.stop`-Task mit genau passenden Handoff-/Revisions-/Stop-Argumenten sein.
Ohne Task-ID wird Audit.task_id=None gespeichert, niemals der alte Codex-Turn:
damit bleibt die Runtime der direkten Hostprobe unbekannt statt retroaktiv erfunden.
Er prüft bestehende `task.cancel` **und**
`process.terminate`-Berechtigungen und genau den eigenen Handoff. Ohne konfigurierte
Assembly darf der neue Kontrollweg nur eine fehlende Voraussetzung melden.

Das Root-Wiring wird getrennt vorbereitet: optionales `[workflow_control]` mit
enabled=false als Standard, ausschließlich stop_only, state_root, expliziter
Projekt-Rootzuordnung und festen Actor-/Consumerwerten. Ein eigener Router soll
den tatsächlichen CWD zuordnen und control_project_id in der bestehenden Bindung
bewahren; geänderte kontrollierte Zuordnungen müssen scheitern. Diese spätere
Config-/Input-/Kontrollworker-/Readiness-Integration ist **nicht** in diesem
Adaptercommit aktiviert oder als öffentlicher Abnahmenachweis ausgegeben.

## Was der Anschluss wirklich macht

1. HandoffManager bindet einen Turn ausschließlich an den aktuellen gespeicherten
   eigenen Task und die bestehende Handoffbindung. Ein ContextVar ist zusätzlich
   exakt an Principal, Task und aktuelle asyncio-Task gebunden; Kinder erben keine
   verwendbare Dispatchberechtigung. Das Token wird im finally zurückgesetzt.
2. TerminalManager tritt **direkt** um den tatsächlichen `await spawn_process`
   und die Sessionregistrierung in `WorkflowControl.process_start(identity)` ein.
   Die vorhandene auftragseigene TG-Dateisperre bleibt bis danach gehalten.
   DISPATCH_ATTEMPTED wird vor dem Start dauerhaft geschrieben. Kein frühes Allow,
   keine zweite Queue, kein neues Kontrolljournal.
3. Lockübernahme und Freigabe laufen im Thread, nicht als wartende Dateisperre im
   Eventloop. Bei Cancellation wird eine möglicherweise nachträglich erworbene
   Sperre kontrolliert geschlossen. Spawn-/Registrierungs-/späte Commitfehler
   räumen ausschließlich den gerade erzeugten eigenen Prozess auf; die dauerhafte
   Versuchmarke bleibt unbekannt und wird nicht wiederholt.
4. Stop ruft die bestehende TG-Barriere auf, bricht passende eigene Wartetasks
   über `cancel_queued` ab und beendet nur passende registrierte eigene Prozesse
   über `TerminalManager.terminate`. Maximal100 Wartetasks/256 eigene Sessions;
   Begrenzung, Inspektionsfehler und Rennen werden angezeigt. Fremde Prozesse,
   andere Handoffs und bestehende interaktive Sitzungen bleiben unberührt.
5. Stopbelege gehen ins vorhandene Bridge-Audit. Die Ansicht zeigt diese getrennt
   von der zuletzt berichteten Turnphase. Ein späteres altes question-/return-
   Metadatenspeichern löscht weder die TG-Barriere noch die beobachtete EFFECTIVE-
   Auditreferenz. Der Recordhash wird geprüft; Hashprüfung beweist keine externe
   Identität. Ein späteres PENDING nimmt eine bereits beobachtete Barriere nicht zurück.
   Der ausführende Stopp-Taskeintrag ist vom ursprünglichen Turn getrennt. Die
   Auditmetadaten führen configured project_id, technische workflow_id, stabilen
   Scopehash control_ref, original_task_id und die tatsächliche Stop-bridge_task_id
   separat. stop_state/barrier_seq stammen ausschließlich aus der TG-Quittung.

| Rückmeldung | Belegter Umfang |
| --- | --- |
| PENDING | Lock noch belegt; dauerhafte Sperre noch nicht bestätigt |
| EFFECTIVE | Weitere **angeschlossene** Starts dieses Scopes dauerhaft gesperrt |
| exit_observed | Ende genau des zugeordneten eigenen Prozesses beobachtet |
| termination_requested / unknown | Abbruch angefordert bzw. Ausgang unklar |
| not_observed | Kein passender aktiver registrierter Prozess gesehen; kein Endebeweis |
| standalone | Keine TG-Assembly für diesen Turn, kein TG-Schutz behauptet |

`stop_observation` ist die damalige minimierte Auditbeobachtung, keine frische
TG-Abfrage und keine allgemeine Abnahme. Auch bei EFFECTIVE bleiben externe
Restwirkung und aktuelles Prozessende ohne eigenen Nachweis unbekannt. Eine späte
Turnantwort kann weiter als Turnphase/Ankunft gemeldet werden; das hebt die Sperre
nicht auf. Neustart oder anderer Idempotenzschlüssel darf unbekannte Versuche nicht
wiederholen. Bereits als kontrolliert gespeicherte Historie kann ohne Assembly
nicht still als Standalone fortgesetzt werden. Bounded-Modi werden abgewiesen.

Rückweg: Assembly deaktivieren, neue Quelländerungen nach Review zurücknehmen;
vorhandene TG-Journale und Bridge-Auditbelege **erhalten**. Kontrollierte Historie
bleibt bis zum erneuten passenden Anschluss gesperrt. Keine Journalbereinigung,
Reset-/Resume-Automatik oder Datenmigration erforderlich.

## English

This optional trusted-host adapter connects the existing durable TollGate scope
barrier directly to actual owned CLI process spawn and registration. It is
**stop-only**: cost unknown, hard_cost_cap=false, no zero-dollar quote or money
reservation. A bounded-budget scope can never be downgraded. The operator must
review/pin the TollGate source above and verify actual imported source paths;
there is no automatic package installation or runtime activation in this change.

The host supplies project/actor/consumer configuration. Workflow identity is the
stable technical owned handoff binding, while the original task ID, Bridge step,
receipt, request hash and revisions remain separate. Inputs cannot self-enable
control or switch consumers. Default standalone execution stays explicit; prior
controlled history cannot resume silently if the assembly disappears.

The context is bound to exact principal/task/attempt and current asyncio task;
child context inheritance is not a new permission. The real spawn and owned
session registration occur while holding the same existing durable journal lock
as stop. A persisted DISPATCH_ATTEMPTED precedes spawn. Unknown/crashed attempts
never replay. Cancelled thread acquisition is awaited and safely closed even if
it acquires late. Spawn/registration/late-commit failures clean up only the newly
owned process and preserve uncertainty.

`async stop(principal, handoff_id, revision, stop_id, *, task_id=None)` requires existing task.cancel
and process.terminate grants. It uses the existing queued-task cancellation and
owned TerminalManager termination. Only matching owned tasks/processes are touched;
100 queued tasks/256 owned sessions are inspected, with truncation/races visible.
Root must separately wire validated inputs, policy, reserved control worker and
operator configuration. No blanket control over CLI children, external effects or
unconnected adapters is claimed.

The optional task_id must identify the active owned workflow.stop operation with
matching target/revision/stop arguments. It is the audit executor, not the previous
Codex turn. Direct trusted-host calls without it record audit.task_id=None and
therefore unknown runtime. Configured project scope, stable scope hash, original
task and actual stop Bridge task references remain separate. Stop state/barrier
sequence come only from the TollGate receipt. Root prepares a separate disabled-
by-default stop_only configuration/router/readiness/control-worker integration;
that wiring is not activated by this source change.

PENDING is not a committed barrier. EFFECTIVE blocks later connected starts but
does not establish process exit. exit_observed is only the registered owned
process; not_observed is not an exit proof. External remaining effects remain
unknown. Existing audit observations expose this separately from the last reported
turn/question/return phase, surviving stale metadata saves. Historical EFFECTIVE
is not negated by later PENDING; it is not a fresh current-runtime check, external
identity authentication or project acceptance.

Keep journals/audit evidence on rollback. No second queue/control log, provider
call, release, visibility change or live activation is introduced here. The
specific acceptance record is [STATUS](evidence/workflow-stop-20261018/STATUS.md).
