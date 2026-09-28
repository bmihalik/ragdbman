# Python Call-Level API Guide

Updated for ragdbman 0.5.2 from the supplied guide. The implementation is the
authority for signatures, lifecycle and return fields; examples below describe
the current Python, CLI and transport boundaries.

## Overview

`Engine` implements collection storage, indexing, retrieval and jobs. The
`corpus` and `corpus_admin` modules provide the unified MCP contracts over it.
Direct Python calls share the underlying behavior without HTTP overhead, but
transport envelopes, authentication and default output formats can differ.

This guide covers everything you need to use ragdbman as a Python library: instantiation, the complete method catalog, request/response types, error handling, and concurrency rules.

## Installation

```bash
uv sync --locked
```

Or add to an existing project:

```bash
uv add /path/to/ragdbman
```

## Architecture in Brief

```
GlobalConfig (TOML)
       |
       v
    Engine  ←── shared storage and indexing services
     /   |   \    \
   CLI  MCP  REST  Web UI   (service adapters/transports)
```

The `Engine` class is defined in `ragdbman.engine.Engine`. Its constructor takes
a validated `GlobalConfig` and an optional `Embedder`, defaulting to Ollama.
MCP does not expose every engine method: its three read-only tools are
`corpus_describe`, `corpus_query`, and `corpus_graph`; the optional admin profile
adds `corpus_manage`, `corpus_ingest`, and `corpus_job`.
CLI service commands map kebab-case names to the corresponding engine methods.
See [CLI.md](CLI.md), [MCP.md](MCP.md) and [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).

## Getting Started

### Loading Configuration

```python
from ragdbman.config import GlobalConfig

# Load from the default or a custom TOML path
config = GlobalConfig.load("~/.config/ragdbman/config.toml")
```

If the file does not exist, `GlobalConfig.load()` returns a config with all defaults. You can also construct a config programmatically:

```python
from ragdbman.config import GlobalConfig

config = GlobalConfig()  # all defaults
config.ollama.base_url = "http://127.0.0.1:11434"
config.ollama.embedding_model = "bge-m3:567m"
config.storage.allowed_source_roots = ["/home/user/documents", "/home/user/projects"]
```

Key configuration sections:

| Section | Purpose |
|---|---|
| `server` | Bind address, port, MCP path, auth mode |
| `storage` | Data directory, registry path, allowed source roots, sidecar settings |
| `ollama` | Embedding model, base URL, batch size, concurrency, timeouts |
| `defaults` | Chunk size/overlap, scan concurrency, file size limits, recursive scanning |
| `source_code` | Chunk size/overlap for `source_code` collections |
| `graph` | Source-code graph enablement, parser budgets, enrichment limits |
| `search` | Default/max top-k, vector/keyword weights, RRF k, context char limit |
| `media` | Optional external converters (LibreOffice, Tesseract, Whisper, etc.) |
| `security` | File URI links, HTTP source URLs, arbitrary path access from MCP |
| `logging` | `critical`, `error`, `warning`/`warn`, `info`, `verbose`, `debug`, `trace` |

### Creating an Engine Instance

```python
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine

config = GlobalConfig.load("~/.config/ragdbman/config.toml")
engine = Engine(config)
```

The constructor:
- Copies and re-validates the config.
- Creates the data directory if it does not exist.
- Repairs the collection registry by scanning for existing SQLite databases.
- Recovers interrupted jobs (marks running/queued jobs paused and unfinished items retryable), refreshes keywords and replays pending graph outbox events.
- Initializes the Ollama embedder client.

### Synchronous vs Asynchronous Methods

Methods fall into two categories:

- **Synchronous** (no network I/O): `list_collections`, `get_collection`, `update_collection_config`, `delete_collection`, `list_source_roots`, `add_source_root`, `remove_source_root`, `list_sources`, `get_source`, `start_scan`, `get_job`, `list_jobs`, `cancel_job`, `resume_job`, `list_keywords`, `list_metadata_fields`, `rebuild_collection`, `vacuum_collection`, `export_collection_manifest`.

