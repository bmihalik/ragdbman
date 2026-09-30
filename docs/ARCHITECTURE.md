# Architecture

## MCP capability boundary

`CorpusMCP` in `mcp_server.py` subclasses FastMCP and removes unused
prompt/resource handlers immediately after the SDK's normal handler setup.
Both operational and administrative profiles use this factory. Initialization
therefore omits these capabilities, while unsupported protocol methods return
Method Not Found instead of an empty catalog. Tool registration and authorization
are unchanged.

The `_setup_handlers` hook and low-level handler map are a deliberately small
private-SDK compatibility boundary. The dependency is `mcp>=1.30.0,<2`, with
1.30.0 locked, and wire-level regression tests cover both profiles. Future SDK
updates must rerun discovery and teardown tests; ragdbman does not monkeypatch
the SDK transport or silence its error logger.

The MCP boundary is implemented in `mcp_server.py`, with read-only contracts in
`corpus.py` and discriminated management actions in `corpus_admin.py`. Query and
admin transports use separate tool registries/session managers and share
server-side authentication in `web.py`; the query registry never contains a
mutation tool. Credential enforcement covers administrative REST/UI routes as
well as MCP. See [MCP.md](MCP.md) for scope and authorization details.

The Python service is organized around a shared `Engine`. Transport code validates requests and delegates; indexing and search are not separately implemented for the browser and AI clients.

## Module map

| Responsibility | Python module |
|---|---|
| Configuration and domain models | `config.py`, `models.py`, `errors.py`, `diagnostics.py` |
| Persistence | `db.py`, `schema.sql`, collection lifecycle in `engine.py` |
| Embedding provider | `ollama.py` |
| Tokenization and chunking | `chunking.py` |
| Document extraction | `extract/` |
| Facts and keywords | `metadata.py` |
| Scanning and indexing | `scanner.py`, extraction dispatcher, indexing/jobs in `engine.py` |
| Retrieval | `search.py` |
| Deterministic raw/LLM presentation | `formatting.py`, request format selection in shared services |
| Source syntax graphs | `graph/parser.py`, `graph/store.py`, `graph/query.py`, `graph/schema.sql` |
| Shared application engine | `engine.py` |
| Blocking-work isolation and cancellation cleanup | `workers.py` |
| MCP interface | `mcp_server.py` |
| REST and administrative UI | `web.py`, `static/` |
| Command-line interface | `cli.py`, `cli_commands.py`, `cli_signals.py`, `process_lock.py`, `__main__.py` |

## Ingestion path

1. Resolve the collection, canonicalize the source, enforce the allowlist and size limit.
2. Hash the file and compare with the existing source's indexed hash and status.
3. Extract directly or create a collection-appropriate Markdown sidecar.
4. Resolve the collection model's tokenizer, create structure-aware chunks and metadata.
5. Embed via batched Ollama calls outside any SQLite write transaction.
6. Verify count/dimensions, check cancellation, and verify the source did not change during processing.
7. In one transaction, replace old chunks/FTS/vectors/facts, persist artifacts and a source version, and mark the source indexed.

For source-code collections, Tree-sitter observations and AST boundaries are
prepared off the HTTP event loop before embedding. The primary source transaction
also writes a graph outbox event; after commit it is applied idempotently to the
separate graph SQLite DB. Reads validate source hash/status and parser fingerprint,
and resolve current chunk citations dynamically. Unchanged-file scans can backfill
graphs without embedding. Graph writes are derived and retryable; their failure
does not roll back an already committed document index. See [SOURCE_GRAPH.md](SOURCE_GRAPH.md).

Failed processing records a durable error and marks the source failed. A later scan retries it even when its content hash has not changed.

## Storage and initialization

`schema.sql` defines the complete collection schema, including collection kinds, line positions, Markdown paths, percentage positions, and an internal-content FTS5 index. `db.initialize_schema` creates missing tables and seeds built-in metadata fields idempotently; the vector table is created once the embedding dimensions are known.

Source and chunk tables are authoritative, and indexing keeps their FTS and vector records consistent within a transaction. Normal restarts leave stored source IDs, chunk IDs, embeddings, and search results intact; tests cover both fresh initialization and reopening populated databases.

Collections keep one lazy writer connection on a dedicated single-thread executor
and exclusively lease reusable read/control connections (up to eight cached idle
readers). A single shared connection across readers and writers would break
isolation or block live UI reads. Connections load sqlite-vec once and use foreign
keys, WAL, `synchronous=NORMAL` and a busy timeout. Long conversion/network work
occurs outside transactions. `connections.py` handles lifecycle and lease cleanup.
Do not run multiple daemons on the same data directory; locks are not distributed.

