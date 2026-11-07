# Bounded partial presentation output — 26 October 2026

The built `449d851` macOS presentation probe exposed a real short-write failure:
a 9,666-byte frame (3,120 Braille cells) was cancelled after only part of the
frame reached the owned terminal. This change keeps the existing renderer and
geometry; it repairs the caller's output acknowledgement contract.

## Caller contract

`SetupUI` retains at most one UTF-8 frame, capped at 128 KiB (or the renderer's
smaller byte budget). `graphic_stream.write_bytes(bytes)` returns the exact
accepted byte count; EAGAIN accepts zero bytes. Each `tick()` makes at most one
write attempt. A partial frame blocks controller polling, replacement frames and
new cursor-up commands. Frame-area bookkeeping changes only after complete
acknowledgement. No sleeping, threads, timers, locks or waits are introduced.

`pending_output` means remaining frame bytes only. After `finish()`, callers must
also check `finalization_pending`: draining an old frame does not yet confirm the
final static frame. Decorative completion must never extend a real operation's
deadline. A caller may cancel decoration instead.

Before real child output, errors, prompts or status text, cancel decoration.
`output_prefix` is opaque cleanup text, possibly including CAN to abort split
UTF-8/CSI, an SGR reset, and a bounded forward-only move out of the already owned
frame. It never rewinds. Transmit the prefix completely before real bytes and call
`acknowledge_output_prefix()` only after full success. A failed/EAGAIN cleanup
must remain pending; never replay the discarded frame or send real text after an
incomplete cleanup. The normal `say`/`ask` paths implement the same ordering.
Unknown viewport changes disable redraw. Plain ASCII cancellation needs only a
newline, without extra ANSI. Buffered text-stream flush failures remain uncertain
and retain cleanup even when `write()` returned the entire character count.

## Targeted evidence

Source base: `449d85175309e2fce17e536b9036036073695757`.
Interpreter: existing `current-release/.venv/bin/python` with `PYTHONPATH` pinned
to this worktree's `src`; no other checkout's implementation is imported.

The new private nonblocking `os.pipe` tests reproduce the original cancellation
before the change, then cover exact UTF-8 byte continuation, actual EAGAIN, one
write per tick, no premature polling/rewind, partial CSI cancellation, persistent
cleanup before `FATAL`, ASCII/resize fallback, delayed finalization, buffered flush
failure and prompt/error/status priority. Existing directly affected presentation
expectations were checked separately. Ruff and `git diff --check` passed.

Detailed local logs are in ignored `dist/braille-partial-write-20261026/`.
These are private-pipe and isolated text-stream tests, not a claim of successful
visible macOS package acceptance. The parent integration must supply and verify
the raw-byte writer and deadline-aware child-output prefix handshake, then repeat
the one owned-window built-package acceptance. No production installation,
Terminal window, agent session, service or queue was touched by these tests.

## Actual native reproduction and integrated follow-up

The built449d851 package reproduced this defect in an owned native Terminal:
viewport131x35, requested9666bytes/3120Braille cells, partial write reported as
BlockingIOError, only311Braille cells independently read back. No installation
was performed. The one owned test window60091 was closed and its absence
independently confirmed; other windows were untouched.

[Native reproduction](evidence/braille-partial-write-repro-20261026.json). Root
transport now exposes exact nonblocking byte acknowledgements, forwards opaque
abort/reset prefixes before real child text under the original deadline, and
acknowledges only full success. Fast completion never starts a late frame merely
to discard it. The normal short KiraBridge heading remains visible.

One directly affected combined partial-IO/presenter/package batch passed
**50 tests in3.79s**, Ruff/format passed and independent review found no remaining
concrete blocker. Earlier449 package and CI results remain tied to449. The new
source still needs its own build/targeted actual presentation acceptance; no
production update, merge, hostedMac/ARM pass or publication is claimed here.
