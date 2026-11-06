# KiraBridge 0.8.0rc39 · local Intel CLI modules M1

Separates program semantics into explicit Codex and Grok Build adapters with a
small versioned contract and capability inventory. Shared Terminal identity,
focus, native key/paste transport, permissions, task idempotency and reservations
remain common. Existing helper imports and other isolated CLI providers remain
compatible.

Codex's captured copy/transcript/model views receive precise action semantics.
A single bound Escape can return to an observed composer; Enter in the model or
copy view is refused. Exact `/status` and `/model` tasks distinguish transmitted
input from actual CLI status/menu acceptance. No model/effort/permission selection
or automatic retry is introduced. Grok retains its own literal-input behavior
without claiming Codex navigation or status interpretation.

Local Intel candidate only; no public release or cloud build. Native tests,
simulations and pending real browserchat acceptance remain separate. Details:
[M1 architecture](plans/TERMINAL-CLI-MODULES-20261104.md) and
[evidence/delivery](TERMINAL-CLI-M1-EVIDENCE-20261104.md).
