# Optional local project-file search (E08.2, first slice)

This slice adds a disposable FTS5 cache, bounded source scanning and queries to
the existing authenticated `read_query` tool. It is **disabled by default**.
It does not change permissions, activate a service, or install a watcher.
The separate ThreadDesk search remains responsible for its own canonical data.

## Explicit operator configuration and use

An operator may add the following to a reviewed configuration. These are example
paths, not a command to change the running configuration. Apply configuration
through the existing policy activation procedure.

```toml
[file_index]
enabled = true
projects = { example = "/absolute/path/to/one/project" }
exclusions = ["private", "generated"]
```

The authenticated principal must already have **both** `file.read` and
`file.list`, and the configured directory must lie inside its existing file
roots. A project selector grants no authority. A `/` permission never becomes a
scan root. Explicit `/` and the user's home directory are rejected too.

```sh
kirabridge --config /path/to/reviewed.toml file-index status example
kirabridge --config /path/to/reviewed.toml file-index scan example --batches 100
kirabridge --config /path/to/reviewed.toml file-index search example orchid --limit 20 --pages 10
kirabridge --config /path/to/reviewed.toml file-index scan example --discard-cache --batches 100
```

`scan` reconciles create/update/rename/delete through a new bounded observation.
Each invocation starts a new observation; its `--batches` advance the same live
iterator. There is no persistent cross-process scan continuation. Interrupted
observations stay `building` and queries use a bounded source scan. Superseded
builders cannot prune or publish another builder's rows. `--restart` restarts an
observation in the same process. `--discard-cache` deletes only the four fixed
derived SQLite/journal filenames, after a local scope check. It never deletes
source files or the Bridge task database. No remote rebuild/reset tool exists.

Existing authenticated MCP clients can call the same dictionary-shaped tool:

```json
{"operation":"file.search","project":"example"}
{"operation":"file.search","project":"example","text":"orchid","limit":20}
```

The first returns status. A query returns current source hits, an opaque
`next_cursor`, `mode`, `index_status`, `generation`, `reasons`, and explicit
partial-result flags. Pass the cursor with the identical project/text/limit
through the same running service. Cursors are single-use, expire after five
minutes, and are discarded on process restart, policy/config/root binding or
cache-epoch changes. At most four query iterators and two scan iterators are
retained per service. CLI `--pages` handles continuation inside one invocation.

The small Python owner is `bridge.file_index`: `status(principal, project)`,
`scan(principal, project, restart=False)` and
`query(principal, project, text, limit=20, cursor=None)`. It holds configuration
and security references, not the entire Bridge or another module's database.

## What a result guarantees

Before each hit, the source layer re-fetches both existing capabilities and the
current loaded policy, configured root binding and exclusions. It uses the
existing descriptor-relative `PathScope` traversal with no symlink follows,
rejects hardlinks and nonregular files, and compares root, parent and leaf
identities and file metadata around the read. A changed authority/root/cache
generation at page completion discards the whole page. A cache row supplies
only a candidate path; the path, match and snippet are derived from a fresh
bounded UTF-8 source read. Cached text is never returned as a snippet. Results
include a file stamp, observed size and character offsets in that source text.
Snippets are plain strings of at most 240 characters, not HTML.

This is an observation, **not a filesystem snapshot**. Independent writers can
change a file after its check, or create a new matching file absent from an old
FTS observation. Every enabled query therefore returns `complete=false`,
`truncated=true`, and `filesystem_snapshot_unverified`, including at iterator
exhaustion. `reconciled_observation` means only that a bounded scan reached its
observed end and pruned old cache rows. It does not mean current or exhaustive.
`next_cursor=null` means observed iterator exhaustion, not proof of completeness.
`partial` denotes scan omissions such as unreadable or oversized sources/depth
limits; that status uses the bounded source fallback. Until a watcher exists,
operators must explicitly reconcile after edits; there is no automatic update
or freshness claim.

Queries accept 1–16 literal terms, at most 512 UTF-8 bytes, and limit 1–100.
C0, DEL and C1 controls are rejected. FTS5 uses quoted, bound literal AND terms;
the fallback uses case-insensitive literal substring AND. Both verify each hit
against current source text. Tokenization can differ between the two modes;
`match_semantics` reports which mode produced the page. There is no operator
language, normalization policy or ranking guarantee.

## Bounds, exclusions and failure behavior

Each call examines at most 500 entries/candidates and charges at most 8 MiB of
source reads (a failed attempted file reserves 1 MiB). Each file is at most
1 MiB; paths are at most 4096 UTF-8 bytes. Traversal opens at most 12 directory
levels. A 100 ms cooperative budget is checked between units of work; it is
not an OS deadline or a latency/SLO promise. SQL also has a progress budget.
Time/candidate/byte limits retain a continuation when possible. File and depth
omissions are reported rather than presented as complete results.

The separate owner-only cache is `file-index/content.sqlite3` under Bridge
state. Its database page limit is 1 GiB, not a disk-reservation or RSS guarantee.
An unsafe, missing-FTS or corrupt cache falls back to bounded source scanning.
No search failure writes canonical project files, tasks, approvals or backup
data. No index hook is placed on canonical Bridge saves. Windows has no secure
source adapter in this slice; disabling the feature leaves core work unchanged.

The scanner excludes Bridge state and its configured policy/credential files
even for full file grants, hidden paths,
common build/dependency/credential directories, key/database suffixes, and the
user's SSH/GPG/4AllPass/browser/keychain locations. Explicit relative exclusions
apply before traversal/read, including conservative case aliases. An explicit
text-extension allowlist defaults to source/document formats; binary/NUL and
invalid UTF-8 content are omitted. This is not a universal secret classifier:
operators must choose appropriate project roots and exclusions. It does not
invent team rights or protect against a privileged adversary or an OS user
already able to alter the Bridge process and its files.

## Deliberately unfinished E08.2 work

No filesystem watcher, change batching, overflow/restart event recovery, watcher
extra dependency, live activation, Windows acceptance, or 10k/100k Bridge
performance acceptance is included. A watchfiles Intel-wheel test was isolated
in private scratch; that proves only the tested package/platform combination,
not watcher integration. ThreadDesk measurements are not Bridge benchmarks.
The existing architecture record tracks this partial slice and its review.
