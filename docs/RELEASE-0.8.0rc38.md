# KiraBridge 0.8.0rc38 · local Intel follow-up

KB-CHAT-REWORK-20261104-C6D1 addresses two failures from Kira's real browserchat
acceptance on RC37. A wrapped Codex draft now uses the same complete footer-group
validation as the empty/single-line paths. The exact model-plus-warning group is
supported; warning rows alone or extra/unknown dialogs remain unsupported.
Cursor, process/TTY/birth, active-turn and Return dispatch guards are unchanged.

An idle shell whose input cannot be confirmed empty now reports
`visible_input_unknown`, separately from occupied process state. Exact whitespace
recognition is unchanged. A safe existing shell can still be selected alongside
an ambiguous one; if none is confirmed, no replacement window is created merely
because existing input is unknown. No whitespace is stripped or submitted.

This is a local Intel candidate. No public release or cloud/cross-platform build.
Local acceptance is distinct from Kira's pending real browserchat acceptance of
the existing unsubmitted test draft. See `CHAT-REWORK-C6D1-20261104.md`.
