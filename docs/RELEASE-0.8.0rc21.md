# KiraBridge 0.8.0rc21 · Intel macOS

Visible Codex/Grok handoffs now paste the supplied message body exactly. KiraBridge
adds no task header, ACK/reply instructions, previous-message appendix or end marker.
Sender, message ID, receipt, routing and duplicate protection remain internal metadata.
The current input widget and original empty state are checked before Return;
historical uncertain handoffs are never reinterpreted or replayed.

A confirmed Paste/Return with explicit `wait_for_reply=false` is reported as
`visible_input_delivery`. It does not claim
that the agent acknowledged, answered or completed the work. Genuine subsequent
mailbox ACKs and replies remain separately observable. The compatible default
continues to wait for a genuine authenticated reply; it adds no instructions to
the user body. Already recorded genuine replies always take precedence.
New delivery reservations
are released only after a fresh matching target is ready with empty input.

Includes the already implemented modular macOS provider, repaired wrapped/blank-line
Prompt/Return handling and explicit no-prompt diagnostics for the actual helper
process. No OS rights are granted by those observations. The source implementation
and earlier productive evidence are documented in
[the adapter completion report](MACOS-PLAN-COMPLETION-20261031.md).

This prerelease targets the actually tested Intel macOS system. Apple Silicon,
other macOS versions, signing/notarization and all Live/Voice workflows are not
certified by those local results. Missing original research documents and the
existing desktop lock heuristic remain documented evidence limits.

## Deutsch

Sichtbare Codex-/Grok-Übergaben enthalten ausschließlich den übergebenen Text:
kein automatisch hinzugefügter Kopf, keine Quittierungs-/Rückmeldeanweisungen,
keine angehängte Nachrichtenhistorie und kein Endmarker. Die Auftragszuordnung
bleibt intern. Bei ausdrücklich gewähltem `wait_for_reply=false` belegen Einfügen
und Return die Zustellung, keine Agentenantwort oder Auftragsfertigstellung.
Der bisherige Standard wartet weiterhin auf eine echte authentifizierte Antwort,
ohne dem Auftrag dafür Text hinzuzufügen. Alte unklare Übergaben bleiben erhalten.

Der Release übernimmt den bestehenden Adapterstand und die ausdrücklich verlangte
Korrektur der sichtbaren Übergabe.


## Verified release state · 31 October 2026

Tag and source commit: `7ea0f24ae6c36f689d0889d41071fa8bca8aaf65`.
Both Linux CI axes passed 2347 tests, 38 skipped each. Local Intel native acceptance
passed 17 checks against the exact shipped Python source. Isolated launchd upgrade,
rollback, fresh install and the downloaded GitHub bootstrap passed. All 15 published
assets were freshly downloaded and their GitHub digests verified.

The operator Mac runs RC21 Core PID50602, started 2026-10-31T16:17:49.751678Z;
134 Python files hash `c3f75aa22e4f54b0b61a6af026cc2bbe7a5cd5d92f839e658e878642b3f3f7fd`.
Companion App PID50637 is updated too. Data, persistent credentials and existing
agent sessions were preserved. A supplementary live prompt was correctly refused
before input because the original cooperative release handoff still reserved the
canonical Codex slot; that supplementary delivery is not claimed as passed.

Hosted Mac jobs did not start because of billing limits. Short noncollapsed
multiline wrap states can still refuse with `visible_paste_unconfirmed` before
Return. These and retained failed intermediate probes are documented in
[the final release report](RC21-RELEASE-20261031.md).
