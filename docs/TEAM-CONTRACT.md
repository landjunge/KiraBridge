# Team implementation contract v1

Internal implementation contract, shared by the three implementation agents.
Root owns config, Bridge/MCP integration, activation and release packaging.

## Configuration (root implements)

`config.team`: enabled=False, workers=dict[str,TeamWorkerConfig] (max16), concurrency=2,
max_hops=6, max_work_per_root=32, max_pending_per_member=32, max_total_work=10000,
max_messages=10000, max_body_bytes=16384, max_result_bytes=65536,
max_actions_per_turn=4, max_runs_per_hour=24, max_teams=64. TeamWorkerConfig: agent:str|None=None, cwd:str|None=None,
timeout:float=120, response_framing:strict_json|work_reply_header='strict_json'. The workers mapping is an operator-owned participation AND
automatic-execution consent roster. A null agent is an external/manual member,
including ChatGPT. An automatic worker needs its own authenticated principal,
agent.execute capability, configured own agent grant, allowed fixed cwd and
automatic approval mode. Team roles never widen OS/file/executable permissions.

## Domain (team_domain implements)

`TeamManager(bridge)` at `bridge.teams`, `interface_version='1'`, `.wake=asyncio.Event`.
Own additive `team_*` SQLite tables via existing Store transaction; no Store
user_version change, no relaxation of private tasks/messages.

Models in team_manager/models.py, all strict existing Input subclasses:

- TeamCreate: team_id, name, members:dict[str,role], coordinator:str,
  idempotency_key. Creator is owner separately and is always a member.
- TeamRoleSet: team_id, member:str, role, active:bool=True,
  expected_revision:int, idempotency_key.
- TeamMessageSend: team_id, recipient:str, body:str, kind(question/answer/work/result/note),
  idempotency_key, reply_to:str|None=None. No caller-selected sender.
- TeamWorkCreate: team_id, assignee:str, title:str, body:str,
  idempotency_key, parent_id:str|None=None.
- TeamWorkClaim: team_id, work_id, idempotency_key.
- TeamWorkReprocess: team_id, work_id, core_task_id, expected_result_sha256, idempotency_key.
  Owner/coordinator only: one explicitly pinned postprocessing of a known completed
  native result with no previously applied actions. Never a model retry; original
  completion and result snapshot remain preserved.
- TeamWorkComplete: team_id, work_id, result:str, success:bool=True,
  idempotency_key. Only manual/external assignee; evidence is assignee_report.

Roles: coordinator, worker, reviewer, observer. Exactly one active coordinator.
Owner is immutable and separately retains control. Only owner/current coordinator
can set roles. Worker/reviewer/coordinator may send and delegate to any active
non-observer member. Observers only read. Owner/coordinator cannot enable an
identity outside config.team.workers. Removing the current coordinator requires
selecting a different coordinator first. Setting role=coordinator atomically
demotes previous coordinator to worker. Role changes require revision CAS.
Capabilities: team.manage for create; team.read for read; team.write for all
other member writes, with role/owner authorization enforced additionally.

Public synchronous methods:

- create(principal, TeamCreate)->team dict
- list(principal)->{'teams':[...]} ; get(principal,team_id)->team incl members/revision
- context(principal,team_id)->bounded recent team/work/message context (32 KiB)
- set_role(principal, TeamRoleSet)->team
- send(principal, TeamMessageSend)->message dict
- messages(principal,team_id,after=0,limit=50)->{messages,next_cursor}
- ack(principal,team_id,message_id)->message (actual recipient only)
- delegate(principal,TeamWorkCreate)->work dict
- work_get(principal,team_id,work_id)->work dict
- work_list(principal,team_id,after=0,limit=50)->{work,next_cursor}
- work_claim(principal,TeamWorkClaim)->work; work_complete(principal,TeamWorkComplete)->work
- work_reprocess(principal,TeamWorkReprocess)->work
- events(principal,team_id,after=0,limit=50)->{events,next_cursor}

Shared work fields: id, team_id, assigned_by, assignee, title, body, parent_id,
root_id, depth, state, core_task_id, result, evidence, error, created, started,
finished. Manual work starts queued_manual; automatic work starts queued.
Public views contain ONLY intentional team data and sanitized linked result;
do not expose private TaskRequest.args or unrelated tasks. Membership is checked
on every access, including results. Recipient receipt timestamps are separate
from model execution. Queues/results/messages are bounded in UTF-8 bytes.

