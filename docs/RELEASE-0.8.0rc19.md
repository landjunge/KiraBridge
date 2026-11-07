# KiraBridge 0.8.0rc19 · Intel macOS

This candidate contains the existing native Swift/Cocoa/WebKit companion and Python
bridge. The Intel package and source commit are identified by release.json and SHA256.
Actual acceptance, installation and publication evidence belongs to the matching
GitHub release and docs/ISSUE51-SHELL-PROMPT-20261030.md; do not infer passed gates
from a successful build alone. Older releases remain separate.

Changes: recognize the current Codex queue composer without mistaking old submitted
prompts for pending input. Empty queued input while the agent works stays protected.
Dynamic ThreadDesk discovery is explicit and schema-based: dynamic_read_proxy enables
readonly tools; dynamic_tool_proxy enables all tools allowed by the current grants.
Mutations require stable operation IDs and durable tasks; uncertain effects are not
automatically replayed. ThreadDesk remains a separate configured MCP server.

Existing ThreadDesk integration requires both explicit flags in [threaddesk], a valid
configured peer/workspace and corresponding read/manage/knowledge permissions.
The Intel operator configuration migration is guarded and reversible. Before rolling
back to RC18, remove only the newly added dynamic_tool_proxy field under the recorded
configuration hash; old RC18 rejects this unknown field. Never restore an old database.

ARM, paid hosted-macOS CI, notarization and complete Codex/Live/Voice host acceptance
are not certified by the Intel package. This is an Intel prerelease, not a Tauri app.
