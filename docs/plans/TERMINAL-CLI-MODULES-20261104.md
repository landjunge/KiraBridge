# Terminal / CLI modules M1 · 4 November 2026

Task **KB-MODULAR-CLI-20261104-M1**, one writer Codex; Kira coordinates real
browserchat acceptance. Base: `ef65f65d0a65241c8a60190838fd5525d00206c0`, preserving
the installed RC38 repair `5af2e788d48f56b39c45d4b763a76a16553df756`.
Branch: `feat/terminal-cli-modules-m1-20261104`. No new service, provider account,
public release or cloud build belongs to this package.

## Ownership and migration

`cli_adapters.contract.ProgramAdapter` and immutable `Capabilities` describe
program semantics. `AdapterRegistry` explicitly registers Codex and Grok Build;
unknown programs fail closed. The registry does not grant execution permission,
authenticate a process or establish readiness. `session_catalog` describes the
adapter/capabilities for a recognized agent; `session_read` observes its current
UI and separately bound work state. An empty composer alone never proves an idle
agent. Existing structured agent/provider connectors remain separate.

| Layer | Owns |
| --- | --- |
| Terminal transport / SessionManager | App, visible window, logical tab, TTY, PID/birth/image, focus, native reads and shared key/paste transport |
| Common input/Return/navigation coordinators | Permission, exact released intent, idempotency, reservations, fresh target/cursor checks, effect boundary and evidence |
| Codex adapter | Composer/footer/wrap grammar, draft and Return semantics, copy/transcript/model views, slash validation and observed command results |
| Grok Build adapter | Existing boxed composer and literal insertion grammar; explicit absence of separate Return/menu navigation/status interpretation |

The old readiness, Return, paste-rendering and resume helpers remain compatible
imports, delegating into the adapter package. Retained Codex/Grok parsing helpers
live in the internal migration module `_legacy_readiness`; the common Terminal
and Return paths contain no program footer/menu grammar. The old renderer bodies
are preserved. Native keyboard delivery has one implementation: `press_key`;
`press_return` is its compatible Enter wrapper.

Adapters perform no native mutation or task dispatch. Their observations propose
semantic actions; they cannot unlock a target, release buffered input or approve
a dialog. The coordinator releases the **original exact task** once, validates
the effective payload, then performs at most one supported navigation key, one
paste and one Return. A transport result lost after an effect stays UNKNOWN;
replaying its task does not send another key. Historical UNKNOWNs remain intact.

## Supported first package

Codex's exact `⌃c copy · enter copy & follow · esc clear` toolbar denotes a copy
view: Return is **not** prompt submission. Only a proven empty composer beneath
that complete toolbar permits its single Escape exit. The captured transcript
view requires the complete `↓ Back to bottom · esc` control plus the model row
and `esc latest` footer, including only its known optional warning badge. This
classifies the observed UI without claiming that a person scrolled it. Return on
a cursor-bound draft first exits that view and must observe the identical draft
before sending one Enter. Empty copy/transcript views may be exited within an
explicit `submit=true` text task.

The complete captured `Select Model and Effort` menu has numbered model rows,
one selected/current model and `enter select · esc back`. It exposes only
`return_to_input`. Enter there is refused. Escape exits once, and success requires
a freshly observed empty composer; no model, reasoning, tariff or permission
selection is confirmed. Arbitrary menus and unknown dialogs remain unsupported.
No Escape loop or generic keyboard-control bypass exists.

Only exact `/status`, `/model` and the retained `/resume` command are accepted
for Codex submission. Wrapped or indented argument drafts do not bypass this.
The input-buffer release suffix is removed by the existing policy before semantic
validation. `/status` acceptance requires a **new** status block after the prior
transcript with the CLI banner and Model/provider/Directory/Permissions/Session
fields. `/model` acceptance requires the actual complete menu. Unknown or lost
output remains unconfirmed, with no repeated input. Grok's existing literal
slash forwarding remains; its result is explicitly uninterpreted rather than
treated as Codex status or a Codex menu.

Evidence distinguishes `text_transferred`, `insertion_verified`, `return_sent`,
`acceptance_observed`/`acceptance_evidence` and `response_observed`. Literal input
does not create an agent work message or claim its answer. The existing bound
Codex reply observer remains the separate work-message evidence path.
Shell handling, including intentionally typed spaces and `visible_input_unknown`
versus process occupancy, retains RC38's exact safety rules.

## Existing API and Kira acceptance

No new MCP endpoint. Use the existing `session.input` task via `action_request`
with unique `task_id`/`idempotency_key`. A fresh `session_read` supplies the current
`next_cursor`, exact pane/shell PID and agent PID. The explicit exit request is:

```json
{
  "request": {
    "task_id": "<unique task ID>",
    "idempotency_key": "<unique idempotency key>",
    "operation": "session.input",
    "arguments": {
      "pane_id": "<fresh catalog handle>",
      "expected_pid": 123,
      "expected_agent_pid": 124,
      "key": "escape",
      "expected_cursor": "<fresh next_cursor>"
    }
  }
}
```

Pass this envelope to `action_request`, using fresh values instead of example PIDs.
Escape requires the exact agent and captured cursor. A text request uses `text`
and `submit=true`, without `key`/cursor fields. To submit an existing draft use
the same observed-key form with `key="enter"`. Status/menu tests use exact
`text="/status"` or `text="/model"`, `submit=true`; leaving the model menu is a
separate observed Escape. Check `return_sent` versus CLI acceptance and actual
response evidence. On UNKNOWN, inspect that same task; do not resubmit it under
a new ID. Structured queue/API and visible Terminal remain selectable routes,
with no silent fallback between them.

Kira must perform fresh unique-marker tests from the real browserchat, including
copy/transcript recovery, status, model exit, resumed text and focus/tab change.
The two old chat markers were manually completed and must not be resent. Local
testing below is **not** that acceptance.

## Extension contract and limits

Implement `ProgramAdapter`, register a unique explicit name, and add pure observed
frames plus coordinator regression tests. Declare only implemented capabilities;
unsupported navigation/Return/result interpretation must fail closed. The fixture
adapter test reaches the existing readiness, insertion and Return facades without
Terminal changes. Dependency tests forbid imports from adapters back into the
task dispatcher, Terminal transport or shared readiness/input/Return facades.

This is not universal visible execution support for every installed CLI. Existing
configured bindings and process recognition still apply. `bound_turn`,
`bound_reply`, CWD/wrap proof currently require compatibility with the retained
Codex metadata/reply/rendering backends; new adapters must not advertise them
without implementing that backend contract. Grok's structured connectors and the
other existing isolated provider adapters are not replaced. New layouts stop
conservatively until characterized. No mouse development or App-Server/ACP
rewrite is included.

## Evidence and delivery

Private raw native/account-bearing evidence and checkpoints:
`~/.local/share/kirabridge/backups/modular-cli-20261104-m1`.
See the companion [M1 evidence and delivery record](../TERMINAL-CLI-M1-EVIDENCE-20261104.md).
The final source review is independently read-only and pinned by file hashes in
`independent-final-review.json`; it is separate from executed tests and deployment.

Readme DE/EN receive only the development-documentation link. Public RC36 download
links remain the published package; this local candidate has no public download.
No website/image change or deployment is needed for this internal module package.
