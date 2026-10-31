# README verification · 2026-10-31

This report records the documentation review, not a new product acceptance run.
Both user READMEs describe the published download. No application code, release,
installed service, credentials, OS settings or other project was changed.

## Checkout and release

- Repository: `https://github.com/landjunge/KiraBridge.git`; default branch `main`.
- Delivery checkout: `/Users/landjunge/KiraBridge`, branch
  `fix/visible-busy-idle-20261021`, source commit `dfbae48`.
  Existing application-code changes were preserved. The README and associated
  documentation were updated directly here after the user's clarification.
- The publication worktree is `KiraBridge-worktrees/readme-bilingual-20261031`,
  branch `docs/readme-bilingual-20261031`, based on upstream `main`.
  Refreshed upstream `main` is `307004e5b2e4285c19e8d7544bedf45b28297a0b`;
  the release source was verified separately. No branch was switched or merged.
- Latest published release: [v0.8.0rc20](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20),
  published `2026-10-30T21:23:04Z`, explicitly a prerelease.
- Release source: `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4`.
  `git log origin/main..v0.8.0rc20` and `git diff origin/main v0.8.0rc20` identify
  the subsequent shell, visible-terminal, dynamic-tool and reservation changes.
  The release tag is ahead of `main`; this docs change does not merge those changes.
- The complete authenticated release inventory contained 11 records: seven
  published prereleases and four drafts. No stable release was present. RC17,
  RC16 and RC15 remain drafts; their assets are not offered as published downloads.
- The repository is private. Successful authorized downloads do not establish
  anonymous access. A reader without repository permission may receive a 404.

API metadata, release asset URLs, digests and local verification counts are saved in
[the release evidence](evidence/readme-release-check-20261031.json).

## Claim checks

Code and tests were inspected at the RC20 tag; tests are evidence of intended and
checked behavior, not proof that every user's setup works. Product tests were not
rerun for this documentation-only change.

| README statement | Code and test evidence at the release tag |
| --- | --- |
| Read allowed files and complete large logs in parts | `filesystem_manager`, `file_ranges.py`; `tests/test_file_ranges.py`, including byte reconstruction, changing sources and excluded paths |
| Edit, move and delete only with matching rights; run allowed commands | `operations.py`, `filesystem_manager`; `tests/test_desktop.py`, `tests/test_permissions.py` |
| Use configured agents with separate accounts | `agent_manager`; `tests/test_agents.py`; no universal provider or account availability claimed |
| View results and locally approve or reject tasks | `approval_console.py`, `control_center.py`, `console_assets/app.js`; `tests/test_permissions.py` |
| Protect busy/uncertain visible terminal sessions | `visible_handoff.py`, `session_manager.py`; `tests/test_visible_handoff.py`, `tests/test_sessions.py` |
| RC20 repairs blocking after a closed Terminal's TTY is reused | `visible_binding.py`, `session_manager.py`; `tests/test_closed_terminal_reuse.py` |
| App needs the installed CLI/service | `integrations/desktop/main.swift` calls `~/.local/bin/kirabridge approvals`; verified ZIP contains the service installer separately |
| Fresh setup is manual and scoped | `installer/install.py` configuration creation; broader `--full-access` is explicit, not the default |
| ChatGPT setup is separate, account dependent | `installer/install.py`, `chatgpt_setup.py`; no automatic connection, universal voice support or autonomous wake-up claimed |

Known RC20 limitations were also checked against later local project evidence:
`bridge_core/bridge.py` routes recognized-agent `session.input` with `submit=true`
through an agent-work envelope. An interactive `/resume` can therefore become a
work message. `visible_readiness.py` can reject a usable Codex composer alongside
navigation hints. The later fix at `881a53f` changes those paths; it is absent from
the released `da1bdae` package. Both READMEs link to these limits in the installation guides instead of
advertising the local repair as released.

## Download and branding checks

