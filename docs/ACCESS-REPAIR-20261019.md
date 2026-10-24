# ChatGPT access repair — deployed, bounded acceptance

The operator explicitly authorized full Mac file, terminal, clipboard, process and
selected agent/session access. The loaded `chatgpt` identity retains automatic
approval, every catalog operation, roots/read_roots/terminal_roots `/`, arbitrary
executables and Codex/Grok profiles. Authentication, bearer credentials, loopback
binding, other identities and macOS permissions were preserved. Added only
`session.inspect` and `session.input`. No Desktop Commander dependency.

## Execution is independent of Events

`task_request` and `task_submit` do not require an Events subscription in the current
backend or deployed facade. Existing ChatGPT connector metadata still requires the
historical root `completion_subscription` before requests reach the server.
An empty string works as **no subscription** with that historical binding; it does
not create or impersonate a subscription. The optional facade strips this legacy
field. The platform cache has not been proven cleared.

New tools `action_request` and `action_submit` expose the same authorized,
idempotent task implementation with fresh names, without this historical field.
Retrieve results through `task_get` and `task_events`; notification setup is optional.
`bridge_health.task_submission` describes both paths to old clients.
The refreshed tools still need to be discovered by the ChatGPT host. This session
cannot trigger that host action. Official refresh instructions:
https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata

`read_query` supports bounded `file.read` with offset or tail (65536 bytes maximum),
`file.list` (100 entries), and `terminal.output` for owned Bridge tasks. It enforces
existing capabilities, roots, state-directory exclusion and descriptor-based
no-symlink traversal. No task dispatch or Event subscription is involved.

Example direct read:

```json
{"query":{"operation":"file.read","path":"/absolute/path/to/session.jsonl","tail":true,"max_bytes":32768}}
```

## Selected sessions and honest limits

`agent_status` discovers process metadata; this alone neither identifies a
controllable agent session nor proves project progress. For an explicitly selected
accessible tmux pane, `session_catalog` provides pane_id and expected_pid;
`session_read` reads its available scrollback. Submit `session.input` through the
normal task path with that exact pair, literal text and optional submit=false.
Changed selection is rejected; input is never automatically replayed after an
uncertain outcome. Transport acceptance does not mean the agent processed input.

No accessible default tmux server was found in production. Existing Codex/Grok
processes were not attached or interrupted, and no real agent prompt was sent.
Non-tmux interactive terminals require their actual supported control interface;
this repair does not claim to provide arbitrary GUI-terminal attachment. File
logs remain readable through authorized direct reads. Existing Bridge-owned
managed agent/message/handoff execution remains available. Provider availability
and provider costs remain separate from local authorization; no Grok calls were made.
macOS privacy/root protections were not changed or claimed bypassed.

## Actual evidence

- Real connected ChatGPT App: file.write completed; task_submit file.read returned
  `KIRABRIDGE_APP_FILE_OK`; terminal.execute returned `KIRABRIDGE_APP_TERMINAL_OK`,
  exit 0. Results were fetched with task_get, including after reload. These calls
  used the historical empty-field compatibility path, without any subscription.
- Production adapter: direct read returned the actual App-created file; fresh
  action_request moved it and action_submit deleted it, both completed without
  any subscription field. This is an operator probe, not a host metadata-refresh proof.
- 51 targeted tests passed (6.38 s), including actual isolated HTTP, authorization,
  idempotency, output limits and input/capture on a private real tmux test server.
  This fixture was a harmless local Python reader, not Codex or Grok.
- Exact staged commit tree was separately exported and tested without the other
  working-tree changes: 18 tests passed (6.34 s). One initial App health call after
  reconnect timed out; the subsequent actual App task_get succeeded.
- Reload happened under BEGIN IMMEDIATE with 0 active tasks / 0 receiver jobs;
  only own Bridge/tunnel were reloaded. Existing rights and authentication preserved.
  Private config and database backups remain outside Git.

[Actual App calls](../examples/access-repair/run-20261019-01/chatgpt-app-evidence.json),
[production adapter](../examples/access-repair/run-20261019-01/production-adapter.json),
[activation](../examples/access-repair/run-20261019-01/activation.json).

`chat-events-receipt-20261019-01` was **not started**. No real subscription,
automatic ChatGPT completion delivery or original-chat event processing is claimed.
The fresh action tools are server-tested; their new binding in ChatGPT remains
an external metadata-refresh acceptance step. Thus this is not a claim of complete
end-to-end acceptance of every interactive session or the optional Events path.

The access-repair commit deliberately excludes the earlier uncommitted Events,
completion-consumer, demo and receiver work. Those working-tree changes are kept.
The historical empty-field bridge is deployed in that optional Events facade;
it is not introduced as a new required field into the access-repair tool schemas.