CLI/serve hold OS advisory ownership locks for both data directory and registry
before constructing an engine. Daemon-mode CLI calls existing REST endpoints
without opening SQLite or performing startup recovery. Direct scan/rebuild/resume
commands keep one event loop alive until the owned job stops, then close it.
Embedded owners can use `DataDirectoryLock` explicitly. This rejects competing
owners; it does not enable parallel daemon processes or distributed workers.

## PDF dependency boundary

pypdf is the built-in base dependency. The default PDF route tries configured
external MinerU/Marker executables and then pypdf/raw recovery. Explicit `pypdf`
selection bypasses both external tools; neither route imports PyMuPDF.
PyMuPDF is a separate extra with a lazy import reachable only through explicit
`pymupdf` selection. MinerU is never imported or installed into the ragdbman
environment by the package; its adapter executes the configured program and
consumes Markdown/images from temporary output. See `PDF_BACKENDS.md`.

## Concurrency and recovery

The HTTP event loop handles job coordination and Ollama network requests.
Extraction runs on a worker-owned event loop, isolating synchronous parsing,
sidecar writes and converter-output processing from HTTP navigation. Shared
Ollama clients and collection locks stay on the main loop; they are never passed
to converter event loops. Optional PyMuPDF extraction is serialized within an
Engine because of its native process-global state.

Hashing and tokenizer/chunking run in worker threads. Index/status/job writes and
pruning are serialized by the persistent collection writer; metadata preparation
occurs outside its write transaction. Vocabulary lookups use bounded IN batches
and bulk inserts; a keyword-ID index supports frequency refreshes. Refresh runs
once when a scan ends, including partially completed scans, and during recovery
of interrupted jobs; standalone add/remove operations refresh immediately.
Threads isolate blocking work, not machine
resource usage: large jobs can still compete for CPU, memory and disk. Large
searches and explicit maintenance operations still need scale-focused profiling.

One mutating job owns each collection; it runs a bounded TaskGroup of file
pipelines with a semaphore. A repeated start-scan call returns the active scan.
Distinct canonical paths may complete out of input order. Thread-safe cancellation flags are checked during index
writes and before commit, so cancelled writes roll back. Cancellation waits for
worker cleanup before releasing the collection lock; it cannot leave a detached
writer modifying a collection after shutdown or deletion.

Interrupted jobs are paused at startup and require explicit resume; successful
source hashes make replay incremental. Shutdown cancellation is forwarded to the
converter's event loop, and converter processes are terminated as a group on
POSIX, even when the immediate parent has exited and descendants retain pipes.
Cancel propagates to active file tasks and drains worker cleanup; commits already
completed remain intact. The CLI's ManagedServer begins cancellation at signal
receipt before Uvicorn waits for HTTP streams, and applies a final process-exit
deadline for non-cooperative threads. See [RUNTIME.md](RUNTIME.md).
The overview's Ollama health probe has a three-second
deadline, including time waiting for an embedding request slot.

## Retrieval path

Format selection happens in the shared service rather than in a client.
REST/Python request models default to raw dictionaries; MCP query defaults and
its specialized graph request default to readable strings. The MCP adapter
emits either structured JSON or text-only content, while REST converts strings
to UTF-8 plain-text responses. Formatting does not call retrieval again or
perform summarization. See [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).

Structured predicates narrow eligible chunk IDs. FTS5 supplies keyword ranks; sqlite-vec supplies exact vector distances. Hybrid fusion combines channel ranks, and multi-collection fusion combines independent collection ranks. Results include evidence and filter diagnostics rather than synthesized answers.

Exact vector evaluation avoids returning too few matches because a selective filter was applied after a small KNN candidate set. This trades throughput for completeness and should be benchmarked before very large deployments.

Source-code search enrichment and `corpus_graph` use read snapshots and bounded
traversal in worker threads. They do not parse or flush pending writes. Scores
and search ordering remain unchanged, and graph failure preserves normal hits.

## Extension points

- Implement the async `Embedder` protocol for another real embedding provider.
- Add format adapters returning `Document` and `Block` records, then register the extension dispatch.
- Keep new retrieval strategies behind the shared search/engine interface.
- Keep schema definitions complete, and test fresh initialization, repeated initialization, and persistence across restarts.
- Knowledge Cards use the specialized `knowledge_cards.py` pipeline and `kc_schema.sql`, described in [KNOWLEDGE_CARDS.md](KNOWLEDGE_CARDS.md). Declarative document-type policies remain future work.
