# Claude subscription text review profile

This opt-in adapter extends the existing `bigplan-delegate` starter. It permits
only `opus` (a CLI alias), `xhigh`, and read-only tasks. Source material must be
self-contained in the bounded task prompt: no built-in tools, MCP tools, skills,
session resume or subdelegation are enabled. It does not add a bridge, queue,
managed AgentManager route or production profile. Codex/Grok adapters are retained.

Before execution (and normal probed plans), the hook rereads the matrix and checks
the exact CLI version. The Claude reader additionally requires successful
`auth status --json`, `loggedIn:true`, `authMethod:claude.ai`, `apiProvider:firstParty`
and a subscription plan. Identity/token fields are neither returned nor logged.
Basic OS and egress proxy/CA policy pass to Claude, preserving the same HOME/keychain
login and excluding inherited API/provider/model/effort overrides. Updater,
telemetry, error reporting and nonessential traffic are disabled for this child.
Metadata probes use the run's restricted/safe-mode and empty settings-source flags.

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

Execution cannot disable native probes. Static no-effect plans may skip them.
Resolved paths and evidence expiry are rechecked at the runner boundary.
Planning is the existing default (no `--execute`), with metadata probes only and no
receipt/model effect. A later explicitly assigned start uses the same existing
admission receipt, fsync, matrix recheck, bounded process runner, output files and
no-replay behavior. `process_completed` means transport completion, not accepted
review, provider identity, Core/Team completion or ACK. Root must inspect the owned
native result and process the result/receipt; no automatic acceptance is added.
UNKNOWN must reconcile its original task ID, never spawn a replacement.

The authentication check confirms route/type, not an account/org fingerprint.
The adapter never logs in, selects another account or falls back to an API key;
an external same-kind account switch is outside this attestation. Post-run
processing failures remain UNKNOWN; known pre-run failures are blocked/no-process.
Write leases remain until non-start or confirmed exit. Cancellation is recorded
before propagation and own-child cleanup/reap is bounded. Result creation uses
exclusive0600/NOFOLLOW, then file/directory fsync; power-loss guarantees remain
filesystem/platform dependent. See [native triage](CLAUDE-NATIVE-REVIEW-TRIAGE-20261116.md).
