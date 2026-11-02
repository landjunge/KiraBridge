# macOS keyboard investigation — 2026-11-02

## Baseline and confirmed defects

The request names RC24. The actual Mac already ran RC25, build7d862e5, with the
same affected keyboard implementation. Hardware: iMac17,1, Intel, macOS15.7.4,
built-in Retina5K display. Private device serials and hardware UUIDs are not part
of this report.

A dedicated, uniquely named Apple Notes test note reproduced `keyboard_unsupported`
through the real authenticated ChatGPT Apps connector. The task conservatively
ended unknown at the commit boundary. An independent read of that exact owned
note confirmed the requested Unicode text had not been inserted. The original
task was not replayed. No existing user note was changed.

Notes can explicitly report unsupported AXEnabled/AXSubrole, and an empty writable
body can report no AXValue. The former field contract rejected these combinations.
The repair recognizes only the exact system Notes body, proven writable/count/
selection state and documented absence, while preserving identity, secure-field,
layout, focus and no-replay checks.

All former key events were posted directly to a PID. That path cannot substitute
for the HID/system-defined path needed by macOS global shortcuts and consumer
keys. New system-scope operations separate those intents. Current user shortcut
preferences and the public Carbon registry are observed; missing or disabled
shortcuts are not invented. Explicit Fn is never erased to match another action.

## Implementation and evidence boundaries

- App keys:54 named keys, explicit modifiers including Fn,1–20 repetitions with
  fresh guards, exact Notes text staging/verification and bounded target identities.
- Five documented Fn/Shift-Fn text-navigation translations; combinations with
  Control/Option/Command are retained rather than guessed.
- System keys: current registered shortcuts,19 NX special-key signal types,
  audio/display observations and a public Space-change notification counter.
- Caps Lock: public IOHID state setter with exact readback and a distinct receipt;
  zero event posts are reported honestly.
- Permission state is bound to the worker PID/generation. Accessibility and event
  posting are required; input monitoring, screen recording and AppleEvents
  automation are not falsely made prerequisites for ordinary native key sending.
- A native event-post receipt is not an acknowledgement of a media, display or
  application effect. Device effects and practical receiver evidence are separate.
- Power/Touch ID/secure-attention hardware and a stand-alone Globe/Fn hardware
  identity are not fabricated. Hardware-dependent and untested effects are named.

## Local verification before practical tests

Team checks cover generic focus, exact Notes metadata, missing attributes,
layout-dependent logical keys, Fn semantics, repetitions and partial-failure
uncertainty. System-key construction/registry/state-transaction tests do not post
real OS events. Browser cases cover system actions without a profile/app choice,
Fn/keypad/repeats, state-readback receipts, lost responses without resend, and
permission guidance surviving normal status refresh.

An integration run passed254cases;3 fixture expectations lacked newly explicit
scope/repeat defaults and were corrected. Only those failed cases were repeated.
The new System Settings URL allowlist and special-key delta passed54 native
cases together. All tests and builds are local Intel; GitHub Actions is skipped.

## Primary references

- [Apple CGEvent and its PID/system posting routes](https://developer.apple.com/documentation/coregraphics/cgevent)
- [HID event insertion point](https://developer.apple.com/documentation/coregraphics/cgeventtaplocation/cghideventtap)
- [Apple keyboard shortcuts, including Fn editing/navigation](https://support.apple.com/en-us/102650)
- Apple SDK: IOKit/hidsystem/ev_keymap.h and IOLLEvent.h define special-key event
  types and explicitly do not promise that every type exists on every device.
- Apple SDK: IOHIDLib.h and IOHIDParameter.h define modifier lock read/write;
  CarbonEvents.h documents CopySymbolicHotKeys without semantic action names.

Practical test matrix, exact candidate/release pins, preserved state, installation
and remaining limitations follow after actual receiver/hardware tests.