Runner-only methods (not public MCP):

- pending(limit=16)->list[work dict], queued with core_task_id IS NULL only
- claim(work_id)->work|None; recheck current author/assignee role, persist
  dispatching and deterministic core_task_id BEFORE any external submission
- inflight(limit=32)->list[work], all known core IDs not terminal
- seal_request(work_id,TaskRequest): persist exact request hash before submission.
- finish(work_id,result,evidence): finish processing_result after actions.
- bind_task(work_id,core_task:dict)->work; validate ID/owner/agent against roster,
  copy only state/native evidence/result, never raw args. Used also for refresh.
- fail(work_id,state,error_code,evidence:dict)->work, sanitized error only
- authorize_execution(core_task:dict)->None: for linked team work check current
  active member/role/roster/assignee and sealed request hash. Principals marked
  team_only_execution cannot use unlinked agent.execute; ordinary existing
  principals retain private task execution.

No automatic replay after uncertain outcome. On restart, known core tasks are
only observed; a previously claimed work whose core ID does not exist becomes
unknown, never resubmitted. `queued` unclaimed work is safe to claim once.
Team action delegation ancestry uses actual parent work; limits max_hops,
max_work_per_root and pending count are transactional and cannot be bypassed by
renaming IDs. Team audit stores hashes/IDs, not bodies, secrets or raw errors.

## Dispatcher (team_dispatcher implements)

`TeamDispatcher(bridge)` at bridge.team_dispatcher, async start/stop.
Starts only enabled; own bounded workers waiting on teams.wake (no idle busy loop).
Submit agent.execute via MCPClientPool peer(config,work.assignee), deterministic
core ID and idempotency key, fixed roster agent/cwd/timeout and generated prompt.
No direct adapter or shell execution. TaskManager owns all actual process work.
Observe existing tasks after restart, without a new submission. On stop, let
submitted work finish within its finite timeout; do not kill unrelated sessions.

Generated prompt includes bounded team roster/roles, current shared work/results,
recipient metadata and input. The adapter can return plain text as its result,
or exactly one JSON object (no code fences):

`{"kirabridge_team":"1","result":"text","actions":[{"type":"message","recipient":"grok","body":"question","kind":"question"},{"type":"task","assignee":"grok","title":"title","body":"request"}]}`

At most max_actions_per_turn (hard max4). Strict known fields, no shell/sender/role
fields. Execute actions as the authenticated receiving principal through the
same public team MCP tools. Message actions use dispatch/inbox only (no implicit
model echo). New work gets parent_id from the REAL current work, never model.
Deterministic per-work action keys make post-result recovery idempotent.
Action parsing failure is recorded visibly, never interpreted as arbitrary code.
Task-producing actions inherit ancestry limits; result/answer messages never
spawn models. No automatic infinite conversation or role-changing model action.

## MCP / UI (root + team_console)

MCP tools: team_create(request), team_list(), team_get(team_id),
team_set_role(request), team_message_send(request), team_messages(team_id,after,limit),
team_message_ack(team_id,message_id), team_work_create(request),
team_work_get(team_id,work_id), team_work_list(team_id,after,limit),
team_context(team_id), team_work_claim(request), team_work_complete(request),
team_work_reprocess(request), team_events(team_id,after,limit).
Principal always comes from existing authenticated MCP context.

TeamConsole(bridge,authenticate) module supplies .routes to extend existing
approval_console.py Starlette app. Existing authenticate(Request) returns local
principal? Inspect actual function: use existing local browser authorization and
fixed 'local' identity, never request JSON identity. Existing Host/Origin guards
stay effective. UI /team with no arbitrary HTML injection or cross-site writes.
Display actual errors/offline/manual/unknown status, not installed=working.
Root links /team from current approvals page and integrates optional CLI team commands.

## Response compatibility and receipt semantics

Strict whole-response JSON remains the default. A worker can explicitly opt into
`work_reply_header`: exactly `Here is the work reply:` at the beginning, followed
by a newline and a single strict versioned JSON object. Arbitrary prefixes,
Markdown fences, duplicate keys and trailing prose never trigger actions.
`evidence.core_result_sha256` pins the exact native UTF-8 text.

Bounded generated context prioritizes the recipient's oldest pending messages and
recent shared results. Only included recipient messages receive authenticated
acknowledgments; an acknowledgment proves receipt of context (which can be
truncated), not complete semantic reading or successful execution.
