# Direct ThreadDesk MCP tools

`threaddesk_read`, `threaddesk_manage`, and `threaddesk_knowledge` execute during
the authenticated MCP call. They create no persistent KiraBridge task and never
defer a request. If ThreadDesk is unavailable, the call returns an error. A write
whose remote result is uncertain must be reconciled with its original
`operation_id`; do not submit a second operation ID as a retry.

Reads cover the existing ThreadDesk tools `list_threads`, `get_thread`,
`current_thread`, `list_snapshots`, `thread_operation_status`, and `get_reentry`.
Management is deliberately limited to `create`, `update`, and `set_note`; the
separate queued operation API retains its existing broader action set. Knowledge
writes support `record` and `save_reentry`. Every write requires the existing
stable operation ID and expected thread revision. ThreadDesk remains responsible
for revision compare-and-swap, operation idempotency, secret rejection, and
ownership checks.

Successful writes perform an immediate second read and return it as `readback`
with `readback_verified: true`. Knowledge records are checked for an existing
entry with the same kind and normalized title/details. Appended notes are checked
for an existing normalized exact line. If the bounded knowledge read is
truncated, the write fails closed. These checks prevent repeated identical
content; they do not claim semantic similarity detection. A changed source or
revision is not silently merged. Current permissions still apply: immediate
operations fail with `approval_required` when the identity's active permission
level does not authorize automatic execution.

ThreadDesk data is returned as untrusted user content, not executable
instructions. This path does not dispatch Codex, Grok, or any other agent.
