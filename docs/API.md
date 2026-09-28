# REST and MCP

The server hosts the UI, REST/OpenAPI and MCP on the same port. Default addresses are `http://127.0.0.1:8765`, `/docs`, `/mcp/query`, and optional `/mcp/admin`; the OpenAPI document is available at `/openapi.json`.

## MCP tools

The query profile exposes `corpus_describe`, `corpus_query` and `corpus_graph`. The optional
admin profile adds `corpus_manage`, `corpus_ingest`, and `corpus_job`.
See [MCP contracts and security](MCP.md) for setup, actions and examples.

The official Python MCP SDK implements stateless Streamable HTTP with JSON responses,
initialization, schema discovery, and typed calls. Query arguments are flat:
`query`, `collections`, `mode`, `perspective`, `limit`, `minimum_score`, `filters`,
`include_graph_context`, `format`. The graph tool takes a `request` object described in
[SOURCE_GRAPH.md](SOURCE_GRAPH.md).
Management tools accept a discriminated `request` object with an `action` and
only the fields valid for that action. The bare `/mcp` path exposes no tools.

Tool errors include the stable application error code in the error text. Returned content can include structured content as well as text content; clients should use standard MCP result handling and the published tool schemas.

MCP query/graph tools default to readable `llm` output with no duplicate JSON.
REST `/api/corpus/query`, `/api/corpus/graph`, `/api/search` and `/api/search/multi`
accept `format="raw"|"llm"` in the body, defaulting to raw JSON. Explicit LLM
mode returns UTF-8 `text/plain`, not a JSON string; default UI behavior is
unchanged. See [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md) for examples and scope.

## REST routes

| Method | Route | Operation |
|---|---|---|
| GET | `/api/health` | Daemon/model/vector status |
| GET | `/api/corpus` | Compact collection catalog for administrative REST clients |
| POST | `/api/corpus/query` | Unified query contract and structured response |
| POST | `/api/corpus/graph` | Bounded read-only source graph traversal; administrator REST authentication |
| GET / POST | `/api/collections` | List / create |
| GET / PATCH / DELETE | `/api/collections/{name}` | Inspect / description update / confirmed delete |
| GET / POST | `/api/collections/{name}/roots` | List / register |
| DELETE | `/api/collections/{name}/roots/{root_id}` | Unregister |
| POST | `/api/collections/{name}/scan` | Start incremental job |
| GET | `/api/collections/{name}/jobs` | List jobs |
| GET | `/api/collections/{name}/jobs/{job_id}` | Job record |
| POST | `/api/jobs/{job_id}/cancel` | Cancel cooperatively |
| POST | `/api/collections/{name}/jobs/{job_id}/resume` | Explicit resume |
| GET | `/api/collections/{name}/sources` | Paginated/filterable sources |
| GET / DELETE | `/api/collections/{name}/sources/{source_id}` | Inspect / confirmed removal |
| POST | `/api/collections/{name}/add_file` | Index an allowed existing path |
| POST | `/api/collections/{name}/upload` | Multipart field `file` |
| POST | `/api/knowledge-cards/search` | Ranked full cards plus ID-free YAML; general/expert query types |
| GET | `/api/collections/{name}/keywords` | Keyword vocabulary |
| GET | `/api/collections/{name}/metadata_fields` | Filter field catalog |
| POST | `/api/collections/{name}/rebuild` | Confirmed clear-and-reindex |
| POST | `/api/collections/{name}/vacuum` | Reclaim SQLite pages |
| GET | `/api/collections/{name}/manifest` | Collection/source manifest |
| POST | `/api/search` | Single-collection retrieval |
| POST | `/api/search/multi` | Cross-collection retrieval |
| GET | `/collections/{name}/jobs/{job_id}/events` | SSE `progress` events |

Creation accepts `name`, `description`, `source_roots`, `kind`, `embedding_model`, `chunk_size_tokens`, and `chunk_overlap_tokens`. Collection names are limited to letters, digits, underscores and hyphens and must begin with a letter or digit.

