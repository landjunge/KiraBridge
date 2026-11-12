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

Der Hookbeleg ist **keine** Core-Ausführungsberechtigung, Claim-Übernahme,
fachliche Abnahme oder Erlaubnis zum Replay eines UNKNOWN. Der bestehende
Aufrufer muss seine native Effektgrenze anbinden; ein einmaliger Vorabcheck
ersetzt den abschließenden Recheck nicht. Für ein künftiges Schreibpaket oder
einen anderen Adapter ist dieser begrenzte Lesebeleg nicht ausreichend.

No production profile/service changes or real model calls are part of the
parser/hook checks. Effective backend-model identity remains unverified unless
independent native evidence provides it.
