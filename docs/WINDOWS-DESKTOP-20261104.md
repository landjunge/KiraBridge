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

Windows may deny foreground activation; no input-queue attachment or
foreground-lock workaround is used. Other window actions retain their full immediate identity/readback checks
and distinguish `requested` from `observed` effects. A changed or reused target
after those actions remains `unknown`, without automatic retry.

Both managers share the existing desktop transaction and deadline. Permissions,
active input desktop and exact target identity are checked again before effects.
Window mutation requires window-list permission; a shortcut requires keyboard
inspection permission. Windows cannot make HWND mutation atomic with process
generation checks, so a final destruction/reuse race remains.

## Verification and installation

**All six V5 native phases passed** for **0.8.0rc31.dev3** in the existing Windows 11
AMD64 guest, using Python 3.14.10. Source:
`271605a5049255b007ea903a28bdfe40c51cf7f7`; run:
`ddb5056cc7ef4ea595714e5ffcc348f4`. The
[sanitized native receipts](evidence/windows-desktop-native-acceptance-20261104.json)
are the exact `native-acceptance.json` included in the locally built Dev Kit,
SHA256 `d4417de8e29c9efce66073284b0b72f8c08eceead8904977a5a2bfe37be9002f`.
All phases bind to manifest
`ad93d6dd980a0dbc64e6b1ca2598d73d19f6c9b4523291085e025ace0f091d00`;
no earlier phase was reused as current acceptance. The 173-module runtime digest
is `309064bdca787d12141ff8e091ab0be67823fe780c71f169b60576cca14495c9`;
wheel SHA256 is
`43374ac3a535de967a966bd0a852c4996e634f0bf631130ca55326d987876f41`.

| Native phase | Observed result |
| --- | --- |
| Core | Four native Windows checks passed: private files, process lock, ACL refusal and SQLite/event journal; no skips. |
| Keyboard | Nine receiver cases passed: real eight-key `Stern am`, US/German layouts, AltGr, explicit Unicode, Return, Backspace, extended arrow and F2. |
| MCP | Authenticated local HTTP delivered eight keys/18 events exactly. Resubmitting the same completed task added zero events and zero task transitions; stale-target and revoked-permission controls added zero input. |
| Preview | HTTP 401 without credentials; exactly eight capabilities and five Windows operations; zero tasks/keys. Its owned test child was stopped and independently confirmed absent. This is separate from a retained installation. |
| Shortcuts | Ctrl+A, Ctrl+S, Shift+Tab and Alt+F2 produced exactly four complete native calls/16 events, with modifier order, queue state and real Alt WM_SYSKEY evidence. The injected held-modifier guard control added zero input. |
| Windows | Seven positive actions passed independent OS readback: move/resize, maximize, restore from maximized, minimize, restore from minimized, activate from owned auxiliary, and close. Stale/forbidden controls had zero effect hooks and preserved the main window. |

The close result deliberately remained `outcome:"requested"`/`observed:false`.
The receiver separately recorded exactly **one WM_CLOSE for the main HWND** and
confirmed its absence. A different auxiliary HWND received its own setup close;
the whole fixture therefore contains two WM_CLOSE records, not one. All owned
fixture windows were independently absent at cleanup; the window phase received
zero keyboard events. No global Windows-key shortcut was executed in the guest;
its native encoder has injected unit coverage only.

Each keyboard/MCP/shortcut/window fixture used one separately recorded, guarded
readiness click: three mouse records in one native call, with durable uncertainty
before dispatch and later foreground confirmation. These are fixture setup,
not tested keyboard input or evidence that production window activation bypasses
Windows policy. No clipboard was used. Partial/uncertain setup stops the test
before keys, without retry or guessed modifier/button release.

### Local timings and their limits

| Path in this guest run | Samples | Result |
| --- | --- | --- |
| Direct native `Stern am` | One eight-key sequence | 169.846 ms; eight native calls, 18 receiver events. |
| Four distinct shortcuts, including receiver confirmation | Four calls | Total 383.467 ms; P50 median 98.174 ms; P95 nearest-rank 127.085 ms. |
| Local authenticated `bridge_health` | Five reads, no omitted warm-up | P50 21.511 ms; P95 85.345 ms. |
| Window task completion through local MCP | Seven distinct positive actions | Total 1080.942 ms; P50 142.486 ms; P95 268.858 ms. Independent OS observation follows these task timings. |

