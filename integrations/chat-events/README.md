# Optional ChatGPT Events adapter 0.0.2

KiraBridge 0.6.0 keeps this SDK-2 adapter isolated from the MCP-1 backend.
Normal task/action submissions never need an Events subscription. The backend's
input schemas are forwarded unchanged; optional push uses the existing
`completion_target=push:<real verified subscription id>`.

`serve.py --external-sender` is the facade; `--sender-only` is the durable sender.
Both use the same private state and explicitly allowed actual callback hosts.
`prepare.py` only creates private candidates. `check_protocol.py` is a clearly
simulated host for tests; never connect it to the actual ChatGPT App.

The versioned core installer preserves an already configured facade, sender,
tunnel, credentials and App connection. It does not invent a subscription or install
new host credentials. On a new machine this optional integration is a separate
operator setup. Actual original-chat receipt remains unverified.

See [versioned installation and acceptance limits](../../docs/INSTALLATION-0.6.0.md).
