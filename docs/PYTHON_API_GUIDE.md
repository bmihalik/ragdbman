# Python Call-Level API Guide

The Python API uses the same operation names as MCP, with underscores instead
of the CLI/REST hyphens. The full method and field catalog is generated in
[INTERFACES.md](INTERFACES.md). This guide describes direct ownership, request
construction, querying and lifecycle rules for ragdbman 0.6.0.

## Installation and ownership

```sh
uv sync --locked
```

Use one Engine owner per data directory. Its constructor validates configuration,
opens storage, reconstructs the registry, recovers interrupted jobs and replays
pending graph writes. Do not create another Engine merely to inspect a daemon's
live databases; call its REST/MCP interface instead.

The CLI/serve paths acquire `DataDirectoryLock` automatically. Embedded Python
owners should acquire it explicitly before constructing the Engine, and keep it
until the Engine is closed. Direct Python access is administrative OS/process
access; there is no implicit HTTP-token check.

```python
import asyncio
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.process_lock import DataDirectoryLock


async def main():
    config = GlobalConfig.load("~/.config/ragdbman/config.toml")
    with DataDirectoryLock(config):
        engine = Engine(config)
        try:
            print(await engine.health_status())
            print(engine.collections_list())
            print(engine.corpus_describe())
        finally:
            await engine.close()


asyncio.run(main())
```

Use one event loop for construction, asynchronous operations and cleanup. Do not
reuse one Engine across multiple `asyncio.run()` calls or call asyncio.run from
an existing event loop. From async code, await the operation directly.

## Configuration

`GlobalConfig.load(path)` reads TOML; a missing file yields defaults. Unknown
settings are rejected. Configure `storage.allowed_source_roots` before indexing
external paths. Managed upload paths are allowed within their collection.
Keep `security.allow_arbitrary_paths_from_mcp=false`; despite its name, setting
it true bypasses the source allowlist for every interface, including Python.

`defaults.recursive_scan` is reserved; use the `recursive` argument on each scan
or root registration. Configuration keys, converter setup, graph budgets and
reserved settings are documented in [CONFIGURATION.md](CONFIGURATION.md).

## Canonical invocation

The Engine exposes all operation methods under their canonical underscore names.
Query, graph and create accept a request model/dict or named keyword arguments.
Other methods accept the named fields listed in the reference.

For strict schema validation of every operation, use the shared dispatcher:

```python
from ragdbman.operations import invoke

result = await invoke(engine, "collection_get", {"name": "code"})
```

The dispatcher is always async, validates unknown/irrelevant fields, applies
confirmation checks and invokes the matching Engine method. It uses a fixed
catalog, not arbitrary user-supplied attribute execution. `admin=False` permits
only the three corpus operations and applies query-profile collection scope.
Use that mode only as one part of a trusted host's authorization boundary.

## Collections, roots and files

```python
await engine.collection_create(name="code", kind="source_code", source_roots=["/data/repo"])
print(engine.collection_get(name="code"))
engine.collection_config_update(name="code", description="Application sources")
root = engine.collection_add_root(collection="code", path="/data/repo")
print(engine.collection_list_roots(collection="code"))
indexed = await engine.collection_add_file(collection="code", path="/data/repo/main.py")
print(engine.collection_list_files(collection="code", limit=50))
print(engine.collection_get_file(collection="code", source_id=indexed["source_id"]))
```

Creation probes the embedding model and records its dimensions. General/source
collections use their configured chunk settings; Knowledge Cards embed whole
fields and reject chunk overrides. Root registration does not scan.
Config update changes only the description; omitted description clears it.

`collection_upload_file(collection, filename, content_base64)` creates a new
managed file and indexes it. The filename must be a single printable name.
It has the same base64 request contract as REST/MCP/CLI; existing external files
should instead use collection_add_file.

## Scans and jobs

```python
job = engine.scan_start(collection="code", root="/data/repo", recursive=True)
while job["status"] in {"queued", "running"}:
    await asyncio.sleep(0.5)
    job = engine.scan_job_get(collection="code", job_id=job["id"])
print(engine.scan_jobs_list(collection="code", status=None))
```

