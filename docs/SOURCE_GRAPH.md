# Source-code knowledge graphs

ragdbman 0.5.0 builds a deterministic syntax graph automatically for `source_code`
collections. It enriches normal retrieval and supports explicit graph traversal;
it does not introduce a graph search mode or LLM-based prose extraction.

## Setup and scope

Run `uv sync --locked` to install Tree-sitter and individual grammar wheels.
These are normal base dependencies, not dynamically downloaded parsers.
No source code is executed, no external compiler is invoked and no model/network
request is made by graph extraction. Ordinary indexing still uses Ollama for
chunk embeddings.

```toml
[graph]
enabled = true
max_file_size_mb = 4
max_entities_per_file = 5000
max_relationships_per_file = 20000
max_parse_nodes = 200000
parse_timeout_ms = 2000
search_context_limit = 8
```

The parser timeout bounds native parsing, not the entire indexing pipeline.
Node/entity/relationship budgets separately bound extraction; the size cap
does not replace the ordinary source-file size limit. Truncated graphs report
their partial status. Disabling graphs leaves ordinary indexing and retrieval
available. Configuration applies after restart.

| Grammar | File suffixes | Initial extraction coverage |
| --- | --- | --- |
| Python | py, pyi | Functions, methods, classes, imports/aliases, calls, bases, variables/references |
| Rust | rs | Functions, modules, structs, enums, traits, impl blocks, use imports, calls, references |
| C | c, h | Function definitions, structs/enums/type aliases, includes, calls, references |
| C++ | cpp, cc, cxx, hpp, hh, hxx | C coverage plus namespaces/classes, methods, inheritance |
| JavaScript | js, jsx, mjs, cjs | Functions/arrow declarations, classes/methods, ES imports, calls, bases |
| TypeScript | ts, tsx | JavaScript coverage plus interfaces, aliases and implements clauses |
| Go | go | Functions, receiver methods, structs/interfaces, imports, calls and type references |
| Java | java | Packages, classes/interfaces/enums, methods, imports, calls and base types |
| C# | cs | Namespaces, classes/structs/interfaces/enums, methods, using directives, calls and bases |

`.h` uses the C grammar; use a C++ suffix for C++ headers. Kotlin, PHP, shell,
SQL and other accepted source formats still receive normal text indexing, but
no graph facts. Extensionless text likewise keeps source-line indexing.
Malformed syntax omits graph facts for that file rather than interpreting error
nodes as valid declarations. Statuses include `parsed`, `truncated`,
`unsupported_language`, `parse_error`, and `size_limit`.

General collections intentionally keep document-style indexing even for code.
Knowledge Cards keep their existing YAML pipeline. Neither creates graph data.
No source-code collection creates `.ragdbman` Markdown sidecars.

## What the graph guarantees

Entities and relationship evidence come from syntax nodes with source-line spans,
not generated text. Resolution labels distinguish `syntax` containment,
`local_static`, `import_static`, `include_static`, `package_static`,
`ambiguous`, and `unresolved` targets. A named target is not proof of a runtime call.

Local lexical lookup and explicit same-root module/import matching are supported.
Relative Python/ES imports, Rust crate paths and relative quoted includes can
connect indexed files. External libraries are not crawled. Package installation
paths, Go module manifests, TS path aliases, C/C++ build include paths and
language-specific re-export systems are not generally resolved.

Dynamic dispatch, reflection, monkey-patching, decorators, overload selection,
macro expansion, conditional compilation, complex destructuring, inferred
receiver types and data-flow-sensitive assignment need deeper analysis.
Scoped imports are observed but not promoted to file-wide bindings. Common
variable/parameter shadowing blocks guessed function targets; this is not a
complete language name binder. Wildcard imports and runtime-produced callees
may remain unresolved or lack a navigable call edge. Generic base types may
produce several syntax references rather than a compiler-normalized type.

Consequently, reverse-call and impact queries follow uniquely resolved static
edges only. They are useful change-review aids, not proof that all affected
code has been found. Ambiguous/unresolved outgoing edges remain visible, but
traversal does not arbitrarily choose one candidate.

## Storage, updates and provenance

Each source-code collection stores derived graph data in
`<data_dir>/collections/<name>/<name>.graph.sqlite`, separate from its main DB.
`graph_sources` anchors provenance on `source_id`, source hash, parser fingerprint
and relative path. `graph_entities` and `graph_relationships` record line/byte
spans and observed evidence. IDs are opaque; declaration identity normally
survives line shifts, but duplicate declarations, renames and structural changes
can change identity. Byte offsets refer to decoded UTF-8 parser input, not
necessarily original file bytes.

