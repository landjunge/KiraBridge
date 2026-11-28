# KiraBridge 0.8.0 RC83 — regular build of the receiver-routing and retry fixes

Source-only release candidate. It has not been installed or restarted on this build host as
part of this build; it packages the current `main` history for later, user-triggered
installation.

RC83 is the first regular release build to contain three fixes that landed on `main` after
RC82 was cut:

- #339 — Honor explicit `separate_managed_session` worker config in receiver routing. Fixes
  the coordinator (Claude) not automatically receiving team messages.
- #340 — Unify `DEFER_UNSENT`/`WAIT_REASONS` handling so `desktop_locked`,
  `desktop_session_inactive`, and `visible_input_not_empty` are retried instead of being
  wrongly treated as final failures.
- #341 — Defer pure pre-claim terminal-observation failures (`session_observation_timeout`
  and sibling codes) instead of failing them instantly, so transient observation errors
  (seen with Qwen, and in general) get a bounded retry instead of an immediate hard failure.

No application code changed beyond what shipped in #339/#340/#341; this candidate exists to
produce a regular, reproducible release package for fixes that, prior to this build, were only
available as a manual hotpatch (#337-style) applied ad hoc to the running 0.8.0rc81
installation.
