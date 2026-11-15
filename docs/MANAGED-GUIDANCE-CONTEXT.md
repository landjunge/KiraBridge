# Original guidance in later managed work

Development candidate based on `0b16dda0992d`; independent review and native
acceptance are separate from local tests. No schema or configuration migration.

The registered, post-cutoff managed receiver can consume passive notes in a
bounded guidance turn. Previously it acknowledged those notes, while later work
started a fresh provider session with only its current body. The candidate reads
the completed original notes from the existing store when claiming new `work`.
It wraps them around the unchanged current body as explicit prior context.

Only owner-acknowledged `note` records with `request_reply=false`, completed
guidance evidence, the same authenticated sender/recipient, conversation and
execution directory qualify. UNKNOWNs, holds, other scopes and plain completed
jobs are excluded. Current peer rights are checked. At most eight qualifying
notes from a bounded latest-record scan are considered, in chronological order.
This is context for the current authorized task; it grants no additional work,
tool rights, delegation or access to another native session.

The work claim stores the source IDs, exact UTF-8 body hashes, original run IDs,
directory, cutoff, current message hash and final prompt hash/size in
`message_jobs.evidence.managed_guidance_context`. Authority is explicitly scoped
to the same local store and loaded bridge instance. This reference is not a
globally durable authority ID or cryptographic remote attestation. New claims
after a bridge restart can read the same persisted completed notes; previously
claimed work retains the existing restart/UNKNOWN/no-replay behavior.

The complete envelope is validated before marking the work running. The newest
contiguous set that fits 262144 UTF-8 bytes is selected without truncating any
original body. Evidence reports considered notes omitted by the size budget. If
JSON escaping makes even the current-body envelope too large, the valid current
body is passed exactly and `body_only_budget_omission` records that no prior
context was included. Selection is capped at eight notes from the newest32 rows;
older history is outside this bounded prompt window.

Before the adapter call, the pinned source scope, rights, hashes, holds and final
prompt are revalidated. Changed context fails as `guidance_context_changed`
without silently selecting different notes or executing the bare work instead.
Progress, completion and failure evidence retain the same context proof. The
existing authenticated receiver still owns current-work ACK and reply delivery.

Visible terminal delivery, interim input, ordinary work without qualifying
guidance, source message bodies and the existing task/queue store are preserved.
There is no provider-session resume, second queue, database synchronization,
permanent coordinator or ChatGPT/voice wake capability in this change.

Focused validation: `tests/test_managed_guidance_context.py` covers two successive
work turns, cold store reopen, origin/conversation/directory isolation, late
changes after claim, byte bounds and JSON expansion. Run with the candidate's
`src` on `PYTHONPATH`; native provider turns and controlled rollout still require
their own evidence.
