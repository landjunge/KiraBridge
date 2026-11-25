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

With the option absent, direct messages retain the existing terminal route. With it
present, new direct messages addressed to `codex` and sealed team work with
`execution_scope = "existing_native_codex_root"` use the same native root. Explicit
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
must return the assigned thread and session, matching source, and no parent or
attached owner. On the pinned 0.171.0 protocol, preflight can restore an explicitly
persisted `notLoaded` root by its exact ID with `thread/resume(excludeTurns=true)`.
Codex loads its own history. KiraBridge supplies no alternate path, history, CWD,
model or permission override. A fresh read after this operation must confirm the
same root and `canAcceptDirectInput=true` before input is considered. The later
submission preflight only reads. A child, sibling, missing or ephemeral unloaded
thread, unsupported protocol, dialog or approval prompt receives no input. No
`thread/start`, interrupt or terminal operation is used.

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

Successful RPC acceptance records `message.native_submitted` and
`completion_scope=native_input_delivery` on the original job. With
`request_reply=true`, the driver observes the newly started turn by exact ID
and stores the final text on the original job only after verifying the sole
user input and the sole final reply in order. The text is then retrievable using
`message_get` with the original message ID and in its completion notice.
An unverified turn, timeout or steer without a reliably attributable reply stores
a concrete UNKNOWN reason on that job. Terminal-output eviction does not remove
the saved result. An observed reply does not fabricate a mailbox message, inbox
receipt, agent ACK or project completion. Authenticated mailbox answers retain
their separate normal operations.

Without a durable acceptance receipt, interrupted input remains UNKNOWN.
If the daemon stopped after persisting an exact `turn/start` acceptance while
waiting for its requested reply, startup restores only the reply observation.
The current configured binding must match the recorded fingerprint and the
original job and acceptance event must match. The observer reads the accepted
turn from Codex, including persisted history, and records a verified reply or a
concrete UNKNOWN reason. It never resubmits input. Previously settled messages,
holds and their receipts remain unchanged. Busy delivery retains the existing
delivery-only model-budget classification; an idle start consumes the ordinary
model-run budget.

## Minimal operational rollout

1. Review the frozen commit, focused test logs and private root/host evidence. Check
   current installed source, config hash, dispatcher work and the proposed Mac
   assignment separately from Debian's independent account/receiver.
2. Use the existing authorized Mac installation process in its owned installation
   window, with current-state backup and rollback. Preserve the current database,
   messages, receipts and running Codex sessions. Do not launch/restart Codex, open
   a replacement terminal, change the Debian service or modify the old TTY overlay.
3. Install the reviewed source and add only the freshly verified native root
   assignment. Re-read the exact configuration and verify the target through
   `thread/read`. A mismatch stops only this unproven route.
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

## Teamturns mit derselben festen Bindung

Automatische Folgeaufträge für
`execution_scope = "existing_native_codex_root"` verwenden dieselbe in
`[visible_handoffs.native_codex]` konfigurierte Thread-/Sitzungsidentität wie
Direktnachrichten. Der versiegelte Auftrag behält das konfigurierte
Arbeitsverzeichnis des Team-Workers. Der native Root hat sein eigenes,
vom App-Server bestätigtes Arbeitsverzeichnis. KiraBridge prüft es erneut
vor der Eingabe und beim Lesen der Antwort. Beide Arbeitsverzeichnisse dürfen
sich vom lokalen Nachrichtenempfänger unterscheiden. Auch bei zwei passenden
Roots bleibt die Zuordnung erhalten. Ist der gebundene Root beschäftigt,
startet der Teampfad keinen zusätzlichen Turn und steuert den bestehenden
Turn nicht. Bestätigt der App-Server, dass der gebundene Root aktiv ist,
bleibt der automatische Folgeauftrag unter seiner ursprünglichen ID bis
zur nächsten Prüfung in der Warteschlange. Der bestehende Ablaufzeitpunkt
gilt weiter. Nach Übernahme des Auftrags wird ein unklarer Ausgang unter
der Original-ID festgehalten. Der Abschluss des bestehenden Workerauftrags
und die daraus erzeugte Folgezuordnung bleiben im selben Bridge-Speicher.

## Nachrichten an den gebundenen Koordinator

Neu eingereihte Team-Nachrichten, die ausdrücklich an den nativen `codex`-Koordinator
adressiert sind, nutzen die separat konfigurierte `[visible_handoffs.native_codex]`
Bindung; dieser Pfad wählt keinen Root anhand von `TeamWorkerConfig.cwd` aus. Ein
nachweislich aktiver Turn wird mit seiner exakten `expectedTurnId` gesteuert; ein
nachweislich inaktiver Root erhält `turn/start` auf demselben gebundenen Thread.
`allow_interim_messages=false` sperrt nur das Steuern eines aktiven Turns. Die
Nachricht erhält das normale native Agenten-Budget-Gate. Scope, Grants, Turn-Freshness
und der persistierte Einmalversuch bleiben vor dem Input geprüft. Historische
`idle_pending`-Einträge werden nicht neu eingereiht; native Annahme ist kein ACK.

## Team turns with the same fixed binding

Automatic follow-ups with `execution_scope = "existing_native_codex_root"`
use the same thread and session identity configured in
`[visible_handoffs.native_codex]` as direct messages. The sealed request retains
its team worker cwd. The bound native root keeps the absolute cwd reported by
the authenticated App-Server, which is checked again before submission and when
reading its reply. The team worker, native root and local message receiver may
each have a different cwd. Another root with the same cwd has no effect on
assignment. A team turn requires the assigned root to be idle
and is never sent using `turn/steer`. When a read of the exact bound root
confirms that it is active, an automatic follow-up keeps its original
queue entry, completion link and expiry until the next check. An ambiguous
outcome after the claim is recorded on the original task. The existing
SQLite team, work and completion records retain their IDs across daemon restart.

## Messages to the bound coordinator

Newly queued team messages explicitly addressed to the native `codex` coordinator
use the separately configured `[visible_handoffs.native_codex]` binding; this path
does not discover a root through `TeamWorkerConfig.cwd`. A verified active turn is
steered with its exact `expectedTurnId`; a verified idle root receives `turn/start`
on that same bound thread. `allow_interim_messages=false` only disables steering an
active turn. This path uses the ordinary native agent budget gate. Scope, grants,
turn freshness and the durable one-attempt boundary remain checked before input.
Historical `idle_pending` entries are not re-enqueued; native acceptance is not an
ACK.
