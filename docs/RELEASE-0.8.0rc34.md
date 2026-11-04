# KiraBridge 0.8.0rc34

This targeted Intel macOS update addresses Codex 0.166.0 changing its final
shortcut/warning row after literal paste. The exact observed transition from
shortcut plus warning to the same standalone warning is verified without
discarding arbitrary footer rows, changing payload checks, or relaxing target
identity guards. Cursor-bound Return recognizes the supported collapsed-draft
footer. Unknown dialogs, active turns and changed input remain blocked.

The original failed and unknown tasks are preserved; installation never replays
them. The correction is independent of the previously observed generic native
`keyboard_unsupported` failure, which remains unresolved. It does not claim
Codex thread continuity, every multiline renderer shape or a general 0.9.0
platform acceptance. Windows code and dependencies are unchanged; no new
Windows package or VM installation is part of this update.

Source tests, independent review, package fingerprints and the actual installed
source will be recorded separately in the dated footer-correction report. A
release note or a passing parser test alone is not installation evidence.
