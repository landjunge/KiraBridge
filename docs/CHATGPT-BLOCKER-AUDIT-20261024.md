# ChatGPT execution blocker audit · 2026-10-24

The operator explicitly requested full ChatGPT access and team-based repair of
unnecessary blockers. Scope is KiraBridge only. This is an evidence-based audit of
policy, discovery, routing, queues/activation, terminal I/O and ThreadDesk adapters;
it is not a claim that every possible project defect has been eliminated.

## Team ownership and verified repairs

| Owner | Module/files | Concrete problem and repair | Necessary evidence |
|---|---|---|---|
| Root | `discovery.py`, `mcp_gateway/server.py` | One-second health monitors occupied foreground terminal read slots. Health defaults to passive discovery, explicit fresh observation remains available. Cached sessions are permission-bound and never input proof. | Prepatch real-HTTP monitor failure;4 focused checks, then3 affected denial/cache checks after team review. Installed f6deb46: formerly busy actual session.read succeeded. |
| Root | `operations_service.py` full selection | Operation names differed from real capability names (`files.inspect`). Explicit full selection now includes actual registry capabilities. | Reproduction missing files.inspect,2 full/revocation checks passed. Productive ChatGPT grant still pending separate activation. |
| terminal_repair | `visible_handoff.py`, `message_manager/__init__.py` | Authenticated final replies / externally ACKed queued deliveries could remain counted as pending. Counts now use original ACK plus exact final reply for execution, or ACK alone only for unstarted delivery. | Two reproductions;19 directly related cases passed. Running jobs, partial input, ACK-only execution and unknown histories stay protected. |
| terminal_repair | `operations_service.py`, `operator_queries.py` | An old ACK-only external wait blocks ordinary activation. New local `principal_grant` mode permits only one principal's ACL diff, preserving external sent/confirmed reservations without replay. |12 focused mode cases;3 directly related checks and1 restart-race/recovery case passed. Source/config/schema/credential/receiver/profile changes, running work and partial input still refuse. No productive use claimed yet. |
| receiver_contract_audit | `team_manager/__init__.py`, `team_console.py` | Legacy approval_mode overrode explicit full levels for team writes/workers. Central effective automatic decisions now apply; role/worker/agent/capability checks remain. |7 new cases plus7 existing directly related regressions passed; only one case rerun after extra ask/medium assertion. |
| receiver_contract_audit | `read_query.py` | Owned visible/admin output rejected, visible output lost, clipped Unicode could exceed byte budget. Return bounded `terminal_output` separately from stdout, preserve ownership and output origin. | Covered above; additional Unicode/status4-case prepatch failure then4 passed. |
| receiver_contract_audit | `development_status.py` | Displayed approval_required used legacy manual flag. Now returns actual scoped permission decision. | full/manual and ask/automatic in those4 cases. |
| whiteboard_repair | `threaddesk_dynamic.py` | Effective full/medium read grants contradicted legacy mode; tools beyond first page disappeared. Central decision plus bounded pool pagination. |4 prepatch failures,7 relevant cases passed; no productive peer changes. |
| whiteboard_repair | `threaddesk_manager.py` | Connected adapter rejected newly added read/knowledge tools, or dispatched removed ones using stale catalog. Refresh before every declared dispatch, retaining mutation schema checks and no replay. |4 prepatch failures,6 targeted cases passed, including unknown mutation exactly once and size denial before dispatch. |

No whole suite was repeated. Fixture mistakes and formatting findings were kept
separate from product reproductions. Root reviewed agent code before integration.
Team changes remain distinct from actually installed source until build/install
and live health evidence identifies their pin.

## Open native terminal evidence

Stable by-ID parent binding and exact unique Window/Fenster menu activation passed
focus-only Intel-macOS checks. Original pre-Paste/PID/image/TTY/viewport guards stay.
Actual Kira input B2 failed visible_focus_changed; B3 became unknown/session_input_unknown.
Readback contained neither payload, current widget was empty. No automatic resend.
A no-Paste diagnostic reached the complete pre-Paste path in4.651s and restored the
known test clipboard. Another diagnostic exceeded its budget. The generic native
worker can be killed before its JS finally restores the clipboard: the clipboard
was actually left containing B3 test text. A separate clipboard lease repair is
in progress; native positive input acceptance remains open. A previous test fixture
vanished without established cause. Never reuse its stale handle or choose a foreign
window. No design preview has started.

## Actual authorization versus external prerequisites

The productive policy already has full/automatic, filesystem/read/terminal roots `/`,
any executable and configured agents. Missing files.prepare/transfer/inspect are
being added only under the latest explicit user authorization; no self-grant by
ordinary MCP calls. The standard activation attempt failed service_busy without
changing config: old Grok handoff channel-aa35… has authenticated ACK but no final
reply. That is not falsely completed or retired. The narrow local ACL activation
mode exists specifically to preserve such durable external waits without interrupting
Codex2/3 or altering their configuration.

