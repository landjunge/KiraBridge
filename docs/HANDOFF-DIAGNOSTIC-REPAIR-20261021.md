# Visible handoff diagnostic repair — 2026-10-21

Scope: additive, read-only diagnostic correction on architecture/six-stages-20261020. This is NOT a completed ThreadDesk integration into main and NOT a live terminal-delivery fix.

## Reproduced defect

VisibleHandoffs.execute records the original failure reason and stages in visible_handoffs / visible_handoff_events, but raises the generic visible_handoff_unknown. MessageManager.get returns only the receiver job evidence, so existing MCP callers cannot see the more specific stored handoff reason. The current live job still has an unconfirmed outcome; this change does not establish whether its input was accepted.

## Change

The existing message_get response receives processing.handoff only when the caller already has both message.read and task.read and is the exact bound sender or recipient. The reader joins message and handoff IDs and participant bindings. It reports an allowlisted reason, state and the latest 32 event summaries; raw prompts, paths, terminal text, receipts and arbitrary evidence fields are not exposed. Evidence parsing is bounded to 8192 bytes. No schema changes, new endpoint, permission change, reconciliation, retry, terminal action or runtime restart is introduced. Historical unknown remains unknown.

## Validation actually performed

The input MessageManager source was reconstructed from the pinned GitHub blob and byte-verified as 6b1e010410b0d3ee922e0f5392ac7a9b19731221 before changing it. On the prepared patch, 31 standard-library unittest component tests passed in an isolated Linux container. Tests use real SQLite and the AST-extracted actual MessageManager.get method with minimal boundary fixtures. They exercise scope binding, permissions, malformed and oversized evidence, event bounds, read-only authorization and preservation of unknown state. With the original MessageManager.get method, the identical suite reports two errors because processing.handoff is absent; the new method passes both regressions.

Command: PYTHONPATH=src python -m unittest discover -s tests -p test_visible_message_evidence.py -v

Not performed: full repository suite, Ruff/formatter, package build, actual macOS terminal acceptance, installation or authenticated live end-to-end verification. Therefore the patch is a review candidate, not a production-completion claim.

## Remaining integration work

Read the original handoff evidence after this code is reviewed and activated through the supported local installation path. Do not resend the existing work or press Return automatically. Recover the existing task according to observed insertion/submission evidence. Independently finish the ThreadDesk main-branch backport with its real permission model; preserve the existing runtime's terminal functions. Updating main must not downgrade the currently installed architecture runtime.
