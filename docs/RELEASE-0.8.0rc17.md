# 0.8.0rc17 · Intel macOS

[Actual release status / tatsächlicher Release-Status](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc17).
A GitHub draft remains unpublished. Final assets, source commit, SHA-256 and installed
service acceptance are recorded separately in the release/PR43, never inferred from a tag.

## Änderungen / Changes

- Retains integrated RC15/RC16/main functionality, native provider adapters,
  guided setup, durable tasks, queue recovery, workflow stop, knowledge and
  optional ThreadDesk integrations. No production policy replacement.
- Preserves explicit visible-input/window/TTY/PID/focus safety, paste-only
  submit=false, current tool discovery and long Whiteboard contracts.
- Repairs native textual team-result queue catalog parsing and coalesces
  repetitive health diagnostics while retaining core audit and limits.
- Adds explicit unknown withdrawal separate from execution reservation, plus
  retirement only for proven vanished original targets. History stays; no fake
  stop/completion, blind repeat or interruption of current agent sessions.
- Reuses PR34's complete Braille KiraBridge wordmark/perspective bridge with
  exact#F06DB0 palette, lighter pink and white highlights. Bounded optional
  point/pulse animation, static reduced-motion and color/encoding/text fallbacks.
- Packages one stdlib renderer and hashed presenter into the actual versioned
  installer. Human output stays on stderr; MCP, statusJSON and daemon remain clean.
- Optional explicit visible installation guard checks current front window,
  selected tab, TTY and process identities. One owned work window is reused.
  Automatic recovery retains old-definition/ownership/idle guards even if
  visibility is lost after a failed switch. launchd remains window-independent.

## Nachweise und Abnahme / Evidence and acceptance

Actual Intel macOS15.7.4 / Python3.11.15, program source20a30e8:
**1609 passed,1 skipped**, Ruff/format, wheel and sdist passed. Actual built package:
**9/9 RC14 lifecycle checks passed**, including data retention, idempotency, installer-exit
independence, restart, KeepAlive, actual rollback and fresh launchd installation.
Native full Braille/pulse rendering and the authenticated isolated copy flow are proven.
Temporary test service was removed; production data/config/credentials were unchanged.

The operator explicitly approved local Intel acceptance for merge and visible installation.
Hosted Intel/ARM jobs did not start because of account billing/spending restrictions;
this approval does not claim green Actions or ARM acceptance. **Apple Silicon and macOS26
remain unverified.** Documentation-only finalization does not change tested program bytes;
the final merged source and new package hashes must be checked separately.

[Detailed evidence/approval](INTEL-ACCEPTANCE-20261026.md) ·
[Historical rollback failure and subsequent passes](RC14-ROLLBACK-20261026.md) ·
[Partial-write fix](BRAILLE-PARTIAL-OUTPUT-20261026.md).

## Installation / Update

Python3.11, uv0.11.6, authenticated private GitHub access and Internet required.
Actual tested OS is Intel macOS15.7.4; older macOS/iMac2015 and arm64 need their
own evidence. No Apple signing/notarization; no permission or billing changes.
Config, credentials, rights, Whiteboards, database and user files are preserved.

[Deutsch](INSTALL-DE.md) · [English](INSTALL-EN.md) · [Current status](../README.md).
Use the README authenticated checksum-verified RC17 command. The release identifies
the exact final source; historical source-pinned review assets remain historical evidence.
