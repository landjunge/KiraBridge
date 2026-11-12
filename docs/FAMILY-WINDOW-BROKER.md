# Native family window broker v1 (macOS)

The existing installed `kirabridge` CLI accepts:

```text
kirabridge --principal local family switch TARGET --source-pid OWN_NATIVE_PID
kirabridge --principal local family inspect TARGET --source-pid NATIVE_PID
kirabridge --principal local family registration
```

`--source-start SECONDS.SIX_DECIMALS` is optional. The broker derives the kernel
start identity freshly when absent. Only the native host supplies its own PID;
the browser supplies one catalog ID, never a PID, path, URL, script or argv.
There is no general window-manager endpoint or new daemon. Other operating
systems return `family_unsupported`; they do not fall back to shell automation.

## Registration and policy boundary

`~/.config/kirabridge/family-windows.json` is an operator-owned **0600** regular
file, not a symlink. The `registration` command only prints a disabled template;
it writes nothing and grants nothing. The integration operator can review and
atomically install that template with `enabled:true` only after checking the
existing local policy. This worker does not install a production registration.

The exact v1 schema is:

```json
{
  "schema": "kirabridge.family-windows.v1",
  "enabled": false,
  "policy": {
    "path": "/absolute/operator/config.toml",
    "sha256": "CURRENT_POLICY_SHA256",
    "principal": "local",
    "operations": ["windows.focus", "accessibility.set", "apps.launch"]
  },
  "apps": {
    "kirabridge": {"path": "/Users/OWNER/Applications/KiraBridge.app", "bundle_id": "de.netzwerkpunkt.kirabridge"},
    "threaddesk": {"path": "/Users/OWNER/Applications/ThreadDesk.app", "bundle_id": "de.netzwerkpunkt.threaddesk.tauri"},
    "4allpass": {"path": "/Applications/4AllPass.app", "bundle_id": "de.netzwerkpunkt.fourallpass"},
    "tollgate": {"path": "/Applications/TollGate.app", "bundle_id": "de.netzwerkpunkt.tollgate"},
    "agent-authority": {"path": "/Applications/Agent Authority.app", "bundle_id": "de.agentauthority.observer"}
  }
}
```

The template uses the real home path and policy hash. IDs/bundle IDs are fixed;
installation paths can be changed only in this trusted operator file. All five
must have distinct canonical paths. This file is a narrow native-host admission,
not permission to broaden the principal. Python checks the existing policy's
three automatic grants without constructing Bridge, Store or SQLite. Native code
requires the same approved policy bytes and registration before **each** effect.
Policy/registry changes invalidate admission rather than retaining stale grants.
No OS permission request or chmod of an existing policy/app is performed.

Registration also preserves `apps.launch`'s existing `PathScope.directory` gate:
the registered target must be inside the principal's **roots**, with the existing
`state_exclusions` applied. Empty/unrelated roots, read-roots alone, excluded
state directories and symlink traversal do not authorize Launch or Reopen, even
with `permission_level="full"` and all three automatic capability grants. Neither
registration nor this broker changes those grants or their existing exceptions.

Python checks the target at switch admission and again before native dispatch.
Immediately before each native Launch/Reopen, the helper directly executes the
fixed installed `~/.local/bin/kirabridge --config POLICY --principal local family
path-check TARGET`, without a shell. This internal read-only subcommand reuses the
same PathScope implementation without Bridge/Store/SQLite. A bounded five-second
check returns the policy hash, registration hash, exact target/path and opened
directory's device/inode. Native code binds all fields to its frozen admission,
rechecks caller/roster/policy after the await and checks canonical directory
identity before opening the URL. Missing/outdated CLI, denial or changed evidence
admits no URL-open effect. This adds no registration-schema field or host-ABI
requirement, and prints no configuration contents.

Only the pinned native payload in the installed release manifest is used, with
its source commit and binary SHA-256 checked by existing NativeSystemTransport.
A source checkout, arbitrary global UI app or generic script is not a production
fallback. The native bundle must declare `KiraBridgeFamilyWindowProtocol = 1`.
It enters existing `--system-operation` mode before creating the desktop UI.

## Identity, geometry and ordering

The actual kernel UID/real UID/saved UID, PID/start, exact registered bundle path,
main executable and installation revision are captured. Source must be a regular
GUI application, be frontmost, and be an ancestor of the CLI/native helper call.
A supplied foreign PID, another ThreadDesk installation, an accessory native
helper or a Terminal/agent window cannot become the source. Before every native
write the source caller chain, application roster, policy and selected AX window
are freshly rechecked. Final receipts retain before/after identity evidence.