The small-sample P95 values are sample maxima, not reliable tail forecasts.
Shortcut P50 uses the median of four samples; its P95 uses nearest rank.
The physical MCP sequence was executed once, so no sequence P50/P95 is reported.
The complete MCP phase took 2390.405 ms for 11 tool attempts, including read/negative
controls. These are guest-local measurements with receipt/confirmation overhead;
they measure neither ChatGPT/Voice nor connector/proxy/cloud round trips.

### Earlier failures and focused checks

V1/V2 keyboard startup timed out before input: each receipt records
`input_attempted:false`, zero hooks and no cases. V3/V4 passed five native phases
and six positive window actions plus stale/forbidden controls; their last close
tasks remained `unknown`. The original V4 task database proved native WM_CLOSE
acceptance followed by `windows_target_changed`, without uniquely identifying
the exact readback substep. Its
[original diagnostic evidence](evidence/windows-close-original-diagnostic-20261104.json)
remains unchanged. Those attempts are never relabeled as passes. V5 uses a new
owned receiver and the request-only contract, with the independent close gate
still required.

Focused local rounds included 95 keyboard unit checks, 52 Dev-Kit guards, 47 fixture
setup checks and the final 128 window-contract/acceptance checks. These are
separate targeted rounds, not one combined suite count or native acceptance.
Independent read-only reviews covered the fixture mouse ABI/guards, close-race
diagnostics and final request-only close contract before the fresh guest run.

### Published release and installed runtime

[Windows dev3 release](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev3)
contains five assets. Fresh authenticated downloads matched GitHub digests and
local bytes for all five. The Dev-Kit ZIP has **64,297,668 bytes**, SHA256
`e35710e4fa9ad903a2412e9885897cb1dbf1ebb0f77fe8b18570b841afd757a3`.
Its three Windows documents are included. The
[compact installation evidence](evidence/windows-desktop-installed-20261104.json)
records the published fingerprints and hashes of the separate original reports;
private report contents, per-file hash maps and screenshots remain local.

The installed **dev3** instance was verified after both verifier and redirector
exit at **2026-11-04 06:23:50.3781590 UTC**: PID **7516**, creation FILETIME
`134382470213253467`, instance `232ff387192b4b7089e8f64f6cd23e0f`, started
`2026-11-04T06:23:46.486780Z`. It owned the sole **127.0.0.1:8766** listener.
All 173 installed Python-module bytes matched the published wheel/source digest;
authentication rejected a request without credentials with HTTP 401, the runtime
exposed exactly eight capabilities/five Windows operations, and had zero tasks.
Root also inspected a fresh private guest image of the new console; only its
fingerprint is published. These facts apply to the recorded observations and
do not promise future process liveness.

`windows_guest_runner.ps1 -WorkName KiraBridgeDesktopDev3 -ReusePreparedPython`
uses a separate work directory and checks the installed dependency versions
without pip writes to the prepared dev2 interpreter. All phases import the
hash-verified candidate source with bytecode writes disabled. Old attempt IDs
and source directories are preserved.

The retained dev3 installation uses a separate venv, existing pinned
dependency packages, a new private state directory `KiraBridgePreviewDev3` and
guest loopback port **8766**. The existing dev2 package/state/port 8765 are kept
for rollback. A real before/after comparison found all 171 old base-module hashes,
the old credential bytes and old desktop-launcher bytes identical. The same
dev2 PID 11720/creation FILETIME `134382301975786026` still owned 127.0.0.1:8765
at the parent readback. Earlier unknown task records remain isolated and were
never replayed.

The new desktop starter **KiraBridge Windows Desktop Test.cmd** prefers the dev3
venv and checks its installed version; SHA256
`47eba8e2e586c0c365f05d3b5b7968e4919b6800b988435a31aace5df7428c2f`.
The installer/verifier submitted no keyboard or window tasks and used no
clipboard, credential rotation, process stop, global OS-right change, Windows
service or autostart. Setup commands were entered separately through UTM in the
existing owned PowerShell window.
The owned console was left running at the recorded readback. macOS/main and
the other ongoing session were outside this Windows deployment. All ten owned
host HTTP staging/report helpers and the temporary OCR watcher were independently
confirmed absent at final cleanup; UTM still reported the retained VM as started.
Neither Windows preview nor UTM was signalled during that cleanup.

External ChatGPT/Voice, full GUI automation, file/process/terminal operations,
Windows 10 and native global Windows-key shortcuts remain outside this acceptance.
The earlier local timings do not measure a cloud round trip.

## Primary references

- [SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)
- [SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos)
- [Normal window closing](https://learn.microsoft.com/en-us/windows/win32/learnwin32/closing-the-window)
- [Previous dev2 evidence](WINDOWS-DEVELOPMENT-20261103.md)