- **Asynchronous:** `create_collection`, `add_file`, `search`,
  `search_multi`, `search_knowledge_cards`, `graph`, `health_status`, `close`.
  Async does not imply network activity: keyword search and graph reads need
  no embedding request.

Call async methods with `asyncio.run()` or within an existing event loop:

The synchronous scheduling methods `start_scan`, `resume_job`, and
`rebuild_collection` also require a running event loop because they create
tasks. “Synchronous” describes their call signature, not standalone job ownership.

```python
import asyncio


async def run_search():
    engine = Engine(config)
    try:
        return await engine.search(
            {
                "collection": "my_docs",
                "query": "configuration file parsing",
            }
        )
    finally:
        await engine.close()


result = asyncio.run(run_search())
```

## Complete Method Reference

### Health and Collections

#### `health_status()` — async

Checks daemon readiness, SQLite vector extension, and Ollama connectivity.

For direct Python/CLI calls, `daemon_ok` means this engine is responsive, not
that an independent HTTP daemon is running. Use CLI `--server-url` or REST to
check the serving daemon. An unavailable Ollama is reported in the returned
health record and does not prevent inspection or existing keyword queries.

```python
status = await engine.health_status()
# {
#   "daemon_ok": True,
#   "vector_extension_ok": True,
#   "ollama_reachable": True,
#   "ollama_model": "bge-m3:567m",
#   "ollama_dimensions": 1024,
#   "message": None,
#   "active_jobs": 0,
#   "collections": 3,
# }
```

#### `list_collections()` — sync

Returns all collections with counts, status, embedding, and chunking settings.

```python
for c in engine.list_collections():
    print(c["name"], c["counts"]["chunks"], "chunks")
```

#### `get_collection(name: str)` — sync

Returns a single collection by name. Raises `RagError("COLLECTION_NOT_FOUND")` if absent.

```python
meta = engine.get_collection("my_docs")
print(meta["embedding"]["model"], meta["chunking"]["size_tokens"])
```

#### `create_collection(request=None, **kwargs)` — async

Creates a new collection. Accepts a `CreateCollection` model or keyword arguments. The method probes the embedding model for dimensionality before creating any files — if the probe fails, nothing is written.

```python
from ragdbman.models import CreateCollection

collection = await engine.create_collection(
    CreateCollection(
        name="my_docs",
        description="Personal documents",
        source_roots=["/home/user/documents"],
        kind="general",  # or "source_code", "knowledge_cards"
        embedding_model="bge-m3:567m",  # optional; defaults from config
        chunk_size_tokens=256,  # optional; defaults from config
        chunk_overlap_tokens=64,  # optional; defaults from config
    )
)

# Or with kwargs:
collection = await engine.create_collection(
    name="my_code",
    kind="source_code",
    source_roots=["/home/user/projects/myapp"],
)
```

Collection names must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`.

Raises `RagError("CONFIG_INVALID")` if the name already exists, or `RagError("PATH_NOT_ALLOWED")` if a source root is outside `allowed_source_roots`.

#### `update_collection_config(name, description=None, rebuild=False)` — sync

Updates a collection description. Model and chunking changes require a new collection (use `rebuild_collection` for re-indexing).

```python
engine.update_collection_config("my_docs", description="Updated description")
```

#### `delete_collection(name, confirm=False, delete_files=False)` — sync

Deletes a collection. Requires `confirm=True`. By default, original files are preserved; only the index database is removed. The deletion is logged to `deletions.jsonl`.

```python
engine.delete_collection("my_docs", confirm=True, delete_files=False)
```

### Source Roots

#### `list_source_roots(collection: str)` — sync

Returns registered filesystem roots for a collection.

#### `add_source_root(collection, path, recursive=True)` — sync

Registers a new source directory. The path must be inside `allowed_source_roots` or the collection's managed root. Returns `{"root_id": "..."}`.

#### `remove_source_root(collection, root_id)` — sync

Unregisters a root. Does not delete indexed data; sources retain their root_id as NULL.

### Scanning and Indexing

#### `start_scan(collection, root, recursive=True, prune_missing=False)` — sync

Starts an incremental scan job on the current running event loop. If the
collection already has an active job, it returns that job. Keep the owning
engine/event loop alive until completion; closing it pauses active work.

```python
job = engine.start_scan("my_docs", "/home/user/documents", recursive=True)
print(job["id"], job["status"])  # "queued"

