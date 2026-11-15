# Native ChatGPT message events: implementation, host acceptance pending

The optional Events envelope now exposes `kirabridge.message.created` for messages
addressed to the authenticated principal. It wraps the existing `kirabridge connect`
process; the current daemon, dynamic ThreadDesk tools and Library aliases remain on
the existing path. It does not require an SDK upgrade or a second Bridge daemon.
This source change does not activate a tunnel, sender, subscription or ChatGPT turn.

[OpenAI's current MCP Events contract](https://developers.openai.com/plugins/build/mcp-events)
supports Events through `initialize` as well as MCP2 discovery. Host-provided
subscriptions and signed webhooks trigger work in a subscribed Work chat. Supported
surfaces include Work on the web and desktop Work with Cloud. Delivery is
asynchronous; a `2xx` response is not proof of a visible assistant reply. Voice/Live
and a measured latency remain separate acceptance questions.

## Integration

Run the opt-in `integrations/chat-events/connect.py` with the same configuration,
authenticated principal and an explicit child command pointing at the current
production front. The wrapper handles the three Events methods itself, advertises
`events` only when those handlers exist, and forwards all other requests and
responses without reconstructing tool schemas. Only the `initialize` response is
extended and its obsolete unconditional no-wakeup instruction corrected. The
normal, unwrapped `connect` command remains unchanged.

```sh
/path/to/current-front/.venv/bin/python /path/to/reviewed-source/integrations/chat-events/connect.py \
  --config /path/to/private/config.toml --principal chatgpt \
  --state /path/to/private/event-state \
  --allow-callback-host ACTUAL_HOST_FROM_HOST_SUBSCRIPTION \
  -- /path/to/current-front/.venv/bin/kirabridge \
  --config /path/to/private/config.toml --principal chatgpt connect
```

The separate persistent sender uses the same journal and callback allowlist:

```sh
/path/to/current-front/.venv/bin/python /path/to/reviewed-source/integrations/chat-events/serve.py \
  --config /path/to/private/config.toml --principal chatgpt \
  --state /path/to/private/event-state \
  --allow-callback-host ACTUAL_HOST_FROM_HOST_SUBSCRIPTION --sender-only
```

These are integration commands, not a claim that a service or tunnel was changed.
Do not guess the callback host, URL or secret. An empty allowlist rejects callback
verification safely. Actual activation needs a pinned source/config manifest,
idle-state check, independent review and a rollback for the one existing front.
No model or paid API request is made by these processes.

## Storage and access

The existing private Events journal is extended additively with event name, filter
arguments and a source watermark. Existing task subscriptions migrate to their
original event type and retain task routing. New message subscriptions bind
`recipient` to the authenticated principal and optionally filter `sender`.
They capture a watermark before callback verification, exclude older inbox entries,
and retain that watermark on an active refresh and sender restart. Resuming a
stopped, revoked or expired subscription starts at the current watermark and
pauses old pending deliveries; historical messages are not automatically released.

Messages are read from the original `messages` table. The source is never ACKed,
rewritten, resent or dispatched to another model. Each subscription/message pair
gets one stable event ID and one durable delivery record. Retries reuse the exact
body and event ID, with a newly generated signature. Before each delivery the
existing authenticated backend `message_get` rechecks source access and the
recipient. A failed or revoked check sends no payload. Events from another
principal's subscription cannot be selected by the sender.

Callback challenge verification, HTTPS, public-address validation, IP pinning,
TLS hostname verification, no redirects, bounded responses, retry limits and
secret rotation reuse the existing EventPush implementation. Callback credentials
are private journal data and are not returned in status or errors. Message text
is bounded to 32768 characters with `text_truncated`; the original `message_id`
allows an authorized `message_get` for the full text. Event payloads are data, not
instructions to the assistant.

## Acceptance

Targeted tests cover a real subprocess envelope, the original stdio proxy and HTTP
daemon, authorized MessageManager sends, native Events subscribe/unsubscribe,
signature-validated **mock** callbacks, recipient/sender filters, duplicate/retry
stability, revoked access, additive migration, and unchanged Library alias reads
through real ThreadDesk stdio. A mock callback is not ChatGPT.

The remaining genuine host acceptance is: rescan the existing plugin; verify the
Events catalog appears; create a subscription from the original supported Work
chat; receive the actual host callback/secret and verify the challenge; send a
correlated Codex message after the assistant turn ends; observe a new assistant
turn without a user prompt, message_receive, long poll or tool wait. Compare the
original message, subscription and event IDs and measure latency. Only that
independent chat observation proves the requested return ping. Mac-offline
operation must then be independently observed with both processes on the server.

## V2 lifecycle, sender readiness and activation order

The first candidate is superseded by a separate correction after independent
review found exit-status propagation, an unbounded EOF drain, and contradictory
error envelopes being accepted for authorization. The wrapper now propagates the
child's exit status (including signal status), allows at most two seconds of EOF
grace, then terminates only its own child with a three-second wait and a two-second
kill/reap bound. Output drain is bounded; incomplete drain is an error. SIGINT and
SIGTERM cancel once, permitting that cleanup. Other processes are never targeted.

Authorization rejects an unsuccessful MCP envelope before using positive IDs,
including conflicting `isError`, `success`, `ok`, and error wrapper/content fields.
An owned full `task_get` record may describe its task's failed execution; this is
source data, not a failed read. That exception requires its bound task/principal,
API version, state, operation and request hash, and never overrides `isError`.
Message bodies and processing records remain data and are not interpreted as
read-authorization envelopes.

A separate persistent sender must hold the existing private `sender.lock` and
publish a fresh private readiness marker. The marker is bound to the complete
parsed configuration, authenticated principal, source database and callback-host
allowlist. It contains no callback secret or credentials. A successful delivery
cycle refreshes readiness; cycle failure removes it, three consecutive failures
stop the worker, and shutdown marks it stopped. A missing lock, mismatch, stopped
worker or heartbeat older than fifteen seconds withholds the Events capability.
The existing tools continue through the original proxy. Event requests received
while unready fail closed. This is local transport readiness, not a host
subscription, webhook receipt, displayed message or latency guarantee.

The V3 correction closes two further independent restart/input regressions. Every
singleton acquisition creates a new random generation and immediately records
`starting` before backend startup. The lock lease and heartbeat must agree on that
generation, PID, kernel process birth identity, and a digest of the five runtime
Events source files as well as the complete route/config binding. A dead/reaped
sender's fresh heartbeat cannot authorize a starting replacement. Linux uses the
kernel process start ticks; macOS uses the kernel's microsecond birth timestamp.
Unsupported or unavailable process identity fails closed. Only a successful cycle
of the current generation may publish `ready`.

An early child exit while the host is still writing valid JSONL may close the
owned child's stdin. Only `BrokenPipeError`/`ConnectionResetError` raised by that
specific stdin write/drain are deferred for the existing bounded child-exit wait.
If the child exits during that wait, its exact status is returned after output
drain. If it stays alive, cleanup terminates/reaps it and the closure remains an
error. Host output, framing, and unrelated or late input errors still propagate.
Regression coverage includes the actual killed/reaped sender replacement with an
unavailable backend, 2.75 MB concurrent valid host input with child exits 0/23, and
the preserved error paths. These are local fixtures, not genuine host acceptance.

Use this activation sequence only after the exact source/overlay and a separate
independent review have passed; these instructions do not activate anything:

1. Pin the existing tunnel binary, complete private profile hash, daemon PID/source,
   unchanged configuration hash and current `connect` argv. Parse the **complete**
   installed configuration with the proposed runtime source and import dependent
   Bridge/MCP modules using the actual front interpreter. Check the source DB path
   and the actual backend's `message_get`/`task_get` schemas through authorized
   read-only MCP requests. A cold configuration subset is insufficient.
2. Extract the reviewed overlay onto an independent copy of the pinned front
   source. Do not hardlink or overwrite the active release. Use the installed
   interpreter/dependencies already proven compatible. Keep a fixed persistent
   journal outside the source release, for example
   `/home/daniel/.local/state/kirabridge-chat-events-server`; both processes must
   receive exactly that path, principal and host allowlist. Directory mode 0700,
   journal/lock/WAL/SHM files 0600, service `UMask=0077`. Never log callback URLs,
   signing secrets, authorization headers or credential files.
3. Verify the **outer installed tunnel transport** forwards Events methods to the
   child. An isolated `tunnel-client dev proxy` with loopback ingress, fixture auth
   and the same installed binary is an appropriate runtime-compatibility check.
   It does not attest the separately hosted OpenAI ingress edge or a true host
   subscription. Those remain part of final acceptance.
4. Coordinate one quiet MCP window with all active workers. Under a fresh short
   SQLite read transaction inspect active native tasks and queued/running receiver
   jobs, and record the exact snapshot. Do not switch with unknown/in-flight front
   calls or tasks. Recheck the daemon PID/config/profile hashes immediately before
   mutation. A new job or intervening profile change invalidates the window; no
   uncertain work is replayed to recover the window.
5. Save the original tunnel profile privately, preserving its exact bytes and
   metadata, with a hash and rollback receipt. Prepare a dedicated **user** sender
   service using the reviewed source and `serve.py --sender-only`, authenticated
   as `chatgpt`, with `Restart=no`, `UMask=0077`, and bounded stop timeout. This
   grants no new Bridge capability or receiver role. `codex_channel` remains the
   original producer; the sender only reads the authorized `chatgpt` inbox.
6. Start only that sender. Confirm the singleton lock is held, the same-route
   readiness marker stays fresh, initial backend readiness and source collection
   succeed, and a duplicate sender is rejected. No subscription or model work is
   created by startup. If readiness fails, stop this sender and leave the original
   tunnel command intact. Restart requires diagnosis; do not create a crash loop.
7. Replace **only** the selected existing profile command atomically after a hash
   CAS, with the wrapper command shown above and the exact old command retained as
   its child argv. All other profile fields, tunnel identity/runtime-key binding,
   daemon configuration, source DB, credentials, roles and services stay bytewise
   unchanged. Restart only the existing owned tunnel service. Independently verify
   its process ancestry is tunnel -> wrapper -> pinned original connect, local
   Events discovery is present, and existing tools/Library aliases still work.
   An unsupported or unready path must not advertise Events.
8. On any failed verification, restore the saved profile **only if** its current
   hash still equals this activation's candidate hash. Restart the same owned
   tunnel service, verify the exact previous child argv and baseline tools, then
   stop/disable only the newly created sender service. If another edit intervened,
   stop and reconcile instead of overwriting it. Preserve the new private journal,
   subscriptions, delivery history and receipts; never restore a stale Bridge DB.

The callback allowlist starts empty unless a previously verified real host is
already evidenced. The first actual host subscription can return the safe reason
`callback_host_not_allowed:<hostname>`. Validate that **actual** hostname, prepare
both process arguments with the same allowlist and fresh readiness binding, then
repeat the guarded quiet-window reload and ask the host to retry the subscription.
Do not guess a callback, signing secret, chat ID or user grant. The actual original
ChatGPT conversation must support Work web or desktop Work+Cloud and event-triggered
work. Refresh/rescan and host subscription are platform actions, not a fabricated
MCP tool. Observe the later assistant turn independently and measure latency only
after a real subscribed webhook; an open tool wait, long poll, inbox ACK or a
synthetic callback never satisfies that acceptance.
