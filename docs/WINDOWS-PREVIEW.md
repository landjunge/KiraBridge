# Interactive Windows desktop preview

The dev3 increment adds explicit keyboard shortcuts and top-level window control.
All six native Windows 11 guest phases passed for source `271605a5049255b007ea903a28bdfe40c51cf7f7`.
[Current contracts, receipts and installation status](WINDOWS-DESKTOP-20261104.md)
separate native acceptance from release/download and retained-installation proof.

This entrypoint runs an owned local MCP service in an unlocked Windows user
session. It does not install a service, alter UAC/OS permissions, configure an
external ChatGPT connector, send keys at startup or expose file/process/terminal
operations. The macOS installation is independent.

[Dev3 is published](https://github.com/landjunge/KiraBridge/releases/tag/windows-v0.8.0rc31.dev3),
fresh downloads matched all five assets, and the separate installed runtime was
independently verified on 127.0.0.1:8766 after verifier exit at
2026-11-04 06:23:50 UTC. [Installation evidence](evidence/windows-desktop-installed-20261104.json)
records its exact identity. This is a timed observation, not a future-liveness
promise. Keep that already running owned console; the command below is for a
later intentional start after confirming its listener is absent.

```powershell
$python = "$env:LOCALAPPDATA\KiraBridgeDesktopDev3\Runtime\Scripts\python.exe"
$state = "$env:LOCALAPPDATA\KiraBridgePreviewDev3"
& $python -I -B -m kirabridge.windows_preview --transport http --state-dir $state --port 8766
```

The isolated guest bootstrap does not change PATH. Dev3 uses a separate venv and
the existing pinned base dependencies. The previous dev2 interpreter/package,
state and port 8765 remain separate rollback resources; do not install over them.

The module's generic default state remains `%LOCALAPPDATA%\KiraBridgePreview`;
the explicit dev3 state above keeps it separate from dev2. State remains after
shutdown so old unknown tasks can be reconciled using their original IDs. Existing credentials
are reused; malformed credentials are rejected and preserved, never rotated.

HTTP binds **127.0.0.1 only**, at `/mcp`, using existing authenticated transport.
There is no remote bind option and no unauthenticated keyboard endpoint. The
startup record goes to stderr and names the private `preview-credentials.json`
file. Its `local` value is the client's bearer token; keep it in local client
secret storage and never paste it into a conversation or log. The token is not
printed by the preview. The credential file uses native Windows owner/DACL and
reparse checks.

For a local stdio MCP client, configure its command as the installed Python and
arguments:

```text
-m kirabridge.windows_preview --transport stdio
```

Stdio stdout is reserved for the MCP protocol. Both transports use exactly one
`local` principal with automatic permission for `bridge.health`, `task.read`,
`task.cancel`, `windows.keyboard.inspect`, `windows.keyboard.sequence`,
`windows.keyboard.shortcut`, `windows.window.list` and `windows.window.control`. There
is no full-permission expansion, executable/root grant or user-supplied token
in an operation argument.

Use `operation_catalog` to discover the Windows schemas. `read_query` can inspect
the current keyboard target or list windows. Use `task_request`/`task_get` for
`windows.keyboard.sequence`, `windows.keyboard.shortcut` and
`windows.window.control`. Submit a sequence or shortcut with its exact freshly
inspected keyboard target; window actions use the separately listed window
target. The native backend rechecks desktop/window/process identity and every
authorization; inserted events
still do not prove application processing. Keep uncertain outcomes explicit and
never resend under a new ID. `close` acknowledges a regular WM_CLOSE request,
not completed application processing; a save dialog may remain. Other window
actions distinguish a request from immediate observation. Stop the owned preview
console with Ctrl+C.

On macOS, `--help` works, while actual execution fails before state or credential
writes. Focused tests cover policy, credential persistence/refusal, protocol-only
stdout, loopback binding and cleanup. The real Windows HTTP startup/stop smoke
passed again for dev3 with exactly eight capabilities/five Windows operations,
zero tasks/keys and independently confirmed child absence. It used CTRL_BREAK
for that exact owned process group (observed child exit code 3); it was not a
retained installation. [Current native results and installation status](WINDOWS-DESKTOP-20261104.md)
keep these facts separate. Native stdio transport and external ChatGPT/Voice
acceptance remain open.
