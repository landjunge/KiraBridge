# Agent CLI version inventory

`agent_inventory` probes the configured CLI executables and every executable
matching a known agent command name on the service's `PATH` with `--version`
(no shell, three-second timeout). It reports the resolved executable, observed
version, PATH search order, whether a matching CLI process is visible in the
terminal session catalog, adapter binding, and an explicit compatibility
status. Configured executable paths have priority over PATH discovery. Installed
commands without a configured adapter remain visible as unconfigured; their
compatibility is `unknown`.

The daemon repeats the read-only version probe at a 30-second interval while its
task workers are running. `agent_inventory`, `doctor`, and `status` also refresh
the observation on demand. Audit compares a sorted set of executable paths,
versions, and compatibility states per CLI, so changing probe order does not
look like an installation change. First observations and real set or
compatibility changes are recorded in the existing chained audit store as
`cli.version_observed`, `cli.version_changed`, or
`cli.compatibility_changed`. These are audit observations only: no team or
coordinator message is sent. Probe failures are reported as unknown; they do
not stop the bridge or block work.

A CLI version never blocks, gates, or marks a CLI `unsupported` (CLIs update
almost daily). Every CLI, including Qwen, reports compatibility `unknown` with
the observed version. Adapters check concrete capabilities at runtime instead
(Qwen ACP: agent name `qwen-code`, ACP `protocolVersion` 1, and `loadSession`
for resume). Capability routing records the observed `--version` line but no
longer requires it to equal the matrix version. The
inventory covers the known command registry plus configured executable paths;
it does not inspect arbitrary process command lines or infer a CLI from a
generic `node` process.
