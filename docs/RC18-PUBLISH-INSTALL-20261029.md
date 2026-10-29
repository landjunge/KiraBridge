# RC18 publication and controlled installation · 29 October 2026

The request is dated29October; final documentation continued30October Europe/Berlin.
Runtime/publication timestamps below are UTC.

Request **rc18_release_install_20261029** expressly approved PR49→50→52 integration,
publication and controlled productive installation with backup/risk notice first.

**Published and installed:** [v0.8.0rc18](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc18).
The exact published Intel archive is installed; current PID**18197**, instance
82cd506b1d854b50b4cc58c5016fc856. **Issue51 remains OPEN**: its complete repeatable
ready-Codex takeover criterion is not established by the shell/protocol acceptance.
[Machine-readable evidence](evidence/rc18-published-installed-20261029.json).

## Integration, artifact and version history

| PR | Normal merge into main |
| --- | --- |
| [49](https://github.com/landjunge/KiraBridge/pull/49) | fa22b539707c57c2e016cc5d869ea5599d97f846 |
| [50](https://github.com/landjunge/KiraBridge/pull/50) | c0100d31bc1e75815a1920d33ab0e0371d108d5e |
| [52](https://github.com/landjunge/KiraBridge/pull/52) | 351944222c964139f09956177cac0252d52aa8bc |

PR50 and52 were retargeted to main in order; remaining intended commits and exact
heads were checked before merging. Normal ancestry retained, no branch deletion,
no --admin/protection bypass, no old productive checkout changed.
Main3519442 equals the accepted57b0fd2 tree. Artifact source
**15d071ebaa95d3bef2eed506c21fe7bfd043464c** is its ancestor; subsequent source differences
are README/evidence only. No duplicate runtime, adapter or installer implementation.
The immutable RC18 source/tag/assets are retained; follow-up documentation does not
silently rebuild/replace them. All9 older releases/assets remain unchanged, including
the separately authenticated RC17 draft. Every original older wheel was downloaded
and matched earlier; publication does not change repository privacy.

## Actual published download and reproducibility

Publication observed2026-10-29T22:20:00Z, isDraft=false, prerelease=true,
versioned tag points to15d071e. All31 original assets were actually downloaded and
matched to GitHub digests. The exact README command then passed another isolated
RC17→RC18→RC17 acceptance from the published release, including an open MCP read;
its own testservice was independently removed (113). No simulated download.

| Artifact | SHA256 |
| --- | --- |
| KiraBridge-macos.tar.gz | 8ec622ca2c6a3ff621c017d55c0f4648d55a738929b5b5be80960778637a388d |
| kirabridge-0.8.0rc18-py3-none-any.whl | a3d66f885da27b76cee5ed05b3976d4dd11c7af70a71f2d43a2d6ef4a112d24c |
| install-macos.sh | 13b9ce3064a66c1ffaaae933a039b463c2cc08915e94c15e7e564e243af07249 |

Earlier exact-source double build was byte-identical,387 manifest files and122 wheel
Python files checked. Actual host: iMac17,1/Intel2015, macOS15.7.4/24G517,
Python3.11.15, uv0.11.6. Full Intel suite1842passed/1skipped, the optional AA reader
separately1passed; real pinned ThreadDesk/TollGate contracts included. Accepted
head57b0fd2 Linux Verify40961821427 passed1826/17 on both Python axes. These prior
runs are not relabelled as new whole-suite runs. [Full build history](INTEL-RELEASE-20261029.md).

## Backup and recoverability before switching

Private0700 root:
`~/.local/share/kirabridge/backups/rc18-release-install-20261029`.
Before edits:18 file hashes reread, full Git bundle verified, consistent SQLite
integrity_check=ok, source archives/patches, config/credential/plist copies and
preexisting PR/release/issue metadata. Immediate pre-switch and pre-lifecycle SQLite
backups were separately consistent. RC17 source583 files were privately restored
and compared byte/Git-mode correct; its actual venv was copied with symlinks retained,
1550 stable environment files compared. Existing original runtime paths remain.
No productive database restore occurred.

The actual RC17 plist ran the managed-message-route worktree; historical installer
current.json referenced fde9d87. Both actual definitions and metadata were preserved
without rewriting away the difference. New installer transaction:
`~/.local/share/kirabridge/install/backups/20261029-233225-bdaf86ef`.
Its saved actual plist and launcher independently match the pre-install originals.
Config/credentials and all3 historical protected message/job records, holds and
withdrawals remain unchanged. Actual config/effective hashes remain
52747b8353bef4cc162997c34c30d8e759ca0691725d902f313ce4653cf903c2 /
3709ee5e48b675813b9708c7b634d137ca3c2c2dc19fefd35a04b61f581cf641.

Risk/resume report was saved before switching, and an authenticated explicit partial
answer c078e692-c076-4f50-865a-aec58b15c642 warned about HTTP/MCP interruption. That
answer was not called project completion. The original RC17 session.input task had
already become unknown/visible_reply_unknown; confirmed input and unconfirmed reply
are separate evidence. It changed to unknown about**300.014 seconds** after started,
with handoff reason reply_unconfirmed, before RC18 installation. This task was
neither edited nor retried. No CWD cause or diagnostic-budget causality is invented.

## Actual visible productive installation and service tests

Exactly one new owned native Terminal window/tab3538, tty004, shell12790/login12788
was opened through the existing authorized session.open path. macOS grouped it with
other native windows; only its exact tab/TTY received input. Existing Codex processes
71896/90216 and their shells, plus the two other initial shells, remain alive.
The initial current Codex tab and every other session received no test input.

The versioned published command ran with --require-visible-terminal and explicit
original productive paths, reduced motion, existing configuration and credentials.
Its local driver waited until its starter transport task was durably completed,
then used the existing installer. No active work was force-cleared to pass idle.
Installation reached authenticated0.8.0rc18/PID14881 at22:32:32Z. All122 actual
installed Python files match the published wheel; startup source SHA
bea0158935efd09a2304be2eb024ce79d5a100cf754742dcbe52aaddce1dc9ee.

| Productive operation | Actual result |
| --- | --- |
| Initial installation/start | RC18/PID14881 healthy, config/credentials preserved |
| Controlled stop/start | label absent113, old PID gone, HTTP endpoint closed; healthy PID18176 |
| Guarded restart via existing stop/bootstrap | same absence/process/endpoint evidence; healthy PID18197 |
| After owned-window closure | MCP still answers from PID18197; same source/config hashes |

Before each stop the existing ownership, visible-terminal and transactional idle
guards ran; SQLite writer reservation was released before startup. No live crash/
SIGKILL test was performed; isolated KeepAlive/crash acceptance remains its own evidence.
There was no critical product failure and no productive rollback was necessary.
The first local lifecycle controller missed its bundle argument and aborted before
any service action. Its traceback is retained; only the corrected v2 lifecycle was
rerun. That setup failure is not counted as a successful first test.

## Live functional acceptance and boundaries

- New tasks rc18-installed-input-round1/round2-20261029 each pasted/submitted once
  in the owned empty shell and produced exactly one file receipt. SHA256 of the
  two receipt lines: 1d7a2f83f457f8efeb11ae73b3cba28858ab96bacf08b9bac16ecd3b8f1909ca.
- Same successful ID/key returned original completed state/receipt/attempt1;
  round2 was repeated after the real restart and produced no third receipt.
- Bounded owned busy fixture had a positively identified live Python child. New
  busy input failed session_busy in about1.3s, started=null and
  terminal_input_attempted=false. No queued input executed when the fixture ended.
  The same failed ID after readiness stayed failed/attempt1, without a new input.
- Wrong PID1 on the owned pane failed session_selection_changed before input;
  no effect file. No input was directed to another agent for these negative tests.
- All original tabs read without focusing them. Parallel reads initially returned
  terminal_read_busy for3 calls under the one-slot read limit; those affected reads
  then passed sequentially. The current own Codex read correctly reported working /
  current_progress_row with an empty widget; it was not labelled ready.
- Actual HTTP MCP initialize/tools/health/catalog/read succeeded with the existing
  ChatGPT credentials after restart:67 discovered tools, principalchatgpt, RC18.
  This is an actual loopback protocol test; browser/Live/voice Host attestation remains
  unverified, as reported by the server. Tokens were never printed or forwarded.
- Diagnostic observer still reports budget_exhausted at2000/day. Primary durable
  task/receipt/events are exported; no claim of complete new observer diagnostics,
  no raised quota or deleted history, no asserted causal link to old handoff failures.

The full owned terminal scrollback is preserved privately (6261 bytes; SHA
390c0b62c302df83a0578eb977a83200f323c5f5ec38465dba120c70e42faba4).
Cleanup first refused an over-strict process count including the normal root login;
the exact recorded login/shell pair was then checked. Tab.close was unsupported
(-1708), independently observed unchanged. The native window contained only owned
tty004, so its supported window close was used. Independent absence of3538 and
presence of all4 preexisting native windows/6 processes were verified.

## Rollback and next safe test

Use the retained verified bundle's installer rollback command only for the matching
owned transaction, in a confirmed owned visible window. It checks current definition
hashes, idle work, queue compatibility and saved actual definitions before restoring.
Do not restore an old database over new results, change OS rights, kill agents or
replay unknown work. Success requires a responding prior RC17 plus preserved data.
RC17 isolated rollback was actually proven; saved productive definitions were compared,
but a productive rollback was not performed because RC18 remained healthy.

[Issue51](https://github.com/landjunge/KiraBridge/issues/51) remains open. It requires
repeatable delivery into an actually ready visible Codex, automatic Return and an
authenticated Codex takeover without manual Return, plus concurrent/stale/limit
regressions. The running orchestrator cannot simultaneously be its own ready target;
other existing Codex sessions were not commandeered. Next safe test after this turn:
from the actual requesting ChatGPT context, first confirm intended Codex tab3033/
TTY001/shell70676/agent71896 is current and ready, then use fresh short test IDs,
observe exact once-only ACK/reply and the repeated same-ID read. Never retry the
historical unknown entries to supply this evidence. Close51 only if its full criteria
actually pass. The actual ChatGPT Host/voice check remains separately observable.

## Masterplan and deferred platforms

Existing KB-INTEL-20261029 delta updated in place: merge/publication/controlled
installation DONE; ready-Codex issue51 and actual Host attestation OPEN; ARM and paid
hostedMac DEFERRED. HostedMac jobs that start0steps are not passed checks; no manual
paid rerun/dispatch or billing/visibility change. Historical reports and the canonical
Whiteboard188ce4729a62 retain their chronology. No new competing plan/Whiteboard,
extra agent assignment or duplicate integration route.
