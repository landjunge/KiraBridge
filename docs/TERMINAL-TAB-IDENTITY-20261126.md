# Terminal tab identity, orphaned agents, stale bindings (2026-11-26)

## Rule
A Terminal.app tab is identified by **the TTY of that tab and the process identity on it**
(`pane_id = terminal:<window>:<tty>`, shell root PID, agent PID). The window title is **not**
identity. The profile can show TTY, active process and arguments, so the title changes while
an agent runs, and a window title shows the *selected* tab, not necessarily the target tab.

## Changes
- `platform_adapters/macos/terminal_window.py`: the physical window proof matches the on-screen
  window by owner process, application start, layer, on-screen state and geometry. The title
  only separates two windows with identical geometry.
- `platform_adapters/terminal_app.py`: `native_window_surface_guard` no longer compares
  `targetWindow.name()` with a stored title; window id, tab TTY and geometry still must match.
  Selecting the tab still checks `selectedTab().tty()`.
- `terminal_hygiene.py` and `kirabridge terminals [--apply]` (dry run by default):
  - **Orphaned agent** = known agent on a `ttysN` that no open tab owns **and** parent PID 1
    (shell/login gone). Agents without a TTY are background agents by design and stay.
    Processes in tmux/ssh trees (live parent) and this session with its ancestors stay.
  - Termination re-reads PID, start time, TTY and parent right before the signal, sends
    SIGTERM only, waits and verifies absence. No SIGKILL.
  - **Stale binding** = recorded tab TTY not open, or recorded shell/agent PID not running.
    `--apply` backs up `config.toml` and `visible-binding-refresh.json`, removes the
    `[visible_handoffs.bindings.<name>]` blocks, reloads the config and restores the backup
    if it is invalid.
  - Fails closed: unreadable tab list (`tabs_unavailable`) or partly parsed `ps` output
    (it is locale dependent, so `LC_ALL=C`) change nothing.

## Evidence (2026-11-26, operator Mac)
Dry run: tabs `ttys000` (free shell) and `ttys002` (claude), no orphaned agents, background
agents `codex`, `opencode` kept, stale bindings `codex`, `grok`, `claude` (PIDs gone). `--apply`
removed them; backup `config.toml.bak.20261126-160932-stale-bindings`.

## Tests
`tests/test_terminal_hygiene.py` (orphan/background/protected selection, identity re-check
before SIGTERM, stale bindings and TOML stripping, fail-closed `ps`, message routing for a
window with two tabs by TTY and PID) and `tests/test_terminal_existing_window_visibility.py`
(renamed window still proven; title only separates identical geometry).

## Open
Message delivery to `claude` needs a new exact assignment after the server restarts with the
cleaned config; verify with a real test message after the next package install.
