# KiraBridge 0.8.0rc24 · terminal and connection reliability

Current local outcome: source `023f70feefcf8fcaa17b0637738b02644ad6b357`
passed real Intel macOS Terminal/Codex acceptance and is installed with Core,
Console and Companion verified. See the [installation evidence](RC24-INSTALLED-20261101.md).
No new hosted CI, push or GitHub publication was performed under the user's
budget constraint. Earlier candidate statements below are historical checkpoints.

An explicitly selected Terminal.app tab now uses only its native catalogue.
An unrelated tmux read failure can no longer block that selection. Explicit
tmux selection likewise avoids unrelated native observations. General discovery
continues to report both transports and their individual availability.

Read-only process catalogue, identity and shell-snapshot timeouts now preserve
their responsible phase as a typed observation error. A read failure never proves
input, Return, successful execution or permission to replay an uncertain task.
Existing observation deadlines, owned-subprocess cleanup and target guards remain.

This continues the RC23 investigation. The historical pre-paste TimeoutError has
no uniquely established cause; these are independently reproducible failure paths.
Actual tests, package verification and physical acceptance are recorded separately
in [the continuation report](RC24-PREFLIGHT-20261101.md). Publication or installation
is not established by this candidate document.

Deutsch: Die Auswahl eines konkreten Terminalfensters hängt nicht mehr von
unbeteiligten tmux-Abfragen ab. Lesetimeouts melden ihre zuständige Phase.
Die Prüfungen von Prozessidentität, mehrdeutigen Ansichten und beschäftigten
Zielen bleiben bestehen. Die vollständige Prompt-/Return-Abnahme ist gesondert
nachzuweisen.

The subsequent independent team review repairs concurrent MCP teardown, stale
connection results and catalog invalidation races; validates macOS plist roots
and ASCII token configuration; rejects ambiguous newly opened terminal handles;
and fixes JSONL event framing at chunk/size boundaries. Routing avoids unrelated
native metadata reads, and event parsing avoids repeated remainder copies.
Regression evidence, measurements and remaining risks are recorded in the
[reliability review](RELIABILITY-REVIEW-20261101.md).

This remains an unpublished candidate. `file.move` now captures into a private
regular-file sentinel, verifies a pinned inode and publishes without replacing an
existing destination. It never unlinks the public source path after capture, so
a concurrently recreated source survives. The kernel rejects directory capture.
Interrupted or conflicting attempts retain recovery data and never replay
automatically. The [move contract](FILE-MOVE-CONTRACT.md) explains temporary private
reachability, retained/unknown receipts and explicit local recovery.
The earlier native Codex handoff acceptance remains unresolved at this checkpoint.
The working RC22 installation is preserved.


The follow-up team review also bounds native app bootstrap pipes and execution,
limits web navigation to the owned starter receipt and Console origin, sets AX
timeouts before observation and uses chunked native request framing. Terminal
submission revalidates the exact process generation at the effect boundary;
malformed process inventories fail explicitly. Indexed TTY observation reduces
repeated catalogue scans without changing catalogue results.

MCP admission, catalogue locks and connection waits have deadlines; complete
validated catalogues have an 8 MiB serialized budget. Expired backoffs and settled
delivery markers are pruned while uncertain storage states retain No-Replay
protection. A narrow, renderer-verified Codex input profile refuses ambiguous
full-row geometry before paste. It does not expand acceptance of other Unicode
or wrapping forms. The unchanged strict post-paste evidence remains required.

The [follow-up report](RELIABILITY-FOLLOWUP-20261101.md) separates measured
improvements, rejected optimizations, actual test results and pending live gates.
Diagnostic history and its exhausted production cap were preserved; ordinary
task/message/audit evidence remains available independently of optional diagnostics.
