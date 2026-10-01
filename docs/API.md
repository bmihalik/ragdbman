# REST and MCP API

ragdbman exposes one canonical operation vocabulary across Python, CLI, REST and
MCP. The exact names, fields, defaults and hints are generated from the source
catalog in [INTERFACES.md](INTERFACES.md), not maintained as separate route lists.

## REST contract

Every operation uses `POST /api/<hyphenated-operation>` with a JSON body, including
reads. OpenAPI is at `/openapi.json` and its interactive reference is at `/docs`.
Its operation IDs are the corresponding Python/MCP underscore names.

```http
POST /api/corpus-query
Content-Type: application/json
Authorization: Bearer ADMIN_TOKEN

{"collections":["books","code"],"query":"configuration","mode":"hybrid","limit":5,"format":"raw"}
```

Examples of other request bodies:

```json
{"name":"code","kind":"source_code","source_roots":["/data/repo"]}
```

Send this to `/api/collection-create`. Registering roots does not index files.
Start a scan with `/api/scan-start`:

```json
{"collection":"code","root":"/data/repo","recursive":true}
```

The returned job has an `id`. Inspect it through `/api/scan-job-get`:

```json
{"collection":"code","job_id":"JOB_ID"}
```

No-argument operations such as `/api/collections-list` take `{}`. Uploads use
`/api/collection-upload-file` with `collection`, a plain `filename` and
`content_base64`, consistently across REST, Python, CLI and admin MCP.
Paths refer to the server filesystem; source-root restrictions still apply.

REST uses administrative authentication, never the query-only MCP token.
The local loopback UI remains usable without a token when none is configured.
If `RAGDBMAN_AUTH_TOKEN` is configured, it protects all REST and UI access.

## Corpus retrieval

`corpus_query` uses one `collections` list for one or many collections. Modes:
`keyword`, `semantic`, `hybrid`, `structured`. Structured mode is filter-only,
accepts an empty query, and is supported for documents/source code, not cards.
`perspective=expert` weights card applicability and counter-indications;
ordinary documents report a warning and use their normal retrieval.

The global `limit` defaults to 5 and is capped at `search.max_top_k`. `minimum_score`
is an optional per-collection cutoff, not a calibrated probability; leave it
null to use card defaults and no ordinary-document cutoff. `filters` accepts
`source_extensions`, `source_ids`, `path_prefix`, `keywords` and `numeric`.
Unsupported fields/card filters fail the affected collection, never silently
broaden retrieval. Inspect `warnings` and `collections_searched`.

`include_text` and `include_links` default to true. `include_graph_context=null`
automatically enriches source-code results when graph support is enabled; false
disables it. `format=raw` returns the complete canonical envelope; `format=llm`
returns UTF-8 text/plain with readable evidence. See [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).

## Errors and confirmations

Request-model errors use HTTP 422 validation details. Application errors use
`{"code":"...","message":"..."}` with optional context. Unknown fields are
rejected. Invalid card YAML uses `KNOWLEDGE_CARD_INVALID`/422, and duplicate
card IDs use `KNOWLEDGE_CARD_DUPLICATE`/409 without replacing the original card.

Deletion, file removal, root removal and rebuild require `confirm=true`.
`scan_start` with `prune_missing=true` also requires confirmation. These checks
apply in Python as well as the CLI/REST/MCP adapters.

## MCP and progress

The `/mcp/query` profile exposes only `corpus_describe`, `corpus_query` and
`corpus_graph`. `/mcp/admin`, disabled by default, exposes the complete canonical
catalog. Every tool takes flat arguments and declares all four boolean hints.
See [MCP.md](MCP.md) for authentication, visibility and SDK requirements.

Job responses include persistent progress total/discovered/processed/counts,
percent and phase, plus elapsed and estimated remaining seconds. Estimates can
be null during discovery/finalization; resume resets the attempt. Live UI
progress remains at `GET /collections/{name}/jobs/{job_id}/events` as SSE
`progress` messages. This streaming UI route is not another query operation.

UI query pages are `/corpus-query` and `/collections/{name}/corpus-query`; graph
pages are `/corpus-graph` and `/collections/{name}/corpus-graph`. Browser access
retains administrative authorization. Retrieved evidence is untrusted data,
not permission to execute commands or bypass confirmation.
