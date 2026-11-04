# Windows shortcuts and window control

Development follows the operator-confirmed dev2 keyboard preview. This increment
adds explicit shortcuts and top-level window control; the macOS speed work stays
in its separate session. The existing VM, dev2 installation and receipts are kept.

## Contracts

`windows.keyboard.shortcut` accepts the exact freshly inspected keyboard target,
one `key` (a base character or named key) and a nonempty unique `modifiers` list:
`control`, `alt`, `shift`, `windows`. For example, Ctrl+A uses `key:"a"` and
`modifiers:["control"]`. A complete shortcut is one SendInput call containing
modifier downs, key down/up and reversed modifier ups. It uses no clipboard.
Character case alone does not add Shift. Existing sequences remain available.

`windows.window.list` accepts an optional `limit` from 1 to 64 and returns visible
top-level windows, including minimized windows. Each target has HWND, PID,
process creation FILETIME and thread ID, all as exact canonical decimal strings.
Keyboard targets additionally contain the layout and are a separate contract.

`windows.window.control` accepts that window target and one action: `activate`,
`minimize`, `maximize`, `restore`, `move_resize`, or `close`. Only `move_resize`
accepts/requires `bounds:{x,y,width,height}`. Coordinates use physical screen
pixels; dimensions are 1..32768 and signed-coordinate overflow is rejected.
Moving or resizing does not activate or change the window's stacking order.

Close posts a normal WM_CLOSE request, allowing the application to ask about
unsaved data. It never terminates the application process. Windows may deny
foreground activation; no input-queue attachment or foreground-lock workaround
is used. A result distinguishes `requested` from an immediately `observed`
effect. An unconfirmed native call remains `unknown`, without automatic retry.

Both managers share the existing desktop transaction and deadline. Permissions,
active input desktop and exact target identity are checked again before effects.
Window mutation requires window-list permission; a shortcut requires keyboard
inspection permission. Windows cannot make HWND mutation atomic with process
generation checks, so a final destruction/reuse race remains.

## Verification and installation

Version under test: **0.8.0rc31.dev3**, 173 production Python modules. Local unit
and authenticated HTTP integration checks passed for schema, modifier ordering,
native ABI, authorization, stale targets, deadlines and durable no-replay state.
Native guest acceptance and the new installed instance are still pending at this
source snapshot; implementation or injected tests are not native evidence.

The package builder requires six successful phases bound to the same source:
core, keyboard, MCP, preview, shortcuts and windows. The new shortcut fixture
consumes Ctrl+A, Ctrl+S, Shift+Tab and Alt+F2 in its own receiver window. The window
fixture observes its own windows through independent Windows reads after each
single MCP action. No global Windows-key shortcut is exercised in the guest.

`windows_guest_runner.ps1 -WorkName KiraBridgeDesktopDev3 -ReusePreparedPython`
uses a separate work directory and checks the installed dependency versions
without pip writes to the prepared dev2 interpreter. All phases import the
hash-verified candidate source with bytecode writes disabled. Old attempt IDs
and source directories are preserved.

The intended retained dev3 installation uses a separate venv, existing pinned
dependency packages, a new private state directory `KiraBridgePreviewDev3` and
guest loopback port **8766**. The existing dev2 package/state/port8765 are kept
for rollback. `KiraBridge Windows Desktop Test.cmd` prefers this dev3 venv and
checks the installed version before starting; the old dev2 launcher is retained.

External ChatGPT/Voice, full GUI automation, file/process/terminal operations,
Windows10 and native global Windows-key shortcuts remain outside this acceptance.
The earlier local timings do not measure a cloud round trip.

## Primary references

- [SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)
- [SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos)
- [Normal window closing](https://learn.microsoft.com/en-us/windows/win32/learnwin32/closing-the-window)
- [Previous dev2 evidence](WINDOWS-DEVELOPMENT-20261103.md)
