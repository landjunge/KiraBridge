# Interactive Windows keyboard preview

This entrypoint runs an owned local MCP service in an unlocked Windows user
session. It does not install a service, alter UAC/OS permissions, configure an
external ChatGPT connector, send keys at startup or expose file/process/terminal
operations. The macOS installation is independent.

With the updated package/source available to the installed guest Python:

```powershell
python -m kirabridge.windows_preview --transport http --port 8765
```

The isolated guest bootstrap does not change PATH. Its current private Python is
`$env:LOCALAPPDATA\KiraBridgeDev\Python314\python.exe`; use that full path when
`python` is unavailable. The updated preview module must be in that interpreter's
installed package or verified `PYTHONPATH` source tree.

Default state: `%LOCALAPPDATA%\KiraBridgePreview`. Override with
`--state-dir C:\KiraBridgePreview` if needed. State remains after shutdown so old
unknown tasks can be reconciled using their original IDs. Existing credentials
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
`task.cancel`, `windows.keyboard.inspect` and `windows.keyboard.sequence`. There
is no full-permission expansion, executable/root grant or user-supplied token
in an operation argument.

Read the current Windows target with `windows_keyboard_inspect`. Submit a
sequence using the exact target token returned by inspection. The native backend
rechecks desktop/window/process identity and every authorization; inserted events
still do not prove application processing. Keep uncertain outcomes explicit and
never resend under a new ID. Stop the owned preview console with Ctrl+C.

On macOS, `--help` works, while actual execution fails before state or credential
writes. Focused tests cover policy, credential persistence/refusal, protocol-only
stdout, loopback binding and cleanup. Native Windows transport/startup acceptance
must be recorded by the guest smoke; unit tests are not that acceptance.
