# Claude subscription text review profile

This opt-in adapter extends the existing `bigplan-delegate` starter. It permits
only `opus` (a CLI alias), `xhigh`, and read-only tasks. Source material must be
self-contained in the bounded task prompt: no built-in tools, MCP tools, skills,
session resume or subdelegation are enabled. It does not add a bridge, queue,
managed AgentManager route or production profile. Codex/Grok adapters are retained.

Before every plan/start, the existing hook rereads the canonical matrix and checks
the exact CLI version. The Claude reader additionally requires successful
`auth status --json`, `loggedIn:true`, `authMethod:claude.ai`, `apiProvider:firstParty`
and a subscription plan. Identity/token fields are neither returned nor logged.
Only basic OS environment keys pass to Claude, preserving the same HOME/keychain
login and excluding inherited API/provider/model/effort overrides.

The session uses `--restricted --safe-mode`, plan permissions, empty built-in tools,
strict empty MCP configuration plus MCP deny, disabled slash commands, no session
persistence and one agentic turn. Per-session `switchModelsOnFlag:false` ends a
flagged request rather than opting into model fallback. Managed policy remains
binding; these flags do not attest that no managed hooks exist or that an effort
cap is absent. `--bare` is deliberately excluded: installed2.1.322 help states that
it disables OAuth/keychain and requires API credentials.

The official [model contract](https://code.claude.com/docs/en/model-config) documents
`xhigh` for current Opus5.5/5/4.8/4.7, and distinguishes Opus4.6. The installed CLI
advertises `opus` and `xhigh`; the
[effort reference](https://platform.claude.com/docs/en/build-with-claude/effort)
independently lists Opus support. This is a documented alias/effort request, not a
provider model-ID, entitlement or effective-effort attestation. Managed limits can
cap effort; output remains unverified until separately assessed. Native remaining
quota was unavailable; the user's budget report remains attributed to the user.
Flags follow the [CLI reference](https://code.claude.com/docs/en/cli-reference).

Planning is the existing default (no `--execute`), with metadata probes only and no
receipt/model effect. A later explicitly assigned start uses the same existing
admission receipt, fsync, matrix recheck, bounded process runner, output files and
no-replay behavior. `process_completed` means transport completion, not accepted
review, provider identity, Core/Team completion or ACK. Root must inspect the owned
native result and process the result/receipt; no automatic acceptance is added.
UNKNOWN must reconcile its original task ID, never spawn a replacement.
