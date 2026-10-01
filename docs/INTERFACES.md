# Canonical interface reference

Generated from `ragdbman.operations.OPERATIONS`. Run
`uv run python tools/generate_interface_reference.py` to refresh, or add
`--check` to verify. This catalog is shared by CLI, REST and MCP dispatch.

CLI names and REST paths use hyphens. Python Engine methods and MCP tools
use underscores. All REST operations use POST with a JSON object body,
including read-only queries; HTTP method alone does not describe side effects.
MCP arguments are the same flat object, never a nested `request` wrapper.

The query MCP profile exposes only the three corpus operations. The optional
admin profile exposes all 28 operations. Python/REST calls are administrative;
query MCP additionally enforces the configured collection allowlist.

## Operation names

| CLI command | Python method / MCP tool | REST endpoint | Query MCP |
| --- | --- | --- | --- |
| `corpus-query` | `corpus_query` | `/api/corpus-query` | yes |
| `corpus-graph` | `corpus_graph` | `/api/corpus-graph` | yes |
| `corpus-describe` | `corpus_describe` | `/api/corpus-describe` | yes |
| `collections-registry-repair` | `collections_registry_repair` | `/api/collections-registry-repair` | no |
| `collections-list` | `collections_list` | `/api/collections-list` | no |
| `collection-get` | `collection_get` | `/api/collection-get` | no |
| `collection-create` | `collection_create` | `/api/collection-create` | no |
| `collection-config-update` | `collection_config_update` | `/api/collection-config-update` | no |
| `collection-delete` | `collection_delete` | `/api/collection-delete` | no |
| `collection-list-files` | `collection_list_files` | `/api/collection-list-files` | no |
| `collection-get-file` | `collection_get_file` | `/api/collection-get-file` | no |
| `collection-add-file` | `collection_add_file` | `/api/collection-add-file` | no |
| `collection-upload-file` | `collection_upload_file` | `/api/collection-upload-file` | no |
| `collection-remove-file` | `collection_remove_file` | `/api/collection-remove-file` | no |
| `collection-list-roots` | `collection_list_roots` | `/api/collection-list-roots` | no |
| `collection-add-root` | `collection_add_root` | `/api/collection-add-root` | no |
| `collection-remove-root` | `collection_remove_root` | `/api/collection-remove-root` | no |
| `scan-start` | `scan_start` | `/api/scan-start` | no |
| `scan-jobs-list` | `scan_jobs_list` | `/api/scan-jobs-list` | no |
| `scan-job-get` | `scan_job_get` | `/api/scan-job-get` | no |
| `scan-job-cancel` | `scan_job_cancel` | `/api/scan-job-cancel` | no |
| `scan-job-resume` | `scan_job_resume` | `/api/scan-job-resume` | no |
| `collection-list-keywords` | `collection_list_keywords` | `/api/collection-list-keywords` | no |
| `collection-list-metadata-fields` | `collection_list_metadata_fields` | `/api/collection-list-metadata-fields` | no |
| `collection-export-manifest` | `collection_export_manifest` | `/api/collection-export-manifest` | no |
| `collection-rebuild` | `collection_rebuild` | `/api/collection-rebuild` | no |
| `collection-vacuum` | `collection_vacuum` | `/api/collection-vacuum` | no |
| `health-status` | `health_status` | `/api/health-status` | no |

The CLI also has three local setup commands: `init`, `serve`,
and `fetch-tokenizer`. They are process/setup actions, not remote tools.

## Request fields and behavior

All fields reject unknown keys. `collection` selects an existing collection;
`name` is used by collection create/get/config-update/delete. `collections`
is the list used by corpus discovery/query. File selectors retain `source_id`,
the stable provenance identifier, and are not filenames or Knowledge Card IDs.

Retrieval `format` is raw JSON by default in Python, REST and CLI. MCP query
and graph tools default to `llm`. CLI additionally supports `table` as a local
display mode, not a server-side format. Arrays use comma-separated CLI values;
`filters` is a JSON object. CLI option names replace underscores with hyphens.

### corpus-query

Query one or more document, source-code or Knowledge Card collections. Modes: keyword, semantic, hybrid, structured. Expert perspective applies to cards. Use format=llm for readable evidence or raw for full metadata; structured mode rejects cards.

| Field | Required | Default |
| --- | --- | --- |
| `format` | no | `"raw"` |
| `include_graph_context` | no | `null` |
| `query` | yes | `required` |
| `collections` | no | `null` |
| `mode` | no | `"hybrid"` |
| `perspective` | no | `"general"` |
| `limit` | no | `5` |
| `minimum_score` | no | `null` |
| `filters` | no | `{"source_extensions": [], "numeric": [], "keywords": [], "path_prefix": null, "source_ids": []}` |
| `include_text` | no | `true` |
| `include_links` | no | `true` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### corpus-graph

Read a source-code syntax graph: find, neighbors, callers, callees, dependencies, inheritance or impact. Static resolution is not a runtime call graph.

| Field | Required | Default |
| --- | --- | --- |
| `format` | no | `"raw"` |
| `collection` | yes | `required` |
| `action` | no | `"neighbors"` |
| `symbol` | no | `null` |
| `entity_id` | no | `null` |
| `source_id` | no | `null` |
| `direction` | no | `"outgoing"` |
| `relationships` | no | `null` |
| `depth` | no | `1` |
| `limit` | no | `50` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### corpus-describe

