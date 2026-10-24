# 0.8.0rc17 — consolidation candidate / Zusammenführungskandidat

**Not published or approved. Nicht veröffentlicht oder abgenommen.**
Latest published release remains [RC14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14).
RC15 and RC16 are historical drafts with their original source-pinned assets.

This candidate combines `main` at `9d03ea8` with the runtime/installer lineage,
RC15 `efb805a`, RC16 `a890375`, queue repair `de2c2f7` and terminal/Whiteboard
repairs through `48a512e`. It preserves main's guided setup, native agent adapters,
owned workflow stop, observations, knowledge integration and portable Linux setup.
It adds the RC16 discovery/file-byte sender and subsequent queue/visible-input/
Whiteboard contracts without replacing production configuration or granting access.

Dieser Kandidat führt die getrennten Quelllinien zusammen. Die Versionsnummer
RC17 unterscheidet das kombinierte Paket von den vorhandenen RC15/RC16-Assets;
deren historische Testbelege werden nicht als RC17-Abnahme ausgegeben.

macOS: Python3.11, uv0.11.6, macOS15, Internet and authenticated GitHub access;
Intel and Apple Silicon artifacts share the wheel/locked dependencies. Actual
arm64 acceptance remains open. No Apple signing/notarization. The launchd user
service continues independently of Terminal/browser windows. Linux source packaging
is preserved from main; its actual installation is not claimed tested on this Mac.

Release gates remain: mandatory CI (currently billing blocked), independent review,
positive native agent input acceptance and protected-main/final release-source validation.
The exact5089fca candidate passed [isolated Intel-macOS package acceptance](ACCEPTANCE-MACOS-RC17.md), including authenticated draft download, upgrade/restart/data preservation and rollback.
The existing native focus refusal is not a positive test. ThreadDesk byte receiver/
index MCP implementation and authorized selected source bytes are still prerequisites
for an actual user Library import. No Library-wide API or duplicate job is created.

See [consolidation record](CONSOLIDATION-20261024.md),
[installation and historical commands](INSTALL-MACOS.md),
[terminal evidence](VISIBLE-SELECTION-20261024.md),
[Whiteboard evidence](WHITEBOARD-BOUNDARIES-20261024.md) and
[receiver/index boundaries](RECEIVER-INDEX-CONTRACT-20261024.md).

Build only from a clean committed source: `uv run python scripts/build_release.py
--out dist/rc17-candidate`. A separately required reproducibility build must use
another empty destination and compare `SHA256SUMS`. This is a build instruction,
not a tested public installation command. No download link is invented here.

## Native focus and ChatGPT responsiveness follow-up (PR32, not merged)

The native focus repair binds immutable window IDs and resolves only unique current
Window/Fenster menu entries when activation selects another window; exact focus,
TTY, process and viewport checks remain. Focus-only actual Intel-macOS proof passed;
installed positive paste acceptance remains pending. Routine bridge_health now avoids
terminal scans so one-second multi-client polling cannot consume foreground read
slots. Explicit observe_terminals=true/inventory/catalog provide fresh observations.
The full operator grant now uses actual capability mappings, including files.inspect.
The latest user explicitly authorized full ChatGPT access; this does not create a
missing ThreadDesk byte receiver or an unsupported Library-wide API.

GitHub Actions is still blocked before execution by account billing. PR32 is open;
RC17 remains draft. Additional external review was waived by the owner; independent
native-team safety audits were performed. No failed Actions run is called passed.

The extended blocker audit fixes effective Team/ThreadDesk read permissions,
paginated/refreshed tool discovery, owned visible/admin output and UTF-8 budgets.
A local one-principal ACL activation mode preserves durable external reply waits
without changing their state or allowing partial-input interruption. Clipboard
restoration moves to an independent RAM-only owner, with generation guards and
stdin transport; killed GUI workers no longer own the only snapshot.
[Team findings and scoped tests](CHATGPT-BLOCKER-AUDIT-20261024.md).
Actual final-package/native-paste acceptance remains separately required.
