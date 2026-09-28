# Web query and graph explorer

The administrative web interface exposes raw/LLM query formats and read-only
source graph traversal. It uses the existing REST services and retains their
authentication, collection-kind restrictions, ranking and filtering semantics.

## Query formats

Open a collection's **Search** page, or **Search all**:

- **Raw JSON:** the default. Existing result cards and per-result metadata
  inspection remain available. Expand **Full raw response** to inspect or copy
  the complete response envelope.
- **LLM text:** show the exact server-formatted text in a selectable response
  panel. The browser does not synthesize summaries or render retrieved HTML.
  Use **Copy text**, or select the text directly.

If the browser denies clipboard access, the Copy button selects the response
and explains how to use the system Copy command. Output is a static snapshot:
there is no polling that replaces it while reading or selecting.

Source-code and multi-collection search also offer **Graph context**:
automatic (null), include (true), or omit (false). This affects source-code
enrichment only, not ranking or other collection kinds. Changing a control
does not requery automatically; submit Search to request a new snapshot.

Knowledge Cards keep their expert/general and minimum-similarity controls.
Raw card results use the specialized JSON/YAML endpoint; LLM card results use
the unified corpus endpoint, mapping vector to semantic, query type to
perspective, top-k to limit and minimum similarity to minimum score.
Structured document filters remain available as JSON on ordinary/multi search.
Empty multi-collection selections are rejected before an API request.

## Accessing graphs

Choose **Graphs** in the primary navigation, **Graph explorer** on a source-code
collection, or **Explore source graph** on a raw source-code search result.
The latter opens entity discovery restricted to the matched source ID.

Only source-code collections are offered in the graph selector. General and
Knowledge Cards collections do not build graphs. Disabled graphs and missing
graph databases have explanatory states rather than triggering indexing.
Build or refresh a graph using a normal scan from collection administration.
Unsupported languages, syntax errors or stale revisions can yield no graph
entities even when the source text is indexed. Supported grammars and limitations
are documented in [SOURCE_GRAPH.md](SOURCE_GRAPH.md).

### Basic query

1. Select the source-code collection.
2. Select `find`, `neighbors`, `callers`, `callees`, `dependencies`,
   `inheritance`, or `impact`.
3. Identify the target by symbol or entity ID. Find may leave this empty;
   other actions need a selector or an advanced source ID.
4. Choose Raw JSON or LLM text and click **Query graph**.

Raw results show status, collection/action, static-analysis caveats, candidate
or traversed entities, and a relationship table with resolution and file/line
evidence. Expand **Full raw graph response and chains** for the complete
structured data.

Click **Use this entity** to select an exact ID for a follow-up. This sets the
action to neighbors and clears a previous source restriction, allowing navigation
to an entity in another file. Choose a different action if desired, then query
again; selecting a candidate does not silently execute another query.
Ambiguous names remain candidates instead of being guessed.

LLM mode shows the backend's readable relationship chains and citations.
Candidate IDs needed for disambiguation can be copied into the Entity ID input.
Unresolved targets, no-match conditions and partial/truncated results remain
visible; this is static analysis, not proof of complete runtime relationships.

### Traversal options

Expand **Traversal options** for depth (1–5), result limit (1–200), direction,
source ID and relationship overrides. Direction applies only to neighbors;
other actions use their backend-defined directions. Leave relationship
checkboxes unchecked to use the selected action's defaults.

Queries only read the graph. They never create a collection, rescan sources,
flush graph work or invoke an LLM.

## Compatibility and verification

The UI handles JSON and UTF-8 text responses, including non-JSON server errors.
Retrieved names, snippets and output are escaped before display. Forms retain
their input on errors and restore their submit state. Existing job-record
snapshot/selection behavior remains unchanged.

Graph pages are `/graph` and `/collections/{name}/graph`; both retain
administrative web authentication. Query-only MCP credentials cannot access
them. No token, database schema or indexing change is required for these UI
controls; restart the daemon to load new routes and refresh the browser assets.

`tests/browser_search_graph.mjs` exercises request formats, graph controls,
candidate selection, card mappings, error/empty/disabled states, hostile text,
copy fallback, and mobile width using Chromium and controlled responses.
`tests/browser_job_record.mjs` covers the existing stable job inspector.
Run either with Node and Playwright/Chromium installed; they are optional browser
checks separate from pytest. Live-backend checks use an isolated synthetic corpus,
not private user collections or a claim about real embedding quality.
