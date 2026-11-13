# Scoped Qwen routing / Begrenzte Qwen-Auswahl

The existing ThreadDesk matrix parser accepts one additional block:
`<!-- bigplan-cli-scope:v1:qwen -->` … `<!-- /bigplan-cli-scope:qwen -->`.
Its JSON has `schema_version: bigplan.cli-scope.v1`, `cli: qwen`,
`adapter: qwen_acp`, `authority_ref`, `checked_at`, `expires_at`, `read_only`,
and `capability` using the existing Capability schema. It contains no executable,
token, endpoint or task grant. The exact block and document revision are bound in
the existing matrix hash / ThreadDesk receipt.

Die globale Acht-CLI-Matrix behält ihre ursprünglichen Daten und ihre TTL.
Ein Scoped-Block gilt nur für die explizite CLI-, Modell- und Effortwahl am
genannten Adapter, höchstens 24 Stunden und nur innerhalb seines Lesescopes.
Der separate Runtime-Access-Beleg muss ebenfalls frisch sein und Version und
Modell bestätigen. Fehlende, doppelte, widersprüchliche oder abgelaufene Blöcke
gewähren keine Ausführung. Prosa oder ein neues Notizdatum erneuern keine TTL.

## Existing Core/Team integration

Use the existing `ThreadDeskSource` / `DelegationGuard`; no second router,
dispatcher, queue or service is needed. A managed native Qwen profile supplies
`Task.execution_adapter="qwen_acp"`. The native routing path derives this from
the actual agent kind, never from model output.

For an already owned private Core/Team entry point, construct `Task` from the
actual fixed task ID, prompt, CWD, timeout and ownership reference. Set explicit
CLI `qwen`, model and effort. Pass the actual `AgentInput` and `AgentConfig`:

```python
decision = guard.validate_qwen_task(task, args=args, config=agent)
# Preserve the original sealed request, grants and existing Core/Team lifecycle.
# Immediately before the native effect, including after intervening awaits:
guard.validate_qwen_task(task, args=args, config=agent, expected=decision)
```

The hook probes only `qwen --bare --safe-mode --version` and the public selected
authentication setting; it never authenticates, prompts a model or reads tokens.
It requires the existing subscription, configured model/MEDIUM, fixed executable,
read-only task arguments, no native local tools/resume and only the configured
read operations / `read_queries` grants. A historical broader AgentConfig does
not widen that task's explicit grants. Source revision/hash, runtime, task,
actual arguments and agent configuration are rechecked against `decision`.

## Actual dispatcher/effect binding

The existing owner can compose the reviewed adapter at **owned Core startup**:

```python
from kirabridge.capability_routing.qwen import ScopedQwenAdapter

native = bridge.agents.adapters["qwen_acp"]
guarded = ScopedQwenAdapter(bridge, native, guard)
bridge.agents.adapters["qwen_acp"] = Observed(guarded)
```

`Observed.execute` must forward its actual `task`, `args`, `config` and keyword
arguments to the inner adapter. The wrapper derives its Task from the actual
dispatcher-packed prompt after `seal_request`, not a preconstructed work-body
lookalike. It checks the real Core record, Team owner/seal, worker scope, current
Core lease owner/receipt/attempt/expiry and CWD identity. It supplies the Qwen
adapter's existing `before_spawn` callback, which rechecks the same binding,
fresh authority, actual arguments/configuration and lease after metadata IO,
immediately before native `spawn_process`.

Keine zweite Queue, kein neuer Dispatcher/Store und keine Sessionübernahme.
Der Wrapper erstellt oder löscht keine Verzeichnisse, Credentials oder Historien;
Ergebnis, UNKNOWN und Cleanup bleiben beim ursprünglichen Qwen-Adapter. Seine
Konstruktion ist kein Hotreload-Protokoll für einen bereits laufenden privaten
Core. Ein Prozess ohne vorhandenen Setter erhält die Anbindung nicht durch einen
Dateiedit oder externen Vorabcheck. Aktivierung benötigt einen gesondert geprüften
Start-/Idlepfad des bestehenden eigenen Ausführers; fremde oder zu erhaltende
Prozesse werden dafür nicht ersetzt. Kein `TemporaryDirectory`-Kontext um bereits
vorhandene Runtime-/Store-/CWD-Pfade.

Der Hookbeleg ist **keine** Core-Ausführungsberechtigung, Claim-Übernahme,
fachliche Abnahme oder Erlaubnis zum Replay eines UNKNOWN. Der bestehende
Aufrufer muss seine native Effektgrenze anbinden; ein einmaliger Vorabcheck
ersetzt den abschließenden Recheck nicht. Für ein künftiges Schreibpaket oder
einen anderen Adapter ist dieser begrenzte Lesebeleg nicht ausreichend.

No production profile/service changes or real model calls are part of the
parser/hook checks. Effective backend-model identity remains unverified unless
independent native evidence provides it.