`scan_start`, `scan_job_resume` and `collection_rebuild` are synchronous scheduling
methods but require a running event loop. Keep the owner alive until work stops.
Calling close immediately cancels owned work and pauses interrupted jobs.
`scan_job_cancel(job_id)` requests cooperative cancellation; resume uses both
`collection` and `job_id`. Resume supports paused, failed, cancelled and
completed-with-errors jobs and starts a fresh attempt.

## One corpus query

```python
from ragdbman.corpus import CorpusQuery

raw = await engine.corpus_query(collections=["code", "books"], query="configuration", mode="hybrid", limit=5)
text = await engine.corpus_query(
    CorpusQuery(collections=["code"], query="parse_config", mode="keyword", format="llm")
)
cards = await engine.corpus_query(
    collections=["cards"], query="shortest path", perspective="expert", minimum_score=0, format="raw"
)
filtered = await engine.corpus_query(
    collections=["books"],
    query="",
    mode="structured",
    filters={"numeric": [{"field": "price", "op": "less_than", "value": 100}]},
)
```

One collection and many collections both use `collections`. Modes are keyword,
semantic, hybrid and structured. Structured accepts an empty query and filters
documents/source code without embedding; cards reject it and document filters.
Perspective defaults to general; expert affects only card scoring. The global
limit defaults to 5. Omitted collections use configured corpus defaults, not all.

Raw dictionaries contain `query`, `effective_options`, `collections_searched`,
`warnings` and ranked `results`. Each result includes kind, collection, title,
relevance/score policy, provenance, content and optional graph context.
Card content preserves YAML values except its top-level ID. Raw scores from
different retrieval policies are not comparable probabilities; cross-collection
ordering uses ranks. Per-collection failures are warnings, not fake success.

`include_text`, `include_links` and `include_graph_context` control evidence.
The first two default true; graph context defaults automatically for source-code
collections. LLM output is deterministic formatting, not generated summaries.
Internal `_query_documents`, `_query_cards` and `_query_many` are implementation
helpers, not public retrieval interfaces.

## Source graphs

```python
from ragdbman.graph.query import GraphRequest

found = await engine.corpus_graph(collection="code", action="find", symbol="parse")
callers = await engine.corpus_graph(
    GraphRequest(collection="code", action="callers", symbol="parse_config", depth=2, format="llm")
)
```

Actions are find, neighbors, callers, callees, dependencies, inheritance and
impact. Exact entity IDs disambiguate names. Source graph reads are bounded,
source-code-only and never trigger parsing, embedding or outbox replay.
Syntax facts are deterministic; target resolution is best-effort static analysis,
not compiler binding or a runtime call graph. See [SOURCE_GRAPH.md](SOURCE_GRAPH.md).

## Inspection and maintenance

```python
print(engine.collection_list_keywords(collection="code", query="config"))
print(engine.collection_list_metadata_fields(collection="books"))
manifest = engine.collection_export_manifest(collection="code")
engine.collection_vacuum(collection="code")
engine.collections_registry_repair()
engine.collection_remove_root(collection="code", root_id=root["root_id"], confirm=True)
engine.collection_remove_file(collection="code", source_id=indexed["source_id"], confirm=True)
```

Root removal preserves files and indexes. File removal preserves originals unless
`delete_original_managed_file=True` targets a managed original. Collection deletion
requires `collection_delete(name, confirm=True)` and preserves managed files unless
`delete_files=True`; external roots are never deleted. Rebuild requires confirmation,
clears first and retains existing model/chunk settings; it is not an atomic swap.
Registry repair is rejected while indexing is active. A manifest is not a backup.

## Errors, embedders and shutdown

`RagError` exposes `code`, `message`, optional `context`, `as_dict()` and
`status_code`. Request model errors are Pydantic ValidationError instances.
Invalid cards map to 422 and duplicates to 409 in REST; direct Python gets the
same stable error codes. Never suppress provider failures with fake embeddings.

An injected embedder must implement async `embed(texts, model,
expected_dimensions=None, keep_alive=None)` and return one finite vector per input
with the recorded dimensions. Knowledge Cards require nonzero vectors for cosine
scoring. Tests inject deterministic fixtures; production needs a real embedding model.

Engine close awaits owned work, converter cleanup and database/HTTP cleanup.
CLI/serve adds signal deadlines and process ownership guards; arbitrary embedded
Python owners must manage their own signals and lifetime. Read [RUNTIME.md](RUNTIME.md)
before operating on shared or production storage.