# Poll for progress
import asyncio

while True:
    job = engine.get_job("my_docs", job["id"])
    if job["status"] in ("completed", "failed", "cancelled", "completed_with_errors", "paused"):
        break
    print(job["progress"])
    await asyncio.sleep(2)
```

The `prune_missing=True` option removes indexed data and marks missing sources
for that root; it does not delete the original file. Direct callers authorize
that behavior by explicitly setting the flag; the CLI additionally requires
`--confirm` for pruning.

#### `add_file(collection, path, origin="filesystem")` — async

Indexes a single existing file. The path must be inside an allowed root or the
collection's managed root. Returns `source_id`, `chunks`, `classification`
(`new`, `changed`, `previously_failed`, `unchanged`, `unsupported`), and `skipped`.
Knowledge Cards can additionally report `not_a_card`; they use field embeddings
and report zero document chunks.

```python
result = await engine.add_file("my_docs", "/home/user/documents/report.pdf")
print(result["classification"], result["chunks"], "chunks indexed")
```

#### `remove_source(collection, source_id, confirm=False, delete_original_managed_file=False)` — sync

Removes all indexed data for a source. Requires `confirm=True`. If `delete_original_managed_file=True`, also deletes the original file — but only if it lives inside the collection's managed upload directory.

### Job Management

#### `get_job(collection, job_id)` — sync

Returns the full job record including status, progress, error summary, and item-level diagnostics.

#### `list_jobs(collection, status=None, limit=50)` — sync

Lists jobs for a collection. Optional `status` filter: `queued`, `running`, `paused`, `completed`, `completed_with_errors`, `failed`, `cancelled`.

#### `cancel_job(job_id)` — sync

Requests cooperative cancellation. The scan stops at the next index commit boundary. Returns `{"cancel_requested": job_id}`.

Already-cancelled jobs return idempotently. Completed, completed-with-errors
and failed records are not rewritten as cancelled; those calls fail with
`CONFIG_INVALID`. Paused jobs can be cancelled without resuming them.

#### `resume_job(collection, job_id)` — sync

Resumes an interrupted or failed scan/rebuild job. Only jobs in `paused`, `failed`, `cancelled`, or `completed_with_errors` status can be resumed.

### Search

#### `search(request)` — async

Searches a single collection. Accepts a `SearchRequest` model or a plain dict.

```python
from ragdbman.models import SearchRequest, SearchFilters, NumericFilter

result = await engine.search(
    SearchRequest(
        collection="my_docs",
        query="configuration file parsing",
        mode="hybrid",  # "vector", "keyword", "hybrid", "structured"
        top_k=10,
        filters=SearchFilters(
            source_extensions=[".pdf", ".md"],
            keywords=["config", "settings"],
            path_prefix="/home/user/docs",
            numeric=[
                NumericFilter(field="amount", op="greater_than", value=1000),
                NumericFilter(field="date", op="between", **{"from": "2024-01-01", "to": "2024-12-31"}),
            ],
        ),
        include_text=True,
        include_links=True,
    )
)

for r in result["results"]:
    print(f"{r['score']:.4f}  {r['source_filename']}  {r['citation_label']}")
    print(r["text"][:200])
