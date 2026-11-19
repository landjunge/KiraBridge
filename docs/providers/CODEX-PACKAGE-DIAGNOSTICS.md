# Codex package observations

`agent_inventory` adds a passive `runtime_package` observation to allowed Codex
identities. The existing Doctor shows it separately from an executable file's
presence and execute bit. No CLI, wrapper, login, model or installer is started;
execution, permissions and response-only workflows are unchanged.

The bounded file reader covers the official **0.169.0 / layoutVersion 1** package
metadata, canonical `bin` layouts, a provisioned macOS entrypoint that resolves
to its declared package entrypoint, and the documented Windows WinGet root
layout. It follows the actual configured executable's symlink, without parsing
or guessing a script/Node/shell launcher's target. Other versions, opaque
launchers, missing/invalid metadata, different targets or unbound entrypoints
remain `unknown`. A wrapper's filename never changes its existing runnable flag.

Only metadata declaring the covered version/layout selects reference files.
Code-mode host lookup follows the manufacturer's resource-first, bin-second
order; a selected non-executable resource is not hidden by a usable bin fallback.
The package builder supplies the exec server, search tool and platform-specific
resource names. Missing reference files produce `layout_incomplete`; observed
files produce `layout_observed`. Neither means that the installation is complete
or that any tool can run. Windows file presence does not attest execute ACLs.

The declaration in `codex-package.json` is not an attestation of the CLI version.
Companion version matching, publisher/digest integrity, ABI, full distribution
contents, authentication and actual tool execution are not verified. Filesystem
observations are not atomic. The metadata read is limited to 16 KiB, the native
header prefix to at most 65,540 bytes, and component checks to a fixed file set;
no recursive scan or package download occurs. External component symlinks are
reported as unknown. The observation exports relative reference names, not
launcher text, credentials, arbitrary metadata or private installation paths.

Doctor uses informational rows for unknown/observed layouts and a warning for
known missing/non-executable reference files. It adds no admission, confirmation
or repair requirement. Successful existing text replies remain valid text-reply
evidence; their success never proves the complete tool runtime.

Pinned primary references, all at `openai/codex` tag `rust-v0.169.0`:

- [Runtime locator and package metadata](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/install-context/src/lib.rs)
- [Package layout and required files](https://github.com/openai/codex/blob/rust-v0.169.0/scripts/codex_package/layout.py)
- [Supported package targets](https://github.com/openai/codex/blob/rust-v0.169.0/scripts/codex_package/targets.py)
- [WinGet adaptation](https://github.com/openai/codex/blob/rust-v0.169.0/scripts/build_winget_package.py)

Tests use artificial files and package metadata. A simulated target layout is
not native Windows/macOS/Linux runtime acceptance. No existing CLI package or
authentication is changed by this feature.
