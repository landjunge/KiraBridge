# Native Codex root binding

Development source, macOS Intel and the locally observed Codex 0.169.0 protocol.
Source tests and a read-only existing-host observation do not activate delivery,
establish live acceptance, publish a package or update an installation.

## Problem and behavior

A saved Terminal.app pane, shell PID and Codex PID can disappear while the logical
Codex task remains active on its native host. Two live Codex terminals then leave
the old physical refresh rule unable to select a destination. The native route
delivers a **new direct message to the administratively assigned ordinary root**
through its existing host, independently of those terminal handles.

The configuration assignment is the authority. A thread ID in message text,
`CODEX_THREAD_ID`, a title, CWD, selected tab, idle sibling or child tool call never
changes the default recipient. The route does not automatically follow a different
logical root without a new verified administrative assignment. Such a selection
needs an actual owner/host selection or continuity proof; this implementation
does not invent a selection lease. This is a physical continuity repair for the
assigned root, not a universal replacement for session selection.

With the option absent, the existing terminal route stays in use. With it present,
only new direct messages addressed to `codex` use the native root. Explicit
`session.input` and `interim_session` handles retain their own selected target.
Passive inbox notes do not acquire a notification or dispatch attempt.

## Assignment and fresh observations

An administrator records the exact authorized root, its session tree, the native
source returned by `thread/read`, its Codex home and supported executable:

```toml
[visible_handoffs.native_codex]
thread_id = "11111111-1111-7111-8111-111111111111"
session_id = "11111111-1111-7111-8111-111111111111"
codex_home = "/Users/operator/.codex"
host_executable = "/Users/operator/.codex/packages/app-server-daemon/releases/0.169.0-x86_64-apple-darwin/bin/codex"
source = "vscode"
protocol_version = "0.169.0"
```

Those IDs and paths are examples, never a default. The administrator first proves
the requested ordinary root from the actual owner context and read-only host
responses. Registering a worker's environment as the global `codex` recipient is
not supported. No separate daemon, bridge, queue, account or provider is created.

Every prepare and submission reads the existing private daemon registry and
enumerates only that exact process's current Unix socket names. There must be one
canonical, user-owned socket in a private directory. Connected descriptors naming
the same socket are deduplicated; multiple possible endpoints are rejected.
Darwin's connected peer PID, OS UID, process start time, native executable path and
managed app-server arguments must match the registry and assignment. The socket
inode is checked across connection establishment. A new host PID, socket pathname
or inode can be accepted automatically through these same checks; no old physical
binding is rewritten.

The existing Unix WebSocket is initialized and `thread/read(includeTurns=false)`
must return the assigned thread and session, matching source, no parent or attached
owner, and `canAcceptDirectInput=true`. Unloaded threads, child/sibling IDs, missing
root proof, dialogs/approval activity and ambiguous observations receive no input.
The adapter never calls `thread/start`, `thread/resume`, interrupt or any terminal
operation. A changed package version requires a reviewed compatible protocol pin.

`thread/turns/list(limit=1, itemsView=summary)` supplies the current active turn. A
working root uses `turn/steer` with **that exact `expectedTurnId`**. An idle root
uses `turn/start` on the same assigned thread, without model, effort, permissions or
provider overrides. A changed observed turn between prepare and submission is
refused before the attempt, without fallback to another turn, sibling or operation.
The existing `allow_interim_messages=false` option also disables native busy input,
including when changed during awaited preflight. Codex 0.169 may append a start
request to a turn that became active concurrently; the destination is still the
same assigned root, and an idle admission retains ordinary model-run accounting.