```

Search modes:

| Mode | Description |
|---|---|
| `vector` | Semantic similarity via Ollama embeddings + sqlite-vec L2 distance |
| `keyword` | BM25 full-text search via FTS5 |
| `hybrid` | Reciprocal Rank Fusion of vector and keyword scores (default) |
| `structured` | Returns matching chunks up to top-k, using constant score 1 rather than semantic relevance |

Raw is the Python default; `format="llm"` instead returns readable text.
`include_graph_context=None` enables graph enrichment for source-code collections
only; false disables it. Raw graph context includes current source/chunk
provenance, while text mode flattens it. The raw return dict contains:

```python
{
    "results": [
        {
            "collection_id": "...",
            "chunk_id": "...",
            "score": 0.0156,  # fused rank score
            "vector_score": 0.83,  # 1 / (1 + L2 distance), not a probability
            "keyword_score": 0.42,  # raw BM25 score (None if not keyword mode)
            "text": "...",  # chunk text (truncated to return_context_chars_per_chunk)
            "truncated": False,
            "heading": "Section Title",
            "source_id": "...",
            "source_filename": "report.pdf",
            "source_path": "/home/user/docs/report.pdf",
            "source_link": "file:///home/user/docs/report.pdf",  # if allow_file_uri_links
            "original_url": None,  # if allow_http_source_urls
            "markdown_path": None,
            "metadata_facts": [...],  # extracted numeric/date fields
            "matched_keywords": ["config", "settings"],
            "section_path": "Chapter 1 > Configuration",
            "page_start": 3,
            "page_end": 3,
            "slide_start": None,
            "slide_end": None,
            "time_start_ms": None,
            "time_end_ms": None,
            "line_start": None,
            "line_end": None,
            "percent_position": 45.2,
            "citation_label": "report.pdf, p.3",
        },
        # ...
    ],
    "applied_filters": ["amount greater_than", "keyword:config"],
    "skipped_filters": [],  # filters that could not be applied (field not found, etc.)
    "exhaustive": True,
}
```

#### `search_multi(request)` — async

Searches multiple collections, fuses ranks via Reciprocal Rank Fusion, and reports per-collection failures.

```python
result = await engine.search_multi(
    {
        "collections": ["my_docs", "my_code", "research"],
        "query": "error handling",
        "mode": "hybrid",
        "top_k": 20,
    }
)

for r in result["results"]:
    print(r["collection_id"], r["score"], r["source_filename"])

if result["collections_failed"]:
    for failure in result["collections_failed"]:
        print(f"Failed: {failure['collection']} — {failure['reason']}")
```

Each collection is searched with `max_top_k` internally, then results are re-ranked globally and truncated to the requested `top_k`. Per-collection failures (e.g. a collection database is locked) are captured in `collections_failed` rather than raising an exception.

### Inspection and Maintenance

#### `list_sources(collection, extension=None, path_prefix=None, limit=50, offset=0, status=None)` — sync

Paginated listing of indexed sources. Filter by extension, path prefix, or status (`discovered`, `extracting`, `embedding`, `indexed`, `failed`, `unsupported`, `queued`).

#### `get_source(collection, source_id)` — sync

Full source record including indexing diagnostics and status detail.

#### `list_keywords(collection, query=None, limit=50, offset=0)` — sync

Browse the deterministic keyword vocabulary extracted during indexing. Filter by substring query, ordered by chunk frequency.

#### `list_metadata_fields(collection)` — sync

Inspect numeric, date, and currency filter fields available for structured search.

#### `export_collection_manifest(collection)` — sync

Returns collection settings and a full source manifest. This is an inspection
manifest, not a complete backup of embeddings, indexes or source files.

#### `rebuild_collection(collection, confirm=False)` — sync

Clears all chunks and re-indexes all existing sources. Requires `confirm=True`. Model and chunking settings are preserved; only chunk data is regenerated.

#### `vacuum_collection(collection)` — sync

Reclaims unused SQLite pages. The collection must be idle (no active scan/rebuild).

## Request Types

Request models use Pydantic with `extra="forbid"`. Most are in
`ragdbman.models`; `GraphRequest` is in `ragdbman.graph.query` and `CorpusQuery`
is in `ragdbman.corpus`. Unknown fields raise validation errors.

### `CreateCollection`

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | `str` | required | Must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$` |
| `description` | `str \| None` | `None` | |
| `source_roots` | `list[str]` | `[]` | Must be inside `allowed_source_roots` |
| `kind` | `Literal["general", "source_code", "knowledge_cards"]` | `"general"` | Code disables sidecars; cards use whole-field embeddings and reject chunk overrides |
| `embedding_model` | `str \| None` | `None` | Falls back to config default |
| `chunk_size_tokens` | `int \| None` | `None` | Must be >= 1 |
| `chunk_overlap_tokens` | `int \| None` | `None` | Must be < `chunk_size_tokens` |

