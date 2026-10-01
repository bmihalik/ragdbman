# Retrieval output formats

ragdbman 0.5.1 formats retrieval evidence in the service itself. Clients can
choose machine-readable JSON or model-ready text without implementing a graph
schema renderer. This is deterministic presentation, not another LLM call,
summary-generation step, retrieval pass or graph search mode.

## Defaults and supported surfaces

| Surface | Default | Selecting a format |
| --- | --- | --- |
| MCP `corpus_query` | `llm` | Top-level `format` argument |
| MCP `corpus_graph` | `llm` | Top-level `format` |
| REST `/api/corpus-query` | `raw` | JSON body `format` |
| REST `/api/corpus-graph` | `raw` | JSON body `format` |
| Python `CorpusQuery`, `GraphRequest` | `raw` | Model field `format` |
| CLI corpus-query / corpus-graph | `raw` | `--format raw`, `llm` or local `table` |

Only `raw` and `llm` are accepted, case-sensitively. Null and unknown values are
validation errors. The MCP graph request schema uses a specialized default;
the ordinary Python/REST `GraphRequest` remains raw by default.

There is no new `corpus_search` alias. The unified search tool remains
`corpus_query`; query/admin profiles expose three/28 tools. Discovery
and named management operations use raw payloads. Knowledge Cards use the same
corpus route and content envelope as other collection kinds. The web UI defaults to raw
output and now offers a Raw JSON/LLM text selector, graph-context controls,
and graph traversal. See [WEB_UI.md](WEB_UI.md) for the card endpoint mappings.

## Raw mode

Raw mode returns the existing structured retrieval envelope, including graph
entities, relationships, revision provenance, chunk citations, score components,
diagnostics and truncation flags where applicable. It does not expand the
existing authorization scope or return arbitrary database columns.

MCP raw mode supplies the payload as `structuredContent` and a JSON text block
for protocol compatibility. REST returns `application/json`; Python returns the
ordinary dictionary. Select this mode for integrations that consume the schema.

```json
{"query":"parse_config","collections":["code"],"mode":"hybrid","format":"raw"}
```

## LLM mode

MCP returns one readable text content block and deliberately omits
`structuredContent`. This prevents frameworks from feeding the entire nested
JSON to the model alongside the formatted text. REST returns UTF-8 `text/plain`
containing Markdown, not a JSON-quoted string; Python returns a string.

The renderer shows numbered results, score and score policy, collection,
file/line/page/slide/time location when available, and the actual retrieved
excerpt. Source results add function names and compact `Calls`, `Called by`,
`Imports`, inheritance and reference lines from the returned graph context.
Multiple functions are identified by name instead of attributing all edges to
the first function. File imports are labelled as syntax observations, not proof
that an external dependency was resolved.

Illustrative layout (symbols, excerpt and score are example values, not output
from a repository scan):

~~~~text
## Result 1 (score: 0.87)

Source code | Collection: ` code ` | Score policy: ` inverse_l2 `

File: ` src/config/loader.rs `, lines 10-18 | function: ` parse_config() `

```text
fn parse_config() {
    read_file();
    validate_schema();
}
```

Static source graph context (best-effort static analysis, not runtime verification).
Calls: ` parse_config() ` -> ` read_file() `; ` parse_config() ` -> ` validate_schema() `
Called by: ` main() ` -> ` parse_config() `
File imports (observed syntax): ` std.fs `, ` serde.Deserialize `
~~~~

ragdbman does not invent an explanatory paragraph about what a function does.
Comments/docstrings already in the excerpt remain available to the model.
Symbol separators reflect the graph's normalized names, not a language-specific
pretty-printer. Scores retain their real policy and use six significant digits,
including scientific notation for small values; they are not recast as
probabilities or normalized to match the illustrative example. Cross-collection
ordering remains rank fusion.

Unknown targets retain `[unresolved]` or `[ambiguous]`. Missing/stale graph data,
excerpt truncation, graph budgets, partial collection failures and skipped
filters remain visible. Omitted relationships are never described as proof that
no relationships exist. Knowledge Cards remain labelled, fenced YAML, with
literal multiline code preserved.

Retrieved names, filenames and other labels are quoted as single-line inline
code with control/newline escaping. Excerpts use adaptive fences so embedded
backticks cannot break the surrounding block. These boundaries help distinguish
evidence from navigation; they are not a guarantee against semantic prompt
injection. Retrieved text must still be treated as untrusted data.

## Explicit graph queries

```json
{"request":{"collection":"code","action":"callers","symbol":"parse_config","depth":2,"format":"llm"}}
```

Graph replies show selected symbols and file locations, then relationship chains
with normal words such as “calls”, “inherits from”, or “depends on”. Each step
keeps the evidence's file/line citation and indicates incoming/outgoing traversal.
Routine chains omit relationship IDs, parser revisions, source hashes and
nested entity dictionaries.

One intentional exception: `find` and ambiguous selection responses include an
`entity_id` beside each candidate so the next tool call can select it exactly.
These are navigation handles, not repeated provenance metadata. Choose
`format="raw"` whenever full structured graph data is needed.

## Operational guarantees

Changing the format does not alter scope, authorization, filters, ranking,
embedding requests or graph resolution. `include_graph_context=false` still
suppresses search enrichment in either format. General collections are not
parsed as code, and Knowledge Cards do not acquire graph extraction.

Formatting tests exercise both MCP profiles and the REST/Python contracts using
real parsers and SQLite with deterministic embedding doubles. No claim is made
that every external LLM client framework has been independently tested.