Actual Kira Whiteboard write plus independent full readback succeeded (revisions30,
32,33). Cached Apps declarations still incorrectly require completion_subscription;
the live RC17 contract does not. Empty legacy field is proven compatible. This
session has no host metadata-refresh tool, and no new Events subscription is needed.

File transfer additionally needs configured sources/projects and a real ThreadDesk
byte receiver. The active frozen peer lacks file_import_* ports; no Library-wide API,
external source rights, receiver or storage receipt is invented. No ThreadDesk code,
receiver configuration or original files were changed. Feature availability is not
the same as an ACL grant.

## Integration state

PR32: <https://github.com/landjunge/KiraBridge/pull/32>. GitHub Actions jobs were not
started because account payments failed or spending limits need adjustment. Failed
or not-started controls are not bypassed; PR remains open, RC17 remains a draft and
published release remains RC14. Productive source at this report snapshot is
f6deb46/PID59932, not yet all team changes. All recorded previous package/upgrade
proofs retain their own exact source pins. No whole-suite or Actions success claim.

## Clipboard lifetime follow-up

The GUI worker's timeout could kill its in-process finally before restoration.
`platform_adapters/clipboard_lease.py` now owns the original formats in a separate
bounded memory-only helper; only payload crosses stdin, never argv/logs/files.
The GUI worker uses stdin for its script too. Generation checks immediately before
Paste reject a changed clipboard; user changes survive cleanup. EOF requests restore
after the GUI worker is reaped; repeated cancellation cannot skip that reaping.
Unconfirmed restoration is an explicit error, never success or permission to replay.
JXA length/count arithmetic is normalized to numbers, avoiding false size limits
from string concatenation. Existing item/type/byte budgets remain.

Native echo timing now checks newly changed nonempty text or a new collapsed-paste
marker, not an empty trailing line or pre-existing history. Its wall-clock polling
budget is bounded. This observation is not an authenticated agent acknowledgement.

Necessary evidence: protocol lifecycle tests (17 defined cases covered through
initial/affected/generation runs),3 affected native syntax/identity checks,2 worker
integration cases,7 cancellation/echo cases and1 directly related trailing-space
case passed. No full suite. Actual Intel-macOS stdin execution, numeric generation
and restoration after an independently killed worker passed with the known own
clipboard fixture; [evidence](evidence/rc17-clipboard-lease-macos-20261024.json).
This does not yet claim a passing productive native paste.

## Installed full grant and final terminal responsiveness follow-up

RC17/5d1cba1 was built twice identically and passed actual isolated Intel-macOS
upgrade/status/data preservation/rollback before productive installation. It ran
as PID65344. The subsequent explicit local ChatGPT-only ACL activation completed
as activation-e14e0a12614d4cfb8b1e048dea7797e7, preserving every handoff and handoff
event, credential bytes/mode and all unrelated configuration. The actual Kira Apps
operation_catalog independently reported all42 registered operations authorized
and automatic, none missing a capability and none requiring approval. Runtime
PID65459/source5d1cba1/config SHA4d116741… was independently read back. The source
fingerprint was b4d9be4a75e34678829ab13899ba9caf93919d3b6e8e4d63187310a7a91307d3.
File-module/receiver prerequisites remain distinct from this complete ACL grant.

Actual input test4 was refused before native intent with TimeoutError; no input
execution claimed. Read-path profiling on the own fixture measured2.08s normally,
but exposed three complete catalogs and four desktop/native probes inside the8s
read budget. The read/readiness chain now shares one fresh, private operationscope:
principal/handle/PID/current-task/active lifetime must match, inherited expired or
foreign scopes refuse. It is never input authorization. Fresh agent_selection,
insert selection and native identity/focus/widget checks remain. Count reproduction
failed3!=1 before repair; the count case and six necessary scope/read/selection
regressions passed. No global stale window cache or caller-supplied snapshot.

An additional native stall risk was explicit: the Edit menu stayed in tracking mode
while Terminal Apple events and process checks were requested. Preparation now
validates then AXCancels that menu before all guards, and invokes only the exact
Paste item's documented AXPress action afterward. An actual own-window Intel-macOS
probe confirmed enabled Einsetzen/AXPress, closed-menu geometry and exact focus
recheck, without Paste: [probe](evidence/rc17-native-menu-20261024.json).
Activation is acquired once with a bounded2s observation wait; subsequent input
checks remain immediate. Mutation-worker budget is15s, accommodating the measured
4.651s pre-Paste path plus bounded2s focus and4s observation phases; reads retain
their prior budget. Five directly affected JXA/identity/lease/cancellation checks
passed. This still is not a passing installed final-Paste claim.