### `SearchRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `collection` | `str` | required | |
| `query` | `str` | required | |
| `mode` | `Literal["vector", "keyword", "hybrid", "structured"]` | `"hybrid"` | |
| `top_k` | `int \| None` | `None` | Falls back to `config.search.default_top_k`, capped at `max_top_k` |
| `filters` | `SearchFilters` | empty | |
| `include_text` | `bool` | `True` | Set `False` to omit chunk text (metadata-only results) |
| `include_links` | `bool` | `True` | Set `False` to omit `source_link` and `original_url` |
| `format` | `Literal["raw", "llm"]` | `"raw"` | Dictionary or readable string |
| `include_graph_context` | `bool \| None` | `None` | Automatic for source-code collections only |

### `SearchFilters`

| Field | Type | Default | Notes |
|---|---|---|---|
| `source_extensions` | `list[str]` | `[]` | e.g. `[".pdf", ".md"]` |
| `numeric` | `list[NumericFilter]` | `[]` | Structured field filters |
| `keywords` | `list[str]` | `[]` | Must match extracted keyword vocabulary |
| `path_prefix` | `str \| None` | `None` | Filter by source file path prefix |
| `source_ids` | `list[str]` | `[]` | Restrict to specific source IDs |

### `NumericFilter`

| Field | Type | Notes |
|---|---|---|
| `field` | `str` | Must exist in `metadata_fields` |
| `op` | `Literal["equal", "not_equal", "less_than", "less_than_or_equal", "greater_than", "greater_than_or_equal", "between", "exists"]` | |
| `value` | `float \| str \| None` | Required for all ops except `between` and `exists` |
| `from_` (alias `"from"`) | `float \| str \| None` | Required for `between` |
| `to` | `float \| str \| None` | Required for `between` |
| `currency` | `str \| None` | ISO 4217 code, e.g. `"USD"` |

### `MultiSearchRequest`

Same fields as `SearchRequest` but with `collections: list[str]` instead of `collection: str`.

## Error Handling

All application errors are raised as `RagError`, which carries a stable code and message:

```python
from ragdbman.errors import RagError

try:
    result = await engine.search({"collection": "nonexistent", "query": "test"})
except RagError as exc:
    print(exc.code)  # "COLLECTION_NOT_FOUND"
    print(exc.message)  # "nonexistent"
    print(exc.status_code)  # 404 (HTTP equivalent, for reference)
```

Stable error codes:

| Code | HTTP | Meaning |
|---|---|---|
| `CONFIG_INVALID` | 400 | Invalid configuration or duplicate name |
| `CONFIRMATION_REQUIRED` | 400 | Destructive operation called without `confirm=True` |
| `COLLECTION_NOT_FOUND` | 404 | Collection does not exist |
| `COLLECTION_BUSY` | 409 | Collection has an active scan or rebuild |
| `PATH_NOT_ALLOWED` | 403 | Path outside `allowed_source_roots` |
| `SOURCE_NOT_FOUND` | 404 | Source ID does not exist |
| `JOB_NOT_FOUND` | 404 | Job ID does not exist |
| `FILE_TOO_LARGE` | 413 | File exceeds `max_file_size_mb` |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | No extractor for this file type |
| `EXTRACTION_FAILED` | 422 | Extraction produced no text |
| `OCR_FAILED` | 422 | OCR step failed |
| `TRANSCRIPTION_FAILED` | 422 | Audio transcription failed |
| `OLLAMA_UNAVAILABLE` | 503 | Cannot reach Ollama |
| `EMBEDDING_FAILED` | 502 | Embedding request failed |
| `VECTOR_SCHEMA_MISMATCH` | 409 | Embedding dimensions do not match collection |
| `JOB_CANCELLED` | 409 | Job was cancelled mid-operation |
| `DATABASE_CORRUPT` | 500 | Database integrity issue |
| `INTERNAL` | 500 | Unexpected internal error |
| `DATA_DIRECTORY_BUSY` | 409 | Another guarded CLI/daemon owns storage or registry |
| `DAEMON_UNAVAILABLE` | 503 | CLI daemon transport failed; no local fallback |
| `REMOTE_ERROR` | 502 | CLI received a non-success daemon response without an application code |

