# Architecture

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
| Shared application engine | `engine.py` |
| Blocking-work isolation and cancellation cleanup | `workers.py` |
| MCP interface | `mcp_server.py` |
| REST and administrative UI | `web.py`, `static/` |
| Command-line interface | `cli.py`, `__main__.py` |

## Ingestion path

1. Resolve the collection, canonicalize the source, enforce the allowlist and size limit.
2. Hash the file and compare with the existing source's indexed hash and status.
3. Extract directly or create a collection-appropriate Markdown sidecar.
4. Resolve the collection model's tokenizer, create structure-aware chunks and metadata.
5. Embed via batched Ollama calls outside any SQLite write transaction.
6. Verify count/dimensions, check cancellation, and verify the source did not change during processing.
7. In one transaction, replace old chunks/FTS/vectors/facts, persist artifacts and a source version, and mark the source indexed.

Failed processing records a durable error and marks the source failed. A later scan retries it even when its content hash has not changed.

## Storage and initialization

`schema.sql` defines the complete collection schema, including collection kinds, line positions, Markdown paths, percentage positions, and an internal-content FTS5 index. `db.initialize_schema` creates missing tables and seeds built-in metadata fields idempotently; the vector table is created once the embedding dimensions are known.

Source and chunk tables are authoritative, and indexing keeps their FTS and vector records consistent within a transaction. Normal restarts leave stored source IDs, chunk IDs, embeddings, and search results intact; tests cover both fresh initialization and reopening populated databases.

Each short operation opens a SQLite connection with foreign keys, WAL, a busy timeout, and the sqlite-vec extension. Long conversion/network work is performed outside write transactions. Do not run multiple daemon processes on the same data directory; in-process collection locks are not distributed leases.

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

Hashing, tokenizer loading/chunking, transactional index writes and missing-source
pruning run in worker threads. Every database writer creates and closes its own
SQLite connection on that thread. Threads isolate blocking work, not machine
resource usage: large jobs can still compete for CPU, memory and disk. Large
searches and explicit maintenance operations still need scale-focused profiling.

Active mutations are serialized per collection. A repeated start-scan call returns
the existing active scan. Thread-safe cancellation flags are checked during index
writes and before commit, so cancelled writes roll back. Cancellation waits for
worker cleanup before releasing the collection lock; it cannot leave a detached
writer modifying a collection after shutdown or deletion.

Interrupted jobs are paused at startup and require explicit resume; successful
source hashes make replay incremental. Shutdown cancellation is forwarded to the
converter's event loop, and converter processes are terminated as a group on
POSIX. Ordinary Cancel is cooperative: an in-flight extraction may finish, but
its index is not committed. The overview's Ollama health probe has a three-second
deadline, including time waiting for an embedding request slot.

## Retrieval path

Structured predicates narrow eligible chunk IDs. FTS5 supplies keyword ranks; sqlite-vec supplies exact vector distances. Hybrid fusion combines channel ranks, and multi-collection fusion combines independent collection ranks. Results include evidence and filter diagnostics rather than synthesized answers.

Exact vector evaluation avoids returning too few matches because a selective filter was applied after a small KNN candidate set. This trades throughput for completeness and should be benchmarked before very large deployments.

## Extension points

- Implement the async `Embedder` protocol for another real embedding provider.
- Add format adapters returning `Document` and `Block` records, then register the extension dispatch.
- Keep new retrieval strategies behind the shared search/engine interface.
- Keep schema definitions complete, and test fresh initialization, repeated initialization, and persistence across restarts.
- Knowledge Cards use the specialized `knowledge_cards.py` pipeline and `kc_schema.sql`, described in [KNOWLEDGE_CARDS.md](KNOWLEDGE_CARDS.md). Declarative document-type policies remain future work.
