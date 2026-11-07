# KiraBridge 0.8.0rc34

This targeted Intel macOS update addresses Codex 0.166.0 changing its final
shortcut/warning row after literal paste. The exact observed transition from
shortcut plus warning to the same standalone warning is verified without
discarding arbitrary footer rows, changing payload checks, or relaxing target
identity guards. Cursor-bound Return recognizes the supported collapsed-draft
footer. Unknown dialogs, active turns and changed input remain blocked.

New Terminal tabs may reflow or resize their positively identified host without
being rejected solely because its old geometry changed. The host must retain
its native AX anchor and ordered original tab identities; all unrelated CG
surfaces remain exactly bound. Fresh current geometry and the existing guarded
detach/postchecks still protect other windows and sessions.

Physical keyboard sequences now discover the application once, retaining fresh
native target inspection and authorization for every step. Cached Apps clients
can use the existing action_request route for keyboard.sequence rather than
issuing one cloud call per character. Literal paragraphs remain single text
requests; adaptive steps remain separate. Native failure diagnostics preserve
bounded readiness and window-proof reasons without terminal contents.

The original failed and unknown tasks are preserved; installation never replays
them. The correction is independent of the previously observed generic native
`keyboard_unsupported` failure, which remains unresolved. It does not claim
Codex thread continuity, every multiline renderer shape or a general 0.9.0
platform acceptance. Windows code and dependencies are unchanged; no new
Windows package or VM installation is part of this update.

317 distinct focused tests passed, including persisted-cursor reuse after a
Bridge reopen, changed-agent refusal and legacy-client sequence idempotency.
Independent reviews, package fingerprints and the actual installed
source are recorded separately in the dated footer-correction report. A
release note or a passing parser test alone is not installation evidence.
