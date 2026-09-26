# Runtime diagnostics, indexing throughput and shutdown

ragdbman overlaps extraction and network work while retaining one mutating job and
one serialized indexing writer per collection. Tuning should follow measurements
on the actual corpus and embedding/converter installation, not a fixed promised
speedup.

## Logging

```sh
uv run ragdbman serve --log-level debug
uv run ragdbman serve --log-level trace
RAGDBMAN_LOG=verbose uv run ragdbman serve
```

All CLI subcommands accept `--log-level`. Precedence is explicit CLI option,
environment, then TOML `[logging] level`. Effective levels:

| Level | Output |
| --- | --- |
| TRACE (5) | Queue offsets, reader-connection reuse and vocabulary batch/select/link counts, plus higher levels |
| DEBUG (10) | Source stages/timings, chunk counts, model/dimension/batch information, queue wait, SQLite opens/commits and converter lifecycle |
| VERBOSE (15) | Per-file indexed/skipped outcomes and elapsed time |
| INFO (20) | Engine/job lifecycle, discovery totals, periodic progress and final counters |
| WARNING (30) | Extraction fallback/warning summaries, failed scan items, interrupted converters and signals |
| ERROR (40) | Individual indexing/provider failures |
| CRITICAL (50) | Forced shutdown when graceful cleanup cannot finish |

`warn` aliases `warning`. A pre-existing logging handler no longer prevents
DEBUG output: application/root levels and handler thresholds are configured
explicitly. Uvicorn uses the effective level without replacing that configuration.
INFO progress is emitted every `defaults.scan_batch_size` processed files and
at the final count.

Logs include timestamps and thread names, with collection/job/source identifiers
where applicable. They do not intentionally print embedding vectors, input texts,
raw tool arguments or authorization headers. HTTP transport logging is quiet and
MCP SDK raw-payload DEBUG is disabled even at application TRACE. Source paths and
upstream converter error messages may still expose sensitive information, so
keep diagnostic captures private and inspect them before sharing.

## File and embedding concurrency

Merge settings into existing TOML sections; do not repeat section headers:

```toml
[defaults]
max_concurrent_files = 4
scan_batch_size = 100

[ollama]
max_concurrent_embedding_requests = 4
embedding_batch_size = 32
```

`max_concurrent_files` bounds active pipelines per collection, with a fixed number
of worker tasks rather than one task for every discovered path. The Ollama
semaphore bounds HTTP requests across all collections using that engine. Both
limits accept 1–32; four is the starting default. Existing explicit values of
one remain in effect. Use 4–8 only if memory, converter CPU usage and model
capacity permit; more concurrency is not inherently faster.

Optional PyMuPDF parsing remains serialized because its native state is not
thread-safe. Other files can still overlap extraction, embedding and queued
SQLite writes. Canonical path duplicates are deduplicated before indexing.
Files may complete out of discovery order. For conflicting Knowledge Card IDs,
the first committed source owns the ID; later conflicts fail without overwriting it.

## SQLite and vocabulary operations

- A persistent writer connection/executor serializes indexing/status/job writes.
- Stable collection settings are captured once per scan rather than recounting
  all sources/chunks for every file. Canonical-path deduplication runs off-loop.
- Separate, exclusively leased read/control connections preserve responsive
  overview/search access and avoid sharing transaction state between callers.
  At most eight idle reader connections are cached per collection; additional
  concurrently leased readers close when returned. Startup/creation and diagnostics
  can still use short-lived connections.
- Connections are closed during graceful engine shutdown and before collection
  deletion. A leased reader is not closed underneath an active read.
- Vocabulary lookup uses `WHERE canonical_form IN (...)`, split into batches of
  at most 800 terms. Missing vocabulary rows and chunk links use `executemany`.
- Keyword frequencies refresh once after all file workers and optional pruning
  finish, including partial work on cancellation/failure. They can be temporarily
  stale during a running scan, but term links are committed atomically with each
  source and remain queryable. Interrupted-job recovery refreshes counts.
- Standalone file add/remove still refresh immediately. Rebuild first clears the
  vocabulary with its index, then performs one final scan refresh.
- The keyword-ID index supports count lookups. Short source transactions retain
  rollback and source-version semantics; previously successful commits are not
  rolled back merely because a later file or the overall job is cancelled.

`db.connect()` sets WAL and `PRAGMA synchronous=NORMAL` on persistent databases.
NORMAL with WAL preserves consistency, but a power loss or OS crash can roll back
recent committed transactions; it is not FULL-level durability. Application
crashes are distinct from power/system failures ([SQLite PRAGMA documentation](https://www.sqlite.org/pragma.html)).
Back up databases and original sources, especially before maintenance. NORMAL is
not OFF and does not eliminate all synchronization/checkpoint I/O.

## Ctrl+C and termination

```toml
[server]
shutdown_grace_seconds = 5
shutdown_timeout_seconds = 30
```

Both are positive finite durations; the overall timeout must exceed request grace.
On the first SIGINT/Ctrl+C or SIGTERM:

- New mutations are rejected.
- Active scan/standalone indexing tasks receive cancellation and stop flags.
- Owned converter process groups are terminated immediately.
- SSE progress streams stop rather than keeping Uvicorn's request drain alive.
- Child file tasks and database writers finish cancellation cleanup before
  collection ownership is released.
- Job state is persisted for explicit resume, keyword counts are reconciled,
  HTTP/model clients and pooled database connections are closed.

Converter cleanup kills the POSIX process group even if its initial parent has
already exited. This addresses descendants retaining inherited stdout/stderr
pipes. Spawn cancellation is shielded long enough to obtain and clean up the
new process instead of losing ownership in the spawn race.

Uvicorn bounds request draining by `shutdown_grace_seconds`. Python cannot safely
kill arbitrary threads executing native code or blocked filesystem calls.
Therefore the CLI also has a watchdog: a second signal, or expiry of the overall
deadline, terminates remaining owned converter groups and exits the process.
This is an emergency path, not graceful completion. Uncommitted SQL transactions
are recovered/rolled back; unfinished jobs require explicit resume, and converter
scratch files may remain. Do not assume in-flight work was indexed successfully.

The deadline applies to `ragdbman serve`/the bundled launcher, not arbitrary
third-party ASGI hosting or callers using `Engine` directly. Programmatic
`Engine.close()` retains the safe drain-before-release contract. Process-group
behavior is verified on Linux/POSIX; intentionally detached services/remote
model servers are not killed, and Windows descendant cleanup has not been
certified. Only ragdbman's registered converter groups are targeted.

## Reproduce the performance fixture

```sh
uv run python tools/benchmark_indexing.py
```

The script compares per-term reference lookup with batched vocabulary operations
for 20,000 chunk-term links and 200 unique terms. It separately compares serial
and four-way scans of 32 generated sources using deterministic embeddings with
40 ms simulated latency. It reports timings and SELECT counts; it does not
download or evaluate a real model. See the verification record for observed runs.
Real source sizes, tokenizer/converter costs, GPU scheduling, disk performance
and cache state can dominate throughput. A universal 10–50× speedup is not claimed.
