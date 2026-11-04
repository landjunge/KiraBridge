# Independent Windows merge review

Observed 2026-11-04T07:06:41.027085+00:00, worktree `/Users/landjunge/KiraBridge-worktrees/integration-dev3-rc32-20261104` during root's in-progress merge. Read-only source review; no tests, edits, builds, installation, VM actions or publication performed.

**Result: no concrete integration bug found in the reviewed shared code.** Runtime/source verification remains root's responsibility; this is independent static review, not native acceptance.

## Shared merge review

- `bridge.py`: Windows imports/typed INPUTS, two lazy managers, unsupported-platform validation before persistence, Windows platform status and explicit task routes are retained. RC31 NativeQueries construction and principal-scoped direct task-event existence check are also retained. Windows operation names (`windows.keyboard.*`, `windows.window.*`) cannot collide with macOS `windows.list`/`windows.inspect`. `platform_operation` selects only known macOS descriptors on Darwin and returns None elsewhere, so Windows effects reach their own managers. Each Windows manager performs its own explicit host/permission/target guards.
- Both Windows managers share the same existing DesktopInput object/lock/deadline as macOS managers. MacOS providers remain separate; mere construction does not load Windows DLLs. No source delta from accepted Windows HEAD was found in Windows adapters/managers/preview or native acceptance harnesses.
- `server.py`: Windows 13-second inline result wait and Windows-specific platform catalog mappings coexist with RC31 native.read/tree documentation. Discovery builds metadata, not effects. Authorized Windows operations are omitted on macOS when their unavailable Windows rows fail eligibility. On Windows, the minimal preview principal authorizes only its exact eight capabilities/five Windows operations, so unrelated macOS operations remain excluded by permission. The existing generic non-Darwin catalog behavior is unchanged from Windows source.
- `store.py`: Windows file/DACL/WAL/SHM setup remains intact; `(task_id,seq)` index is retained inside the schema startup transaction for old and fresh databases. No replacement of private Windows setup with POSIX open flags occurred.
- `NativeQueries` remains explicitly attached to MacOSProvider and SystemModules; its immutable six-read allowlist contains no Windows keyboard/window-manager effects. Permission checks precede dispatch. MacOSProvider.require rejects unsupported native capabilities before callback invocation; NativeSystemTransport.snapshot_metadata returns unsupported-platform before any app metadata access on Windows. Consequently RC31 native reads introduce no Windows fallback, OS rights request, effects or retry path.
- The pending integration test change parameterizing native-capability refusal with linux/win32 directly covers the merged platform boundary. Tests were not executed by this reviewer.

## Identity and packaging boundary

Working files consistently declare **0.8.0rc33.dev1** in pyproject.toml, package __init__.py and uv.lock. No conflict-marker text remains in these three files at review. The index was still UU when initially inspected, so root must stage the resolved files before committing.

Two preserved historical dev3 entry points must stay explicit in the integration documentation:

1. `scripts/build_windows_dev_kit.py:23` pins VERSION to `0.8.0rc31.dev3` and validates exact native receipts/wheel requirements. It cannot package the rc33 integration using old dev3 acceptance.
2. `scripts/start_windows_preview.cmd:11` checks installed version equals `0.8.0rc31.dev3`, selects the existing dev3 installation and uses its existing 8766/private-state location. It is a launcher for that retained historical installation, not the integration candidate. Do not use it as rc33 startup/install evidence. A future owned rc33 test should invoke the module with its isolated candidate interpreter and new private state/port, after native-test coordination.

These pins safely preserve the accepted release and running sessions. They are not blockers to source integration, provided the report states them and no merged-source package/installation is claimed. README/de now distinguish rc33 source integration from separately verified macOS RC32 and Windows dev3 releases. The referenced integration report must exist in the final committed tree.

Historical native evidence remains valid for Windows source 271605a (which equals Windows HEAD source bytes), but shared bridge/server/store and version changes invalidate any claim of exact-full-runtime native acceptance for rc33. Fresh native guest acceptance is required before publishing/installing an integrated Windows package. Existing macOS release proof likewise remains tied to RC32's exact source/binary identity.

## Reviewed-file SHA256 snapshot

```json
{
  "src/kirabridge/bridge_core/bridge.py": "d20207365280184c793def14eeb97c02b390053400ddaf1b0046d7373749641f",
  "src/kirabridge/mcp_gateway/server.py": "4fa4965c0cdc6bb2d842b877076bed5c7c34cdd4b51749ab154ae728b662c2b2",
  "src/kirabridge/task_manager/store.py": "e4afbf6849e508dba1cc18720b5063f2c791baf45b571eaee348df9ed46ab285",
  "src/kirabridge/native_queries.py": "f0d994ba0395db70e19fd2d7b7149a3aac60c1fdf2f85800b99c6f9265bb9507",
  "src/kirabridge/windows_keyboard.py": "a3b5d554283ee71894bba28848bf1a5c9bf2dad7deb861d5ed089f926b8297c6",
  "src/kirabridge/windows_windows.py": "b575eb67018334364eaf887b31ab67d4dcb59e487ec66f3b3cfe06e49183405c",
  "src/kirabridge/windows_preview.py": "d9dd0b0730280a354da0ddf8d26e25382caca1cbc7a1be09b50e18ba7f14027c",
  "pyproject.toml": "418d7b9a7e34308884830102de0aea4d3d573e41cb361839ac4e7d06fb9d9c86",
  "src/kirabridge/__init__.py": "d7183789a0f371652e0f26e6d6ff543dc46d6c3916a08138d7e12f243379171f",
  "uv.lock": "239075b8ec4529f19972d7b02329eda4cfc383cd92916a01b150066aeda8da87"
}
```