Discover collections or describe selected collections and capabilities.

| Field | Required | Default |
| --- | --- | --- |
| `collections` | no | `null` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collections-registry-repair

Reconstruct the registry from collection databases; no index rebuild. Reject while indexing is active.

| Field | Required | Default |
| --- | --- | --- |
| none | no | `{}` request body |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=true`, `openWorldHint=false`.

### collections-list

List collection configuration and counts for the administrator.

| Field | Required | Default |
| --- | --- | --- |
| none | no | `{}` request body |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-get

Inspect one collection's settings and counts.

| Field | Required | Default |
| --- | --- | --- |
| `name` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-create

Create an empty collection; probes its embedding model. Registering roots does not start scanning.

| Field | Required | Default |
| --- | --- | --- |
| `name` | yes | `required` |
| `description` | no | `null` |
| `source_roots` | no | `[]` |
| `kind` | no | `"general"` |
| `embedding_model` | no | `null` |
| `chunk_size_tokens` | no | `null` |
| `chunk_overlap_tokens` | no | `null` |

Hints: `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=false`, `openWorldHint=false`.

### collection-config-update

Set the description; omission clears it. Kind, embedding model and chunk settings are immutable.

| Field | Required | Default |
| --- | --- | --- |
| `name` | yes | `required` |
| `description` | no | `null` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=true`, `openWorldHint=false`.

### collection-delete

Delete collection indexes with confirm=true. delete_files also deletes managed originals, never external roots.

| Field | Required | Default |
| --- | --- | --- |
| `name` | yes | `required` |
| `confirm` | no | `false` |
| `delete_files` | no | `false` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### collection-list-files

List tracked files, statuses and source IDs with pagination.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `extension` | no | `null` |
| `path_prefix` | no | `null` |
| `status` | no | `null` |
| `limit` | no | `50` |
| `offset` | no | `0` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-get-file

Inspect file metadata and diagnostics by source ID.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `source_id` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-add-file

Index one allowed existing file; wait for completion.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `path` | yes | `required` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### collection-upload-file

Upload base64 content to managed storage and index it.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `filename` | yes | `required` |
| `content_base64` | yes | `required` |

Hints: `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=false`, `openWorldHint=false`.

### collection-remove-file

Remove source index data with confirm=true; optional original deletion is limited to managed files.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `source_id` | yes | `required` |
| `confirm` | no | `false` |
| `delete_original_managed_file` | no | `false` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### collection-list-roots

List registered roots and their IDs.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-add-root

Register an allowed directory without scanning.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `path` | yes | `required` |
| `recursive` | no | `true` |

Hints: `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-remove-root

Unregister a root with confirm=true; keep files and indexes.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `root_id` | yes | `required` |
| `confirm` | no | `false` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=true`, `openWorldHint=false`.

### scan-start

Start incremental directory indexing. Missing-file pruning requires confirm=true.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `root` | yes | `required` |
| `recursive` | no | `true` |
| `prune_missing` | no | `false` |
| `confirm` | no | `false` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### scan-jobs-list

List indexing jobs by collection and optional status.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `status` | no | `null` |
| `limit` | no | `50` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### scan-job-get

Inspect one job's progress, timing and errors.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `job_id` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### scan-job-cancel

Request cooperative cancellation by globally unique job ID.

| Field | Required | Default |
| --- | --- | --- |
| `job_id` | yes | `required` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=true`, `openWorldHint=false`.

### scan-job-resume

Resume paused or failed/partial work, resetting attempt counters.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `job_id` | yes | `required` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### collection-list-keywords

List canonical keyword vocabulary and frequencies.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `query` | no | `null` |
| `limit` | no | `50` |
| `offset` | no | `0` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-list-metadata-fields

List supported numeric/date filter fields.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-export-manifest

Return collection and source metadata, not a database backup.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### collection-rebuild

Clear derived indexes then reindex tracked files; confirm=true required.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |
| `confirm` | no | `false` |

Hints: `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, `openWorldHint=false`.

### collection-vacuum

Reclaim unused primary SQLite pages; does not reindex.

| Field | Required | Default |
| --- | --- | --- |
| `collection` | yes | `required` |

Hints: `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

### health-status

Check engine, vector extension and configured Ollama service.

| Field | Required | Default |
| --- | --- | --- |
| none | no | `{}` request body |

Hints: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`.

## Envelopes and errors

Python and REST return the operation's native dictionary/list, or text for
LLM retrieval. MCP returns text plus structuredContent in raw mode; list
results are wrapped as `{"result": [...]}` because MCP structuredContent
requires an object. Dictionary results are not double-wrapped. LLM output
is one text block without duplicate structuredContent.

Corpus queries report per-collection failures in `warnings` and successful
collections in `collections_searched`. A successful HTTP response can contain
zero successful collections; inspect these fields. Validation/authentication
errors fail the request. CLI raw/table queries return exit 3 if every
collection fails; readable LLM mode retains failures in text.

Explicit confirmations are required for collection deletion, file removal,
root removal, rebuild, and scans with missing-file pruning. They apply at
the Engine and shared dispatch boundaries, not only in a web dialog.

No compatibility aliases, old search endpoints or action-dispatch MCP
management tools are registered. Existing SQLite data does not need rebuilding.
