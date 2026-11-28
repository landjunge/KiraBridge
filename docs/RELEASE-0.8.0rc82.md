# KiraBridge 0.8.0 RC82 — regular build of the delivery_timeout fix

Source-only release candidate. It has not been installed or restarted on this build host as
part of this build; it packages the current `main` history for later, user-triggered
installation.

RC82 is the first regular release build to contain PR #337 (claimed direct deliveries get a
fresh window before giving up) as a tracked commit, rather than only as a hotpatch applied
ad hoc to the running 0.8.0rc81 installation. It also carries the two other changes merged to
`main` since the RC81 candidate was cut:

- #328 — Approval console: reuse ps/launchctl status observation for 30 s (perf/approval-poll).
- #336 — Stop auto-displaying a terminal session in the Terminals tab.
- #337 — Give claimed direct deliveries a fresh window before giving up (delivery_timeout fix).

No application code changed beyond what shipped in #328/#336/#337; this candidate exists to
produce a regular, reproducible release package for the fix that was already hotpatched live.
