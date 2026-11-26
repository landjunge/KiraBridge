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
`cli.compatibility_changed`. Only the current observation is sent once to the
current team coordinator as a deduplicated `result` when the authenticated
inventory caller has a writable team route. Probe failures are reported as
unknown; they do not stop the bridge or block work.

Qwen ACP currently declares only `0.27.2` and `0.27.3` supported. A detected
`0.28.0` therefore reports `unsupported` with the adapter reason; this change
does not claim compatibility or enable the version. Other adapters report
`unknown` until they have an explicit version compatibility policy. The
inventory covers the known command registry plus configured executable paths;
it does not inspect arbitrary process command lines or infer a CLI from a
generic `node` process.
