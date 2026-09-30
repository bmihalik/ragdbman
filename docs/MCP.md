# The corpus MCP interface

ragdbman exposes one small operational interface for all collection kinds, with
administration available on a separate, optional endpoint. Both endpoints use
stateless MCP Streamable HTTP with the official SDK.

## Tools-only discovery and SDK requirement

Version 0.5.3 requires `mcp>=1.30.0,<2`; `uv.lock` selects 1.30.0. Both profiles
advertise tools but omit `prompts` and `resources` from the initialization
capabilities. They do not register handlers for prompt listing/retrieval,
resource listing/reading, resource templates or resource subscriptions.
Requests for those methods return JSON-RPC error `-32601` (Method Not Found).
The three query tools and six admin tools below are unchanged.

This is an explicit boundary around FastMCP's default registration of empty
prompt/resource managers, not a new retrieval interface; the upstream behavior
is visible in [FastMCP 1.30.0](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v1.30.0/src/mcp/server/fastmcp/server.py).
No database changes, rescanning or re-embedding are needed for this patch.

### Applying the patch

Stop the existing daemon before replacing its source and installing dependencies.
From the release directory, use the isolated locked environment:

```sh
uv sync --locked
uv run --locked ragdbman serve
```

If you use optional extras, preserve them in both commands, for example
`uv sync --locked --extra pymupdf` and
`uv run --locked --extra pymupdf ragdbman serve`. Do not assume an old daemon
loading packages from `~/.local` is using the project's lockfile.
Check the selected SDK with:

```sh
uv run --locked python -c 'from importlib.metadata import version; print(version("ragdbman"), version("mcp"))'
```

Reconnect the MCP client to refresh its cached initialization capabilities.
Hermes supports `/reload-mcp` or a restart and can expose prompt/resource
operations as client-side tool wrappers; those are not ragdbman's `corpus_`
tools ([Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference/)).
For older or non-capability-aware Hermes installations, explicitly disable
the utility wrappers by merging this fragment into the existing server entry,
preserving its URL and authentication settings:

```yaml
mcp_servers:
  ragdbman:
    tools:
      resources: false
      prompts: false
```

These utility switches are documented in the
[Hermes MCP configuration reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference/).
The server cannot delete tool definitions already cached by a client.

### Stateless teardown logs

`Terminating session: None` can remain an ordinary INFO message for this
stateless transport. SDK 1.30.0 handles a closed read stream after termination
at DEBUG while retaining ERROR logging for unexpected closure, as shown in
the [SDK transport implementation](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v1.30.0/src/mcp/server/streamable_http.py).
ragdbman does not suppress all `ClosedResourceError` exceptions or filter
transport ERROR logs. An unexpected closure still needs investigation; an
HTTP 200 status alone does not prove that the JSON-RPC operation succeeded.

## Profiles and authentication

| Profile | Endpoint | Exposed tools |
| --- | --- | --- |
| Query | `/mcp/query` | `corpus_describe`, `corpus_query`, `corpus_graph` |
| Admin | `/mcp/admin` | All three query tools plus `corpus_manage`, `corpus_ingest`, `corpus_job` |

The endpoint prefix is configurable with `server.mcp_path`. Admin MCP is disabled
by default and returns HTTP 404 while disabled. The bare prefix exposes no tools.
The web interface remains capable of administration independently.

Set two distinct secrets in the daemon environment:

```sh
export RAGDBMAN_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export RAGDBMAN_QUERY_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run --locked ragdbman serve
```

Store stable secrets securely for normal operation; generating them again changes
the client credentials. For systemd, use a protected EnvironmentFile as shown in
`deploy/ragdbman.service`. Never commit secrets to TOML or source control.

- Query agents send `Authorization: Bearer <query token>` to `/mcp/query`.
- Administrators send `Authorization: Bearer <admin token>` to `/mcp/admin`.
- The admin token can also use the query endpoint, but that endpoint still has
  only three read-only tools and applies the query-profile collection allowlist.
- The admin profile can inspect/query every collection. Never give its token to
  an agent intended to have query-only access.
- Query tokens cannot access any web/REST route or the admin MCP endpoint.
- MCP requests without authorized Bearer credentials are rejected, even locally.
- Setting a query token or enabling admin MCP requires an administrator secret;
  equal secrets are rejected at startup. Any configured administrator secret
  protects web/REST administration even when `web_auth_mode="local"`.
- For the browser, use any username and the admin token as the Basic-auth password
  in `password` mode or protected local mode. In `oauth_proxy` mode use the
  configured authenticated proxy.

