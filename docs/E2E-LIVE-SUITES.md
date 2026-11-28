# Live E2E suites: user + ChatGPT/Kira perspective

Two reusable scripts exercise the **installed, running** bridge end to end —
not an isolated simulation — from the two perspectives that actually use it:

- `scripts/accept_e2e_user_perspective.py` — principal `local` (the human
  operator's own Desktop app / terminal view).
- `scripts/accept_e2e_chatgpt_perspective.py` — principal `chatgpt`
  (ChatGPT/Kira's own MCP connection).

Run either any time after a release, an install repair, or a config change,
against the actually-running bridge on `127.0.0.1:8765`:

```sh
python3 scripts/accept_e2e_user_perspective.py --output docs/evidence/e2e-user-$(date +%Y%m%d%H%M%S)
python3 scripts/accept_e2e_chatgpt_perspective.py --output docs/evidence/e2e-chatgpt-$(date +%Y%m%d%H%M%S)
```

Both print one line per check and a final `{"all_ok": true/false}`; full
per-check JSON lands in `--output`.

## What each suite actually checks

Both check two things together, every run:

1. **Function** — do the core operations this perspective relies on answer
   correctly against the live bridge.
2. **Discoverability ("Auffindbarkeit")** — does `tools/list` expose a tool
   (or a resolvable `operation_catalog` entry) for every capability this
   principal's `config.toml` entry grants, each with a substantive
   (non-thin) description. A capability nobody can find is as broken as one
   that errors.

The ChatGPT/Kira suite additionally runs a full addressed-message round
trip: send (as `chatgpt`) → delivered into the recipient's own mailbox,
confirmed absent from an uninvolved third principal's mailbox (`qwen3`,
normally idle) → receive → acknowledge. This is the direct regression check
for "one mailbox per participant": an addressed message must land in that
recipient's mailbox only, never broadcast.

It runs a second, separate regression check (`recipient_not_rewritten_check`)
for a real past incident: `chatgpt` sends a message explicitly addressed to
`codex` (not the coordinator), and the test asserts the recorded recipient is
still `codex`, the message lands in `codex`'s own mailbox, and never leaks
into the coordinator's (`local`) mailbox. This was broken until 2026-11-27
(commit `41648f9`, "Remove coordinator-only-senders recipient rewrite"):
`team_manager`/`message_manager` silently rewrote any explicit recipient to
"coordinator" for messages sent by `chatgpt`, which once delivered a message
addressed to `codex` to the coordinator instead.

## Storage/data-growth audit

`scripts/accept_storage_growth_audit.py` is a separate, read-only report (not
a pass/fail suite): sizes of every KiraBridge data/config/log/release/backup
directory, `bridge.sqlite3`'s notable table row counts (including unacked
`completion_notices`), a size-sorted breakdown of `~/.config/kirabridge`'s own
subdirectories (surfaces stale per-session repair/rollback snapshots
directly, which is where unexpected growth usually hides), and an observed
(not judged) snapshot of the shared family directory layout. It never
deletes, moves, or compacts anything — any cleanup decision needs the
operator's own word first.

```sh
python3 scripts/accept_storage_growth_audit.py --output docs/evidence/storage-audit-$(date +%Y%m%d%H%M%S)
```

## What they deliberately never do

Neither suite opens a visible window, posts an OS notification, moves the
mouse/keyboard, writes/deletes a file, launches/focuses/quits an app, or
dispatches a message that could wake or steer an active agent session
(`dispatch=false`, `request_reply=false` throughout). Every message either
suite sends is tagged `[E2E-TEST]`, uses a fresh id each run, and is
acknowledged (cleaned up) before the run ends — nothing is left behind in a
real mailbox. That is why both are safe to re-run unattended; anything
interactive (terminal.visible, session.open, notifications.post, keyboard/
mouse, app.launch, clipboard writes) needs a human's own go-ahead per run
and is out of scope here on purpose.

Neither suite changes production config or credentials, and neither was
written against an isolated/simulated bridge — they call the real daemon a
human or ChatGPT/Kira actually uses, with the same credentials those
clients use (`~/.config/kirabridge/credentials.json`, read not written).

## Extending

Add new checks to `DEDICATED_TOOL_CHECKS` (direct tool, no construction
needed) or via `action_request`/`operation_catalog` for capabilities with no
dedicated tool (see `GENERIC_OPERATIONS` in the user-perspective suite).
Keep every addition read-only/passive unless it has its own cleanup path
like the mailbox round trip does.