The protocol fixtures retain the observed 0.169 distinction: steer returns
`{turnId}`, while start returns `{turn}`. The upstream transport implementation
also identifies the Unix transport as WebSocket:
[pinned official transport source](https://github.com/openai/codex/blob/5cb38e79842a0e0a6dca5bb97874163e8ee50129/codex-rs/app-server-transport/src/transport/unix_socket.rs).
Generated schemas from the actual installed 0.169 binary are retained in the
private evidence bundle; they take precedence over unrelated current examples.

## Attempts, receipts and restart

The existing DirectDelivery driver admits only the new stored message and uses its
existing claim, recipient lease, job, events, audit and completion notices. After
awaited host reads it rechecks the exact configuration fingerprint, sender grants,
claim/run ID, receiver scope, holds, withdrawal and prior receipt/ACK. Immediately
before native IO it records `message.native_submitting`, with original message ID,
run ID, host generation, logical target and expected turn. The original UUID is
also sent as `clientUserMessageId`; it is correlation, not permission to retry.

Successful RPC acceptance records `message.native_submitted` and the existing job's
`completion_scope=native_input_delivery`. This proves submission only. It does not
fabricate an inbox read, transport receipt, agent ACK, final reply or work completion.
`message_get` and completion notices report those limits explicitly. Recipient
fetch/ACK and responses retain the existing authenticated message operations.

Any cancellation, rejected or malformed response, disconnect or timeout after the
durable attempt remains UNKNOWN. Reads, repeated send keys, process replacement,
host refresh and daemon restart do not replay it. Old failed/UNKNOWN/held messages
and their receipts remain unchanged. There is no historical queue release and no
second retry loop. Busy delivery retains the existing delivery-only model-budget
classification; an idle start consumes the ordinary model-run budget.

## Minimal operational rollout

1. Review the frozen commit, focused test logs and private root/host evidence. Check
   current installed source, config hash, dispatcher work and the proposed Mac
   assignment separately from Debian's independent account/receiver.
2. Use the existing authorized Mac installation process in its owned installation
   window, with current-state backup and rollback. Preserve the current database,
   messages, receipts and running Codex sessions. Do not launch/restart Codex, open
   a replacement terminal, change the Debian service or modify the old TTY overlay.
3. Install the reviewed source and add only the freshly verified native root
   assignment. Re-read the exact configuration and run the adapter's read-only
   `prepare` before admitting new input. A mismatch stops only this unproven route.
4. Use one genuinely new marked user-authorized message for live acceptance. Correlate
   its immutable original ID, native attempt, expected turn, host acceptance and
   actual root observation; inspect the parallel session as a negative control.
   Fetch/ACK and reply are separate evidence. Never reuse a failed diagnostic ID.
5. If a rollback is needed, remove this optional assignment and restore the backed-up
   runtime through the existing installer. Preserve current data and all uncertain
   attempts. A rollback does not turn historical messages into new work.

No UI/website or download change follows from this internal optional development
route; both READMEs link this contract. Windows/Linux, published packages and live
message acceptance remain separate outcomes.

## Teamturns ohne feste Bindung

`execution_scope = "existing_native_codex_root"` auf `TeamWorkerConfig` wählt im
`agent.execute`-Zweig `NativeCodexTurns`. Der Dispatcher übergibt `worker.cwd`.
`authorize_execution` verlangt, dass das Auftrag-cwd nach `expanduser().absolute()`
dem Worker-cwd entspricht. `discover` liest `thread/loaded/list`. Ist diese
Id-Liste keine Liste oder länger als 16, ergibt das
`native_codex_target_not_ready`. Sonst bleibt ein geladener, elternloser Root:
`parentThreadId` und `attachedToThreadId` sind null, die Quelle ist `cli`,
`vscode` oder `appServer`, und das aufgelöste Thread-cwd entspricht dem
aufgelösten Auftrags-cwd. Eine andere Anzahl ergibt
`native_codex_root_not_unique`. Ist der beobachtete Vorgang `turn/steer`, lehnt
der Teampfad ab (`native_codex_target_not_ready`) und ruft nur `turn/start` auf.
Der Lauf setzt `terminal_input_attempted` auf false. Die Threadauswahl verwendet
kein Pane, keine Terminal-PID und keinen Rollout-Pfad. `CodexHost` prüft die
Hostidentität (`native_codex_host_unverified`, dazu `codexHome` und
`codex-tui/<major>.<minor>` gegen `protocol_version`). Ein Patch einer
unterstützten 0.169-Minorlinie und Plattform unter
`codex_home/packages/app-server-daemon/releases/<version>/bin/codex` bleibt
gültig. `protocol_version` entspricht entweder `^0\.169\.[0-9]{1,3}$` oder exakt
`0.171.0`; der Standard bleibt `0.169.0`. Der 0.171-Support lockert weder den
Managed-Host-Pfad noch Socket-, Peer-, Root- oder Turnprüfungen. Patches derselben
0.169-Minorlinie bleiben zulässig; 0.171 User-Agent und Releasepfad müssen exakt
`0.171.0` sein. Der Worker braucht
`[visible_handoffs.native_codex]` mit `codex_home`, `host_executable` und
`protocol_version`; Agent und Art müssen `codex` sein. Fehlt die Bindung, ist
der Code `native_codex_unconfigured`.

## Team turns without a fixed binding

`execution_scope = "existing_native_codex_root"` on `TeamWorkerConfig` selects
`NativeCodexTurns` from the `agent.execute` branch. The dispatcher passes
`worker.cwd`. `authorize_execution` requires the task cwd, after
`expanduser().absolute()`, to equal the worker cwd. `discover` reads
`thread/loaded/list`. A missing id list or more than 16 ids raises
`native_codex_target_not_ready`. Otherwise it keeps a loaded, parentless root:
`parentThreadId` and `attachedToThreadId` are null, the source is `cli`,
`vscode` or `appServer`, and the resolved thread cwd equals the resolved task
cwd. Any other count raises `native_codex_root_not_unique`. When the observed
operation is `turn/steer`, the team path refuses
(`native_codex_target_not_ready`) and calls only `turn/start`. The run sets `terminal_input_attempted` to false.
Thread selection uses no pane, terminal PID or rollout path. `CodexHost` checks
host identity (`native_codex_host_unverified`, plus `codexHome` and
`codex-tui/<major>.<minor>` against `protocol_version`). A patch of a supported
0.169 minor line and platform under
`codex_home/packages/app-server-daemon/releases/<version>/bin/codex` stays valid.
`protocol_version` matches `^0\.169\.[0-9]{1,3}$` or exactly `0.171.0`;
the default remains `0.169.0`. The 0.171 support does not relax managed-host path,
socket, peer, root, or turn checks. Patches on the existing 0.169 minor line
remain supported; the 0.171 User-Agent and release path must be exactly `0.171.0`.
The worker needs
`[visible_handoffs.native_codex]` with `codex_home`, `host_executable` and
`protocol_version`; agent and kind must be `codex`. A missing binding raises
`native_codex_unconfigured`.
