# Repository work context

Use the existing ThreadDesk Whiteboard **“ThreadDesk und KiraBridge – Wechselentwicklung
durch Codex”**, thread ID **188ce4729a62**, as the current work memory. Do not create a
competing Whiteboard. Read it through existing authorized ThreadDesk tools when resuming.
Update it at meaningful milestones and before switching between KiraBridge and ThreadDesk.
Separate completed work, work in progress, open issues and plans. Preserve existing
content; append with an observed revision and stable operation ID. Independently read
back every write before reporting it saved. A failed/uncertain write must be reconciled
by task/operation ID, never blindly repeated. If access fails, record the exact error in
the existing work report and continue independent authorized work.

KiraBridge and ThreadDesk remain separate modular codebases. A status note is not
permission to alter production installations, credentials, user data or OS permissions.
The current ordered repair status is in `docs/REPAIR-SEQUENCE-20261024.md`; do not assume
its deployment gates have been satisfied without current evidence. The queued Library
request must not be executed a second time. Keep unknown execution states explicit.

Tests: run only tests necessary for the actual change and relevant effects. No extra
or precautionary repeated whole-suite loops. On failure rerun only the affected test
and directly related checks. Required security, review, merge and release checks remain
mandatory; never bypass failed/not-started checks or label an interrupted run passed.

Standing operator preference (26 October 2026): use native subagents for independent
project work, review their results before integration, and commit/push completed
authorized changes so the local branch and GitHub stay synchronized. Keep releases
and the operator Mac current after the required acceptance succeeds; preserve data,
permissions and running agent sessions. Productive installation must be genuinely
visible in a confirmed separate macOS Terminal window. Never treat this preference
as permission to bypass failed/missing gates, publish unverified assets, change
billing/OS rights, or perform unrelated work. Report concrete blockers and actual
commit, PR, release and installed-source status.
Reuse one freshly confirmed, owned visible work/install window. Do not open new
Terminal windows for every probe or step, and never use a running Codex/Grok
session as an installation window.
The operator explicitly allows one new owned test window when needed. Keep at
most one such additional window open, reuse it for the necessary test steps, and
close that owned idle window afterwards with an independent absence check. Do
not accumulate test windows or close unrelated windows or agent sessions.
