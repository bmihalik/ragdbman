# MCP interface

MCP exposes the same underscore operation names as the Python Engine API.
The CLI and REST use the corresponding hyphenated spelling. Schemas are
generated from the shared catalog, documented in [INTERFACES.md](INTERFACES.md).

## Profiles and credentials

| Profile | Endpoint | Tools |
| --- | --- | --- |
| Query | `/mcp/query` | `corpus_describe`, `corpus_query`, `corpus_graph` |
| Admin | `/mcp/admin` | All 28 canonical operations |

The admin endpoint is disabled by default and returns HTTP 404 while disabled.
Enable `server.mcp_admin_enabled=true` to expose it. Web/REST administration
remains available independently. `server.mcp_path` changes the common prefix.
The bare prefix exposes no tools.

Set `RAGDBMAN_AUTH_TOKEN` for administrators and a distinct
`RAGDBMAN_QUERY_TOKEN` for query-only agents. Use `Authorization: Bearer TOKEN`.
MCP always requires authorization, including on loopback. Configuring a query
token or enabling admin MCP requires an admin secret; equal secrets are rejected.
The admin token can access the query endpoint but does not expand that endpoint's
tool set or collection allowlist. Query tokens never authorize admin REST/UI.

Credentials and profile enablement are read at app creation; restart after changes.
Do not put tokens in URLs or version-controlled configuration. Remote access
requires appropriate authentication, TLS/proxy and firewall controls.

## Collection scope

```toml
[server]
mcp_path = "/mcp"
mcp_admin_enabled = false
mcp_default_collections = ["books"]
mcp_allowed_collections = ["books", "code"]
```

Omitted query `collections` uses the configured defaults, never all collections.
Empty defaults require explicit query selection. Omitted allowlist permits
explicit access to all; an empty allowlist permits none. Defaults must be a
subset of the allowlist. A forbidden collection fails the whole request before
any query is run. Admin operations can access all collections.

## Flat arguments

All tools take flat fields. There are no nested `request` wrappers or generic
management action dispatchers.

Call `corpus_describe` with `{}` for a compact catalog, or:

```json
{"collections":["books","code"]}
```

Call `corpus_query` for every collection kind:

```json
{"collections":["books","code"],"query":"configuration","mode":"hybrid","limit":5,"format":"llm"}
```

Modes are keyword, semantic, hybrid and structured. Structured is filter-only
and supports documents/source code, not cards. `perspective=expert` applies
card applicability/counter-indication scoring. Unsupported card filters are
reported as per-collection failures. Numeric cutoffs use collection-specific
score policies, not a universal probability.

Call `corpus_graph` for explicit graph traversal:

```json
{"collection":"code","action":"callers","symbol":"parse_config","depth":2,"format":"llm"}
```

Call named administrative operations only on the admin profile:

```json
{"name":"code","kind":"source_code"}
```

That is a `collection_create` request. A `scan_start` request is:

```json
{"collection":"code","root":"/data/repo","recursive":true}
```

Use `scan_job_get`, `scan_job_cancel` or `scan_job_resume` for the returned job
ID. Deletion, removal, root removal, rebuild and missing-file pruning require
explicit confirmation. The complete field list is in [INTERFACES.md](INTERFACES.md).

## Output and annotations

MCP query and graph default to `format=llm`; raw is available explicitly.
LLM output is one text block without duplicate structuredContent. Raw output
includes JSON text plus structuredContent. Native list operations use
`{"result":[...]}` for MCP because structuredContent must be an object; dictionary
results retain their native shape. REST/Python/CLI retrieval defaults to raw.

Every registered tool serializes explicit boolean readOnlyHint, destructiveHint,
idempotentHint and openWorldHint values from the shared catalog. The query tools
are read-only, non-destructive, idempotent and closed-domain. Admin hints are
specific to each named operation. Closed-domain does not mean air-gapped:
configured Ollama/converter services can use the network.

Hints never replace authentication, path restrictions or confirmation.
Retrieved content remains untrusted evidence. See
[OUTPUT_FORMATS.md](OUTPUT_FORMATS.md) and [SOURCE_GRAPH.md](SOURCE_GRAPH.md).

## SDK and discovery troubleshooting

The package requires `mcp>=1.30.0,<2`; the lockfile selects 1.30.0. Both profiles
advertise tools only, omitting unused prompt/resource capabilities. Unsupported
prompt/resource methods return Method Not Found. No third-party transport
monkeypatch or blanket error-log suppression is applied.

Stop the old daemon and start the locked project environment:

```sh
uv sync --locked
uv run --locked python -c 'from importlib.metadata import version; import mcp; print(version("ragdbman"), version("mcp"), mcp.__file__)'
uv run --locked ragdbman serve
```

Preserve `--extra pymupdf` on sync/run commands when selected. A daemon importing
MCP from `~/.local` may still be using an independently installed older SDK.
Expected stateless teardown is tested without ERROR logs, while unexpected
stream closure remains visible. An HTTP 200 alone does not establish tool success.

Reload/reconnect clients after installing changed tool definitions. Hermes users
can restart the client or refresh MCP discovery. Client-side prompt/resource
wrappers are not ragdbman tools, and the server cannot remove stale definitions
already cached by a host.