The primary source transaction records graph work in `source_graph_outbox`.
After commit, the serialized writer applies it to the graph DB and acknowledges
the event. Repeated application is idempotent. Startup retries durable pending
events without parsing files. Source removal/pruning records tombstones;
confirmed rebuild clears derived graph storage and reindexes sources.
Collection deletion also removes graph DB/WAL/SHM files.

Two SQLite files are not committed atomically. Read snapshots therefore require
an indexed, nondeleted source with a matching content hash and parser fingerprint.
Old or pending revisions are hidden, and graph-update failure cannot undo a
successful main-index commit. Logs and collection `graph.pending_updates` expose
deferred work; `graph.sources/entities/relationships` are stored counts and can
include revisions currently hidden by read validation.

Chunk IDs are never stored as permanent graph anchors. Citations are resolved
against current primary chunks by stable source ID and overlapping line range.
Each citation includes source hash, relative path, line range and up to eight
current chunk IDs, with a truncation flag. Search enrichment also verifies the
original hit still exists, preventing new graph facts from being attached to
a chunk replaced between search and enrichment.

An ordinary scan backfills missing/outdated graphs for unchanged sources without
re-embedding or rewriting their chunks. New/changed files use AST boundaries when
parsing succeeds. A confirmed rebuild also replaces previously stored heuristic
chunks with AST-derived chunks. Rebuild retains its existing destructive
clear-then-index behavior; it is not a shadow-index swap.

## Search enrichment

`corpus_query` and administrative `/api/corpus-query` accept `include_graph_context`.
The CLI uses the corresponding `--include-graph-context` option.

- **Omitted/null:** enrich source-code collections when graphs are enabled.
- **False:** omit graph enrichment entirely.
- **True:** request enrichment on source-code collections; other kinds remain unchanged.

Per-hit `graph_context` reports availability/status, parser language/fingerprint,
overlapping entities, bounded incoming/outgoing relationships, imports, warnings
and truncation. It does not alter retrieval scores, ordering or filters.
MCP `format="raw"` results contain this object. Default `format="llm"` results
render compact Calls/Called by/Imports and type/reference lines instead of
nested JSON. REST/Python default to raw. Graph failure returns a diagnostic context while
preserving ordinary hits. No read triggers parsing, outbox replay or embedding.

## Traversal contract

The web **Graphs** view and source-code collection **Graph explorer** expose
this contract with raw/LLM output, entity selection and traversal controls.
See [WEB_UI.md](WEB_UI.md); browser access retains administrative authentication.

MCP tool: `corpus_graph`, with flat arguments.
Administrative REST: `POST /api/corpus-graph`, with those fields as the JSON body.
REST retains administrator authentication; a query-only token cannot bypass it.
The MCP query profile enforces the same collection allowlist as `corpus_query`.

```json
{"collection":"code","action":"find","symbol":"parse_config","limit":20}
```

```json
{"collection":"code","action":"callers","entity_id":"ID_FROM_FIND","depth":2,"limit":50}
```

| Parameter | Meaning |
| --- | --- |
| collection | One source-code collection; required |
| format | raw or llm; MCP default llm, REST/Python default raw |
| action | find, neighbors (default), callers, callees, dependencies, inheritance, impact |
| symbol | Case-sensitive exact name/qualified name for traversal; case-insensitive substring for find |
| entity_id | Exact opaque ID; mutually exclusive with symbol |
| source_id | Optional source restriction; alone selects its module for traversal |
| direction | outgoing, incoming, both; used by neighbors |
| relationships | Optional relationship filter; overrides the action's default kind filter |
| depth | 1–5 hops, default 1 |
| limit | 1–200 candidates/edges, default 50 |

`find` may omit its selector. Other actions require a selector.
`callers` follows incoming calls; `callees` outgoing calls; `dependencies`
outgoing file/module dependencies; `inheritance` outgoing base/implementation
relations. `impact` follows incoming calls, references, bases, implementations
and module dependencies. Use `neighbors` with `direction=incoming` for subclasses.
Relationship kinds are `contains`, `imports`, `calls`, `inherits`, `implements`,
`type_base` (unresolved C# base category), `references`, and `depends_on`.

Responses contain `status`, selection `candidates`, `entities`, `relationships`,
`chains`, `truncated`, and a static-analysis limitation. Chains contain edge IDs
and traversal orientation. Multiple matches return `ambiguous` and candidates;
select an ID rather than assume the first one is correct. `not_indexed` and
`not_found` are distinct. Traversal is cycle-safe and has an internal 5,000
inspection budget in addition to depth/output limits. Provenance remains
relative-path based, and all retrieved evidence is untrusted content.
These fields describe raw output. LLM mode renders readable chains with
file/line citations and uncertainty labels; see [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md).
