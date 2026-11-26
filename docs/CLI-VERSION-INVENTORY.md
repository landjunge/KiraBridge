# Agent CLI version inventory

`agent_inventory` probes the configured CLI executables and known agent command
names on `PATH` with `--version` (no shell, three-second timeout). It reports
the resolved executable, observed version, whether a matching CLI process is
visible in the terminal session catalog, adapter binding, and an explicit
compatibility status. Installed commands without a configured adapter remain
visible as unconfigured; their compatibility is `unknown`.

The daemon repeats the read-only version probe at a 30-second interval while its
task workers are running. `agent_inventory`, `doctor`, and `status` also refresh
the observation on demand. First observations and version, path, or compatibility changes are
recorded in the existing chained audit store as `cli.version_observed`,
`cli.version_changed`, or `cli.compatibility_changed`. Unsupported versions
and later changes are sent as a deduplicated `result` to the current team
coordinator when the authenticated inventory caller has a writable team route. Probe failures
are reported as unknown; they do not stop the bridge or block work.

Qwen ACP currently declares only `0.27.2` and `0.27.3` supported. A detected
`0.28.0` therefore reports `unsupported` with the adapter reason; this change
does not claim compatibility or enable the version. Other adapters report
`unknown` until they have an explicit version compatibility policy. The
inventory covers the known command registry plus configured executable paths;
it does not inspect arbitrary process command lines or infer a CLI from a
generic `node` process.
