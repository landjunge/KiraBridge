# Native Claude review: triage and narrow source correction

The first assigned substantive review was one native Claude session
`943f3f79-6cf5-4185-a072-59ec2c560bab`: successful transport/end_turn, one turn,
CLI-reported `claude-opus-5-5`/firstParty. The requested effort was xhigh; effective
effort and remaining quota were not independently attested. Native costBasis=list
is not a bill. The earlier V1 administrative HOLD came from the pending-assignment
preamble, not failed authentication. Neither original task/result is rewritten.
Pure original review: Server Library `eed4a3bd1274`, SHA
`8cd5e884fb9e64c6ce354a4154f3cabc79f3798ad59c06028dc994a3a77dab7d`.
Sanitized metadata: `3d83259b25aa`, SHA
`ab8210b7aff2766d7dd0c9d32126d4cb7a60703eafe629f4b741ec5bad7d8712`.

The reviewer explicitly lacked router validators, evidence parsing and the process
runner. Its nine findings therefore require the full-source distinctions below.

| # | Full-source verdict | Action |
|---|---|---|
| 1 | Unmanaged workspace/user hook or CLAUDE.md execution is **not demonstrated**. The documented restricted/safe-mode flags exclude these settings/customizations. Managed policy remains active by design. Metadata probes did not carry the same flags. | Align Claude metadata probes with the run's flags; explicitly select no user/project/local settings sources. No new real session or hook-execution test. No claim that managed hooks are absent; no neutral-cwd redesign. |
| 2 | Confirmed public Python API bypass; predates the Claude adapter. `execute=True, probe=False` could reach the runner without current native checks. | Reject that combination before any admission or runner call. Static no-effect planning may still disable probes. |
| 3 | Confirmed pre-existing receipt/lease classification bugs. RoutingError/FileExistsError after the runner boundary could become blocked; BaseException could leave admitted evidence and release a live writer's lease. The old runner also failed to clean its own child on interrupt. | Track boundary and confirmed exit separately. Post-boundary errors become UNKNOWN; original IDs are never replayed. Preserve a write lease until non-start or confirmed exit. Persist before propagating cancellation. Narrow lease-open conflict handling. Bound cleanup/reap of the newly owned child. |
| 4 | False positive for the CLI/validated Task contract: `task_id` already uses strict `^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$`. Five traversal/empty-ID controls pass on the original. Trusted Python callers bypassing Pydantic are not an untrusted-data boundary. | No redundant task-schema rewrite. Secure file creation also refuses planted output/temp entries. |
| 5 | Real account-subject limitation, not an adapter-executed account switch. The contract checks subscription route/type; it does not pin an individual account/org. This is shared pre-existing behavior, not a new credential leak. | Document exactly what is checked. A separate subject-pinning contract would require an authorized fresh identity observation; no account/API/login action is introduced here. |
| 6 | Confirmed Claude-specific regression: the new allowlist dropped privacy, egress-proxy and CA settings. This proves lost configuration, not observed network exfiltration or an actual update. | Keep proxy/CA policy, force updater/telemetry/error/nonessential traffic off for this child only, and test the actual environment passed to probes/runner. No global settings write. |
| 7 | Confirmed pre-existing path and freshness gaps; the Task validator does not resolve them. Runtime executable authenticity is a trusted-operator assumption, not cryptographic publisher attestation. | Pin resolved executable/cwd for execution, reject changed targets, recheck unchanged matrix/runtime fingerprints and current evidence validity before the runner. This is not an absolute CAS against arbitrary same-user editors. |
| 8 | Confirmed pre-existing pre-try failure gap. Root changes or directory sync errors could strand admitted receipts; pre-run source OSError was incorrectly UNKNOWN. | Validate roots before admission. Failed admission remains no-process evidence with its original ID; pre-run guard failures are blocked, never invented starts. Retain the original receipt if persistence itself fails. |
| 9 | Confirmed private-directory, symlink/window and final-file-fsync issues. Darwin power-loss/media durability was an inference, not an observed replay. | Require an existing owned private non-symlink state directory. Create outputs/temp exclusively with0600/NOFOLLOW and fsync, then replace only the owned receipt and sync its directory. No claim of universal hardware power-loss durability or automatic retry is made. |

The original isolated regression run had15 failing cases and five passing Task-ID
controls. Later tests also cover real owned Python-child interrupt cleanup; no
Claude/Auth/model call is used for correction testing. Codex/Grok command adapters
and their credentials remain unchanged; the shared receipt/runner fixes protect
their existing boundary rather than redesigning the eight CLI modules.

Policy sources (read this phase): [CLI restrictions and safe mode](https://code.claude.com/docs/en/cli-reference),
[environment/privacy controls](https://code.claude.com/docs/en/env-vars),
[settings precedence](https://code.claude.com/docs/en/settings). The documented
`switchModelsOnFlag:false` contract is retained; it was not an invented setting.
The source correction is not deployed and does not rerun either native review.