With no MCP credentials configured and local web mode, the loopback web UI
remains a trusted standalone administrator interface, while anonymous MCP is
unavailable. Authentication does not protect against an actor that can read the
daemon's secrets, alter its configuration or access its operating-system account.
Remote deployments still require TLS/proxy/firewall controls.

Credentials are snapshotted at app creation. Restart after changing credentials,
profile enablement or collection permissions; there is no request-controlled role.

## Default scope and collection permissions

Example TOML:

```toml
[server]
mcp_path = "/mcp"
mcp_admin_enabled = false
mcp_default_collections = ["programming", "engineering"]
mcp_allowed_collections = ["programming", "engineering", "manuals"]
```

`mcp_default_collections=[]` requires explicit selection in `corpus_query`.
Omitting a query's `collections` never means “search every collection.”
`mcp_allowed_collections` omitted permits explicitly selected access to all
collections; setting it to `[]` permits none. Defaults must be a subset of the
allowlist. Selecting any forbidden collection fails the whole request without
querying permitted collections or disclosing forbidden collection details.

## Discover and inspect

Call `corpus_describe` with `{}` for a compact catalog of accessible collections.
For details:

```json
{"collections": ["programming", "manuals"]}
```

The result includes descriptions, content kinds, counts and search capabilities.
Detailed entries include field names, embedding settings and defaults. Operational
discovery does not expose database paths, managed directories or source roots.

## One query contract

```json
{
  "query": "Find an algorithm for unweighted shortest paths",
  "collections": ["programming", "manuals"],
  "mode": "hybrid",
  "perspective": "expert",
  "limit": 5,
  "minimum_score": null,
  "filters": {}
}
```

- `collections`: optional nonempty array; one name and many names use the same tool.
- `mode`: `keyword`, `semantic`, `hybrid`; default `hybrid`.
- `perspective`: `general` or `expert`; default `general`. Expert selects the
  positive/negative/description formula only for Knowledge Cards. Ordinary
  documents retain general retrieval and report a warning rather than pretend
  to have applicability vectors.
- `limit`: positive global maximum, default 5, capped by `search.max_top_k`.
- `minimum_score`: optional finite 0–1 per-collection cutoff. Explicit zero is
  honored. Cards use their configured cutoff if omitted; documents have no cutoff
  if omitted. This is not a universal probability threshold: see scoring below.
- `filters`: document filters for extension, source IDs, path prefix, keywords and
  numeric fields, following the REST filter schema in [API.md](API.md). Unknown
  numeric fields or nonempty filters on card collections fail that collection
  explicitly. Filters are never silently discarded by the corpus interface.
- `include_graph_context`: null/omitted enables graph enrichment for source-code
  collections only; false disables enrichment. True does not build graphs for
  other collection kinds. This adds context, not another retrieval pass.
- `format`: `llm` by default for MCP, returning readable text without duplicate
  nested JSON; `raw` returns the complete structured payload. REST/Python
  defaults remain raw. See [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).

Modes describe retrieval channels; perspective describes the card scoring strategy.
There is no separate single-query, multi-query or card-query MCP tool.
Filter-only `structured` mode remains available in administrative REST/UI, not
as an extra operational MCP mode.

### Ranking and failure semantics

Each collection searches with its recorded embedding model. Its candidates receive
local ranks, then contribute `1 / (search.rrf_k + local_rank)` to a cross-collection
result list. Global ordering uses these rank scores, then collection name and local
rank for deterministic ties, not incompatible raw metric values. Duplicate sources
across independently indexed collections remain separate results deliberately.

Per-result relevance identifies the raw score policy:

- Cards: confidence-weighted cosine/formula or normalized BM25; hybrid orders
  by within-card rank fusion and exposes the strongest surviving channel score.
- Document semantic: `1 / (1 + L2 distance)`.
- Document keyword: nonnegative BM25 strength, not normalized confidence.
- Document hybrid: configured weighted reciprocal rank fusion.

`minimum_score` applies to each collection's own score policy before global fusion.
A threshold such as 0.65 is meaningful for cards but can exclude all document
hybrid results because RRF scores are much smaller. Use null for collection
defaults or query a homogeneous scope when applying one numeric cutoff.

Successful collections are listed separately from warnings. If some fail, the
remaining results are returned with diagnostics. If all fail, the response is
empty with warnings, not falsely presented as successful retrieval. Query-wide
validation and authorization errors return MCP tool errors. Card hybrid retrieval
can fall back to keyword when Ollama is unavailable and reports that fallback.
Semantic-only failures are not hidden.