The `require_confirmation()` helper raises `RagError("CONFIRMATION_REQUIRED")` for any destructive method called without `confirm=True`.

## Concurrency and Lifecycle Rules

### One Engine Per Event Loop

The `Engine` maintains:
- A per-collection SQLite connection pool (`check_same_thread=False`, safe within a single event loop).
- One serialized persistent writer per collection, exclusively leased read connections, and per-collection mutation locks.
- Background asyncio tasks for scan/rebuild jobs.
- A single Ollama HTTP client with a bounded semaphore for embedding requests.

Create one engine per data directory, share it on one event loop, and close it
on that loop. Independent engines/processes sharing storage are unsupported:
constructor recovery could pause another engine's live jobs.
CLI/serve hold `DataDirectoryLock` for storage and registry ownership.
Embedded applications should also hold `ragdbman.process_lock.DataDirectoryLock(config)`
for the entire engine lifetime when sharing an installation with CLI/serve.
This is an advisory process guard, not distributed locking across hosts.

### Using in an Async Application

```python
import asyncio
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine


async def main():
    config = GlobalConfig.load("~/.config/ragdbman/config.toml")
    engine = Engine(config)

    try:
        await engine.health_status()
        job = engine.start_scan("my_docs", "/home/user/docs")
        # ... do other async work while scanning ...
        result = await engine.search({"collection": "my_docs", "query": "important topic"})
        for r in result["results"]:
            print(r["citation_label"], r["score"])
    finally:
        await engine.close()


asyncio.run(main())
```

### Using in a Synchronous Script

For scripts that only need read operations or one-shot searches:

```python
import asyncio
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine


async def run():
    config = GlobalConfig.load("~/.config/ragdbman/config.toml")
    engine = Engine(config)
    try:
        for c in engine.list_collections():
            print(c["name"], c["counts"]["sources"], "sources")
        return await engine.search({"collection": "my_docs", "query": "test"})
    finally:
        await engine.close()


# One asyncio.run for construction, network operations and cleanup.
result = asyncio.run(run())
```

### Thread Safety

Call public engine methods on their owning event-loop thread. Internally,
extraction, graph reads and database writes use controlled workers and exclusive
connection leases; not all SQLite access occurs on the event loop.
Do not invoke arbitrary engine methods from multiple threads. Use
`asyncio.to_thread()` for independent application work, not to bypass engine
lifecycle or mutation ownership.

## Complete Example: End-to-End Workflow

```python
import asyncio
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.models import CreateCollection, SearchRequest, SearchFilters


async def main():
    config = GlobalConfig.load("~/.config/ragdbman/config.toml")
    engine = Engine(config)

    try:
        # 1. Check health
        health = await engine.health_status()
        if not health["ollama_reachable"]:
            print(f"Ollama not reachable: {health['message']}")
            return

        # 2. Create a collection (or reuse existing)
        existing = {c["name"] for c in engine.list_collections()}
        if "my_project" not in existing:
            await engine.create_collection(
                CreateCollection(
                    name="my_project",
                    description="Project documentation and code",
                    source_roots=["/home/user/projects/myapp"],
                    kind="source_code",
                )
            )

        # 3. Start a scan
        job = engine.start_scan("my_project", "/home/user/projects/myapp")
        print(f"Scan started: {job['id']}")

        # 4. Wait for completion
        while True:
            job = engine.get_job("my_project", job["id"])
            if job["status"] in ("completed", "failed", "cancelled", "completed_with_errors", "paused"):
                break
            print(f"  Progress: {job['progress']}")
            await asyncio.sleep(2)

        print(f"Scan finished: {job['status']}")
        if job["status"] == "completed_with_errors":
            print(f"  Errors: {job['error_summary']}")

        # 5. Search
        result = await engine.search(
            SearchRequest(
                collection="my_project",
                query="error handling and logging",
                mode="hybrid",
                top_k=5,
                include_text=True,
            )
        )

        print(f"\nFound {len(result['results'])} results:")
        for r in result["results"]:
            print(f"  [{r['score']:.4f}] {r['citation_label']}")
            if r["text"]:
                print(f"    {r['text'][:150]}...")

        # 6. Inspect keywords
        keywords = engine.list_keywords("my_project", query="error", limit=10)
        print(f"\nKeywords matching 'error':")
        for kw in keywords:
            print(f"  {kw['canonical_form']} (frequency: {kw['chunk_frequency']})")

    finally:
        await engine.close()


asyncio.run(main())
```