Scan bodies accept `root`, `recursive`, and `prune_missing`. File-add bodies accept `path`. Rebuild bodies require `{"confirm":true}`. Delete endpoints use `?confirm=true`, with optional `delete_files=true` for collections or `delete_original_managed_file=true` for sources.

Source-code collection inspection includes `graph.enabled`, stored
source/entity/relationship counts and `graph.pending_updates`. Counts describe
stored rows; revision validation may hide stale rows from traversal. Document
search routes accept `include_graph_context` (null by default); source-code hits
get read-only context unless false, while other collection kinds are unchanged.

### Scan job progress

Job REST responses, `corpus_job` replies and SSE `progress` events include:

- `progress.total`: candidate file count after discovery; null until known.
- `progress.discovered`: the discovered candidate count.
- `progress.processed`: completed + unchanged + failed + skipped.
- `progress.percent`: processed/total × 100; null until meaningful. A completed
  empty scan reports 100%; cancelled or failed scans retain partial progress.
- `progress.phase`: queued, discovering, indexing, pruning, finalizing, finished, paused,
  cancelled or failed.
- `timing.elapsed_seconds`: current-attempt elapsed time, frozen when stopped.
- `timing.estimated_remaining_seconds`: average indexing seconds per processed
  file × remaining files, or null when unavailable. Completed jobs report zero.
- `timing.estimate_basis`: `current_attempt_average_file_rate`.

The candidate total respects scan exclusions and collection-kind filters.
Progress can reach 100% of files while optional pruning is still running;
`phase="pruning"` makes that distinction explicit and has no cleanup ETA.
Elapsed includes discovery, whereas the ETA rate begins after discovery.
Resume rediscovers candidates and resets counters/timing for the new attempt.
Estimates vary with document size and converter/model performance.

`progress.processing` is the number of files currently in flight, not just a
boolean; `progress.queued` counts candidates not yet started. `current_item`
identifies a representative in-flight source. Multiple files can finish out of
order. Phase `finalizing` indicates the final keyword-frequency refresh; its
remaining-time estimate is unavailable even when all files are processed.

## Document-oriented REST search request

These REST routes support the administrative UI and retain their specialized
controls. They are not additional MCP tools. Query credentials cannot access
these administrative REST endpoints.

```json
{
  "collection": "books",
  "query": "retrieval",
  "mode": "hybrid",
  "top_k": 8,
  "filters": {
    "source_extensions": ["pdf", "md"],
    "keywords": ["retrieval"],
    "numeric": [
      {"field": "price", "op": "less_than", "value": 100, "currency": "EUR"},
      {"field": "published_date", "op": "between", "from": "2025-01-01", "to": "2026-12-31"}
    ]
  },
  "include_text": true,
  "include_links": true
}
```

Modes are `vector`, `keyword`, `hybrid`, and `structured`. Operators are `equal`, `not_equal`, `less_than`, `less_than_or_equal`, `greater_than`, `greater_than_or_equal`, `between`, and `exists`. A multi-search replaces `collection` with `collections: ["books", "code"]`.

Responses include `results`, `applied_filters`, `skipped_filters`, and, for single-search, `exhaustive`. Multi-search additionally includes `collections_searched` and `collections_failed`. Each result preserves provenance and available location fields; clients should not assume every format has page or line coordinates.

## Errors and safety

Application errors use `{"code":"...","message":"..."}` with optional context. Request-schema errors use FastAPI's HTTP 422 validation detail. Common codes include `CONFIG_INVALID`, `COLLECTION_NOT_FOUND`, `COLLECTION_BUSY`, `PATH_NOT_ALLOWED`, `FILE_TOO_LARGE`, `EXTRACTION_FAILED`, `OLLAMA_UNAVAILABLE`, `EMBEDDING_FAILED`, `VECTOR_SCHEMA_MISMATCH`, and `CONFIRMATION_REQUIRED`.

Retrieved document text is untrusted input for AI clients. It does not authorize shell execution, SQL execution, secret access or destructive tools. Explicit confirmations and configured source-root restrictions remain mandatory independently of anything a retrieved document says.
