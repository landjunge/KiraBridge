# KiraBridge 0.8.0rc37

Local Intel repair candidate for the reproduced Terminal tab-switch refusal.
RC36 compared an idle shell buffer captured before activation with the buffer
after activation. A tab bar/row-count change reflowed that buffer and caused
`visible_input_changed` before the command ran.

The regular confirmed shell path now checks the initial empty input and exact
process identity, acquires the requested focus once, and accepts a fresh empty
buffer after that transition. Dispatch then checks focus, process identity,
busy state and the exact raw buffer without selecting or activating again.
User input, changed focus/TTY/process birth and an occupied target still refuse.
The stronger full process/CWD and physical-isolation callback remain in place.

The change includes persistent generated-JavaScript regression cases and a
bounded native Intel acceptance matrix. Simulation, actual runtime and package
results are recorded separately in `TERMINAL-RECOVERY-20261104.md`. Existing
unknown tasks are preserved and never replayed. No Windows, native Swift,
permissions, dependency pin or cloud-build changes are included.

This local candidate is not a published GitHub release.