## Custom Embedders

The `Engine` accepts an optional `embedder` parameter that implements the `Embedder` protocol:

```python
from ragdbman.ollama import Embedder


class MyEmbedder:
    async def embed(
        self,
        texts: list[str],
        model: str,
        expected_dimensions: int | None = None,
        keep_alive: str | None = None,
    ) -> list[list[float]]:
        # Test double only. Production requires meaningful model embeddings.
        return [[0.0] * 1024 for _ in texts]

    async def close(self):
        pass


engine = Engine(config, embedder=MyEmbedder())
```

This is useful for testing (inject a mock embedder that returns deterministic vectors) or for using a non-Ollama embedding backend.

## Path Security

Source paths are checked against allowed roots or the collection's managed
root through `config.checked_path()`. The legacy-named
`security.allow_arbitrary_paths_from_mcp` bypasses that allowlist globally,
including direct engine/CLI calls, not only MCP. Leave it false unless that
broader filesystem access is explicitly intended. Direct calls do not perform
HTTP/MCP token or collection-scope authorization.

## Differences from MCP/REST

| Aspect | Python API | MCP/REST |
|---|---|---|
| Transport | Direct method calls | JSON-RPC over HTTP / REST JSON |
| Authentication | OS/process access; direct calls have no token check | REST/admin and query MCP use distinct authorization boundaries |
| Error format | `RagError` exceptions | Error codes in JSON response |
| Async model | `asyncio` event loop | HTTP request/response |
| Connection pool | Single pool, one event loop | Pool shared across requests |
| Performance | No serialization overhead | JSON encode/decode per call |

Use the direct API when your application owns the engine lifecycle. Use REST/MCP
when a daemon owns the data, including same-machine clients; do not instantiate
a second engine merely to inspect a running daemon.

## Knowledge Cards, unified queries and source graphs

`await engine.search_knowledge_cards(request)` accepts
`KnowledgeCardSearchRequest` or a dict with `collection`, `query`, `mode`
(`keyword`, `vector`, `hybrid`), `query_type` (`general`, `expert`),
`top_k`, and `minimum_similarity`. It returns ranked card matches; this
specialized method retains its list return rather than a presentation switch.
See [KNOWLEDGE_CARDS.md](KNOWLEDGE_CARDS.md).

For the unified document/code/card contract, including multiple collections:

```python
from ragdbman.corpus import CorpusQuery, query

text = await query(
    engine,
    CorpusQuery(
        query="configuration parsing",
        collections=["my_code", "my_docs"],
        mode="hybrid",
        format="llm",
    ),
)
```

`corpus.query` applies the configured query collection scope unless called
with `admin=True` by a trusted owner. Mode `semantic` is the corpus spelling;
the lower-level `SearchRequest` spelling remains `vector`.

```python
from ragdbman.graph.query import GraphRequest

result = await engine.graph(
    GraphRequest(
        collection="my_code",
        action="callers",
        symbol="parse_config",
        depth=2,
        limit=50,
        format="raw",
    )
)
```

Graph reads are bounded, read-only and source-code-only. They do not parse,
flush pending writes, execute source code or call an LLM. Syntax extraction
is deterministic; target resolution is best-effort static analysis, with
explicit ambiguous/unresolved edges. See [SOURCE_GRAPH.md](SOURCE_GRAPH.md).
