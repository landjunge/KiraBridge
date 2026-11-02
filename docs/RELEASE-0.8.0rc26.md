# KiraBridge 0.8.0rc26 — macOS keyboard

The native keyboard path supports Apple Notes' actual accessibility metadata,
54 named keys, F1–F20, numeric keypad, Fn text-navigation semantics and bounded
key repetitions. A separate explicit system path sends configured macOS shortcuts
and special-key signals through the HID event stream. Caps Lock uses a typed,
verified modifier-state transaction instead of invented event-post receipts.

The native inventory distinguishes configured shortcuts, event routes, observed
audio/display/Space state and hardware-dependent effects. Permission guidance
belongs to the actual executing worker and offers fixed System Settings links.
No OS grants or user shortcuts are silently changed. Existing profiles and the
RC25 boot-recovery/transactional installer remain included.

Local Intel checks and practical results are recorded in
[the keyboard investigation report](MACOS-KEYBOARD-COMPLETE-20261102.md). This
candidate's live matrix is completed before the final package is published.
The installer requires Intel macOS 15/26, Python 3.11 and uv 0.11.6 and is ad-hoc
signed. Apple notarization is not claimed.
