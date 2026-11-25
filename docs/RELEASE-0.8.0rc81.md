# KiraBridge 0.8.0 RC81 — installer idle guard

Source-only release candidate. It has not been packaged, installed, published, or restarted.

RC81 corrects the installer busy check when the installer itself runs as an authorized
`terminal.visible` task. The Core runner passes the current task ID and principal to the child.
The installer excludes only that exact task after checking its live database row, running lease,
matching RUNNING event, principal, route, TTY and process identity. Other queued or active tasks,
receiver jobs and team jobs continue to block activation and rollback.

The Linux owned-PTY path waits at an internal start gate until the Core has persisted the process
and TTY evidence. If the evidence callback fails or is interrupted, the child is reaped before it
can execute. A Linux-host end-to-end run remains unverified on this Mac because no Linux VM is
available; the corresponding regression is included for Linux CI. Terminal.app-specific live
acceptance also remains separate from the local pseudo-terminal tests.

Targeted source regressions cover real Store transitions, lease and identity mismatches, process
and TTY ancestry, restart recovery to UNKNOWN without replay, and rollback refusal while other
work remains active. These tests do not certify a production installation.