Only one standard main window per registered application is admitted. Multiple
instances/windows, sheets/modal dialogs and fullscreen fail closed. No title
heuristic chooses between documents. An existing registered instance is reused;
a missing target is launched once by its exact application URL with
`createsNewApplicationInstance=false`. Waits only observe; unknown launch outcomes
never issue another launch. If the existing instance has no accessible main
window, one exact-URL Reopen is admitted; its callback must retain the original
PID/start/path and the one retained WindowServer main-window ID. No retained
handle, ambiguous handles or a newly created window remain UNKNOWN; the broker
does not adopt them. Host Reopen must show its owned main without rebuilding or
reloading its state. The broker then requires one unambiguous AX main window. A replaced process or
extra window is UNKNOWN, never silently adopted or closed. Already invisible
registered apps may omit their AX window; the public on-screen inventory must
prove absence before they are skipped. A new visible/ambiguous window is never
silently adopted. The fixture covers two consecutive switches with AX windows
absent after hiding and unchanged process identities.

Bounds are the actual AX outer window rectangle in logical desktop points.
NSScreen visibleFrame is converted from AppKit bottom-left coordinates to AX
coordinates. Clamping uses the intersecting display's visible work area, including
negative monitor coordinates. Backing pixels are not mixed with logical points
on Retina displays. Size/position changes are read back, including minimum-size
constraints; a mismatch is not reported as success.

Order: durable intent → exact target geometry → show/raise/focus and readback →
hide other registered apps, source last → final one-visible-window/identity
readback → durable receipt. No Close, Quit, webview reload, backend/collector stop,
secret access, unlock, or agent/terminal input is part of switching. 4AllPass's
normal lock policy remains effective. Failures attempt to restore the original
source only if its exact identity and the policy still match. OS-level effects
cannot be made atomic across apps; an unverified partial effect is UNKNOWN.

## Serialization and crash recovery

`~/.local/state/kirabridge/family-windows/switch.lock` is a user-private,
nonblocking cross-process flock. A second request returns `family_busy`; no queue
or delayed click replay is created. `last-operation.json` is atomically replaced
and file/directory-fsynced **before** effects. A prepared/unknown operation after
interruption blocks subsequent switches with `family_previous_unknown`.

Do not remove a pending record or retry merely because the CLI exited. The
integration operator must first inspect the registered process/window identities,
visibility and bounds, resolve the original outcome and preserve its evidence.
`inspect` is read-only and does not authorize a later switch. There is no automatic
UNKNOWN reset. Only a confirmed completed or pre-effect-failed record admits a
new operation. No task database is opened for this state.

## Exact external JSON ABI

Exit zero requires top-level JSON:

```json
{"success":true,"active_product":"threaddesk","actual_outer_bounds":{"x":10,"y":24,"width":1358,"height":664},"visible_family_windows":1}
```

Native identity, operation ID and evidence may be included, never secrets. Error
exit is nonzero and has `success:false`, `error:{code,message}` and
`execution_outcome_unknown:boolean`. Exit 3 denotes UNKNOWN; exit 2 a known refusal.
The wrapper unwraps only the authenticated native transport envelope. Text, exit
zero alone, a task wrapper, wrong target, invalid geometry or multiple visible
windows are insufficient. `inspect` reports `effect:none` and no window effects.

## Build and bounded acceptance

`scripts/build_desktop_app.py` includes `FamilyWindowBroker.swift` and
`FamilyWindowNative.swift`, defines `FAMILY_WINDOW_BROKER`, fingerprints both and
sets the protocol metadata. It preserves existing app destinations. Build only
from a clean committed source into a new candidate path; never overwrite an
installed app from a worker. The existing generic native fixtures compile without
the family feature; its dedicated fixture compiles the real implementation with
that feature and fake window effects plus real temporary-file flock/journal tests.

Run `pytest tests/test_family_windows.py tests/test_desktop_builder.py` for the
bounded CLI/ABI/identity/race/geometry/ordering/compiler checks. Existing transport
and policy tests remain relevant. No whole-suite repetitions or hosted private
macOS builds are needed here. Independent review, required CI and real installed
five-app acceptance remain integration gates. Compilation/fixtures are not a live
window-switch or installation claim.