## Raw reply envelope and readable evidence

With `format="raw"`, `corpus_query` returns MCP `structuredContent` and a JSON
text representation with:

```text
query
effective_options: limit, ranking, per-collection mode/perspective/cutoff/policy/filters
collections_searched
warnings[]
results[]
  rank
  kind: document | source_code | knowledge_card
  collection
  title
  relevance: score, policy, vector, keyword, collection_rank, fusion_score
  provenance
  content
  graph_context (source-code results when enabled)
```

The default `format="llm"` instead returns one text block without
`structuredContent`, with numbered result headings, scores, location labels
and compact natural-language graph context. Untrusted labels are escaped,
single-line inline code; card content is fenced YAML with literal multiline
code. Adaptive fences preserve embedded backticks and trailing newlines.
Document/source snippets use text fences and retain truncation warnings.
Full examples and uncertainty semantics are in [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).

Only top-level card IDs are removed; references, nested values and code text are
preserved. Ordinary operational provenance omits internal IDs and filesystem paths.
Source graph context deliberately includes opaque entity/source/chunk IDs for
navigation and citation, with relative source paths, never generated absolute
filesystem paths. Retrieved content remains untrusted evidence, never instructions.

## Explicit source graph traversal

`corpus_graph` is a read-only tool available on both profiles and restricted by
the query profile's collection allowlist. It never parses, indexes or calls an LLM.

```json
{"request":{"collection":"programming","action":"callers","symbol":"parse_config","depth":2,"limit":50}}
```

Actions are `find`, `neighbors`, `callers`, `callees`, `dependencies`,
`inheritance`, and `impact`. Select a symbol or opaque `entity_id`; `source_id`
can restrict selection or select the file module. Ambiguous names return
candidates instead of guessing. See [SOURCE_GRAPH.md](SOURCE_GRAPH.md) for the
full contract, static-analysis limitations and provenance semantics.
Set `request.format="raw"` for structured graph data; omitted format defaults
to `llm` on MCP. Graph `find`/ambiguous replies retain candidate IDs for exact
follow-up selection, while ordinary readable chains omit metadata IDs.

## Administration contracts

Enable `server.mcp_admin_enabled=true` and restart to expose the admin endpoint.
Each tool accepts one `request` object whose `action` selects a strict schema;
irrelevant and unknown fields are rejected.

### corpus_manage

| Action | Parameters besides action |
| --- | --- |
| `create` | `name`, optional `kind`, `description`, `source_roots`, embedding/chunk overrides |
| `inspect`, `manifest`, `roots`, `vacuum` | `collection` |
| `update` | `collection`, `description` |
| `delete` | `collection`, `confirm=true`, optional `delete_files` |
| `register_root` | `collection`, `path`, optional `recursive` |
| `unregister_root` | `collection`, `root_id`, `confirm=true` |
| `sources` | `collection`, optional `limit`, `offset` |
| `source` | `collection`, `source_id` |
| `health` | none |

Example:

```json
{"request": {"action": "create", "name": "principles", "kind": "knowledge_cards"}}
```

Names, models and chunk strategies remain immutable after creation; update edits
the description. There is no rename action or arbitrary method/SQL dispatcher.

### corpus_ingest

| Action | Parameters besides action |
| --- | --- |
| `add_file` | `collection`, `path` |
| `upload` | `collection`, `filename`, `content_base64` |
| `scan` | `collection`, `root`, optional `recursive`, `prune_missing`; `confirm=true` required for pruning |
| `rebuild` | `collection`, `confirm=true` |
| `remove_source` | `collection`, `source_id`, `confirm=true`, optional `delete_original_managed_file` |

Uploads use unique names within the managed directory and cannot supply a path.
Decoded bytes obey the configured file-size limit; failed indexed uploads remain
available for diagnostics/retry. Source-root allowlists and original-file deletion
restrictions apply equally to every ingestion surface.

### corpus_job

| Action | Parameters besides action |
| --- | --- |
| `list` | `collection`, optional `status`, `limit` |
| `inspect`, `cancel`, `resume` | `collection`, `job_id` |

Job IDs must belong to the specified collection. Cancellation is cooperative and
resume is explicit. Management tool replies wrap their outcome under `result`.

## Web and REST

The browser keeps its full administrative workflows whether admin MCP is enabled
or disabled. It uses the existing REST endpoints; authenticated administrators
can also use `GET /api/corpus` and `POST /api/corpus/query` for the unified service.
Query-only tokens cannot use REST as an administrative bypass.
