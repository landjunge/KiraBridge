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