All 14 RC20 assets were downloaded through authenticated `gh release download` to
a temporary directory, without running the installer. Each download matched its
GitHub API SHA-256. All 13 entries in `SHA256SUMS-INTEL` matched. The large Intel
ZIP contains `KiraBridge-Installieren.command`, `KiraBridge.app` and the runtime;
the smaller ZIP is only the companion app. All 394 runtime manifest entries
matched. Each set of 122 Python files in the packaged source and wheel matched
the release commit. The bundled instruction text and
installer entrypoint were read directly. The manifest's source pin was checked
against Git, and package source files were compared with that release commit.

Existing 256 px light/dark icons from `assets/design/` were visually inspected and
reused, displayed at 160 px. Their origin is documented in
[the existing design inventory](https://github.com/landjunge/KiraBridge/blob/307004e5b2e4285c19e8d7544bedf45b28297a0b/assets/design/README.md). No branding was created.

## Existing test evidence and limits

Downloaded `PACKAGE-ACCEPTANCE-INTEL.json` records actual isolated Intel macOS
15.7.4 install, RC18 upgrade, preservation, restart, KeepAlive, rollback and cleanup.
Its regression record is **1,969 passed, five stale-fixture failures and one optional
skip**, followed by **seven affected cases passed** after test-only corrections:
1,974 distinct validated cases, not a clean first full-suite pass. Those historical
results were read, not rerun or relabeled as new acceptance.

Intel release evidence does not validate Apple Silicon, macOS 26, older macOS,
hosted macOS CI, notarization or every ChatGPT Live/Voice workflow. The app's
reported native architecture is Intel x86_64. Source metadata accepting other
targets is not a platform acceptance result. No current installed version was
inferred from this release review.

## Documentation validation

The English/German READMEs were compared section by section for version, downloads,
features, setup sequence, requirements, limitations and license wording. Their
external targets are identical; localized documentation links lead to counterpart
files. Markdown rendering checks passed for both prominent download links, three-step
start lists and light/dark picture elements. Relative links and images across
eight changed Markdown files were checked, with zero broken targets.
`git diff --check` passed.
Release links were checked against authenticated live metadata and actual assets.
The version-pinned RC20 release notes were fetched successfully. The per-app macOS
opening guidance follows [Apple's instructions](https://support.apple.com/en-us/102445),
also retrieved during this review.

Existing useful configuration, safety, troubleshooting and build details were
preserved in separate developer documents. The two installation guides were
updated in place. Stale current-version/setup claims in `CHATGPT.md` were corrected;
four missing historical archive targets were retained as clearly marked plain-text
references. The existing archive was not presented as current setup guidance.

Only KiraBridge documentation was edited. The user's explicit scope excludes
ThreadDesk/Whiteboard writes and overrides the broader repository workflow.
No release publication or installation was performed. The user subsequently
authorized the documentation push to GitHub; its final commit and remote readback
are reported separately.

## Revision after user feedback

The initial draft was too long and technical for a user landing page. The revised
READMEs preserve the existing primary working README's tagline and introductory
paragraph in each language. They put one complete download first, explain four
practical uses and give three starting steps. Detailed terminal limitations moved
to the linked installation guides. Requirements and preview status remain visible.
The revised README and its associated documentation were then applied directly
to `/Users/landjunge/KiraBridge`; its existing application-code changes remain untouched.

The latest GitHub release inventory and remote main/tag references were checked
again before the direct update. RC20 remains the latest published preview.
Documentation files absent from the older working checkout are linked to the
verified upstream commit instead of importing unrelated source changes.

## Publication preparation

The user explicitly authorized pushing this documentation to GitHub. Only the
nine README/documentation files are included. Application code, releases and
installations are excluded. The existing design inventory, app resources and
approved light/dark presentation were inspected again: they contain KB monogram
icons, but no separate KiraBridge wordmark artwork. The existing icon is reused
with the product name, without creating a new wordmark. Remote README HTML and
its image files are checked after pushing; no success is inferred from local
paths alone.
