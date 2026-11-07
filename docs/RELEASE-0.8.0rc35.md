# KiraBridge 0.8.0rc35

RC35 removes two redundant full Terminal catalogues from each explicit visible
shell command. A freshly selected row is reused only for its immediately
following screen read, within the existing principal/task-scoped observation
context. The screen is still read fresh; session.inspect is authorized again
and ambiguous identities are refused explicitly. Final selection, process
identity, busy/focus/screen checks and the native send guard remain fresh.

The preceding RC34 live acceptance exposed a 15.342-second command, including
11.710 seconds before running. Its source path made five full catalogues before
input and one for output. RC35 reduces these to three and one; this is a proven
request-count reduction, not a claim that all end-to-end latency is solved.

All RC34 footer, tab-reflow identity, restart/no-replay and physical-key sequence
corrections remain. Native Swift and Windows sources and dependency pins are
unchanged. The specific historical keyboard_unsupported fixture remains
unresolved. Installation uses the regular visible backup/idle/rollback path.
