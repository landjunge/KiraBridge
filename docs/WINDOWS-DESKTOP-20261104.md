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
unsaved data. It never terminates the application process. After an accepted post
the backend returns `request_accepted:true`, `observed:false`, `outcome:"requested"`,
`observed_state:null` and `application_processing_confirmed:false`. It performs no
further HWND inspection after that post: completion requires independent
observation. A completed close task therefore means the request was accepted,
not that the window closed. Failed/unconfirmed native delivery remains `unknown`
and is never replayed automatically. The catalog/schema state this distinction.

Windows may deny
foreground activation; no input-queue attachment or foreground-lock workaround
is used. Other window actions retain their full immediate identity/readback checks
and distinguish `requested` from `observed` effects. A changed or reused target
after those actions remains `unknown`, without automatic retry.

Both managers share the existing desktop transaction and deadline. Permissions,
active input desktop and exact target identity are checked again before effects.
Window mutation requires window-list permission; a shortcut requires keyboard
inspection permission. Windows cannot make HWND mutation atomic with process
generation checks, so a final destruction/reuse race remains.

## Verification and installation

Version under test: **0.8.0rc31.dev3**, 173 production Python modules. Local unit
and authenticated HTTP integration checks passed for schema, modifier ordering,
native ABI, authorization, stale targets, deadlines and durable no-replay state.
The recorded V4 guest run passed core, keyboard, MCP, preview and shortcuts.
Its window phase verified six positive actions plus stale/forbidden controls;
the final close task remained `unknown`. A read-only query of that original task
proved native WM_CLOSE acceptance followed by a `windows_target_changed` readback
error. The exact readback substep was not uniquely recorded. The
[original diagnostic evidence](evidence/windows-close-original-diagnostic-20261104.json)
preserves this failure; it is not reclassified as a pass or replayed.

The request-only close contract above separates delivery from window teardown.
A fresh six-phase native acceptance and the new installed instance remain pending
at this source snapshot; local tests are not native evidence for the changed code.

The package builder requires six successful phases bound to the same source:
core, keyboard, MCP, preview, shortcuts and windows. The new shortcut fixture
consumes Ctrl+A, Ctrl+S, Shift+Tab and Alt+F2 in its own receiver window. The window
fixture observes its own windows through independent Windows reads after each
single MCP action. Closing must additionally show exactly one received WM_CLOSE
for the owned main window and independent HWND absence after the completed
request; a backend acceptance flag alone never passes that native gate. No global
Windows-key shortcut is exercised in the guest.

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
