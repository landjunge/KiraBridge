# RC35 · remove duplicate visible-terminal discovery

The successful RC34 postrestart acceptance task
`footer_rc34_postrestart_input_20261104` exposed a further local bottleneck:
15.342 seconds from creation to completion, including 11.710 seconds from
acceptance to running. The command completed correctly in the owned visible
window; correctness did not establish acceptable latency.

Code tracing found five complete Terminal catalogues before input and another
for output. Two were immediate duplicate resolutions performed by
`SessionManager.read()` after its caller had just selected that same row.

RC35 uses the existing principal/task-scoped observation context only around
those two direct screen reads. It explicitly checks current session.inspect
authorization and ambiguous identities before entering the scope. Both screens
are still read freshly. Final selection under the input lock, process birth
identity, native PID/TTY/busy/focus/screen checks and script TTY verification
remain unchanged. This is neither a cross-request target cache nor permission
to reuse a previous chat's stale process identity.

The new integration uses actual SessionManager.catalog/selected/read and a
durable SQLite task, mocking only OS transport. It verifies four catalogues
overall and three before dispatch, two fresh pre-dispatch screens, exactly one
dispatch and no additional calls when the same task is resubmitted. Ambiguity,
revoked inspection rights and a final busy transition send no input. Six focused
cases passed, including existing scope/stale-target checks. The complete
related `tests/test_discovery_visible.py` file passed21cases incrementally. Four
stale fixtures first failed identically against an isolated RC34 source archive;
their existing open/progress/inline-result contracts were corrected without
changing runtime behavior or weakening assertions, and only those four were
rerun successfully. These groups are not summed because one existing case overlaps.

All RC34 footer, host-identity/reflow, keyboard-sequence and restart tests and
their scopes remain documented in [the preceding delivery report](CODEX-FOOTER-20261104.md).
The unchanged native Swift sources, installer and dependencies reuse their
existing evidence; the new exact package still needs its source pin, signature,
smoke, publication/download and actual installation checks.

The request-count reduction is deterministic. A single native before/after
command is not a general benchmark; cloud/host roundtrips and the remaining
fresh target proofs still contribute to end-to-end time. Historical unknown
tasks are never replayed. Only the owned install/test window may receive input.
