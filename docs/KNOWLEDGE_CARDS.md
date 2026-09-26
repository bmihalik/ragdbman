# Knowledge Cards

Knowledge Cards are curated YAML records, distinct from raw document chunks.
Create a collection with `kind="knowledge_cards"` in REST, MCP or the web interface,
register an allowed source root, and start a scan. Only `.yaml` and `.yml` files
are discovered; managed YAML uploads and `add_file` also work.

## Card structure

Each file contains one YAML mapping. Required keys are nonblank strings `id`,
`category`, `title`, `description`, and a finite numeric `confidence` from 0 to 1.
Optional known fields are validated without filling missing fields into the
returned payload; extra domain-specific keys are retained.

```yaml
id: example-graph-traversal
category: Programming
subcategory: algorithm
title: Layered graph traversal
description: Explore vertices by their distance from a starting vertex.
positive_text: Use a queue for unweighted shortest paths.
negative_text: Do not assume this solves weighted shortest paths.
method_texts:
  - Visit undiscovered neighbors in layers.
inputs: [graph, start]
outputs: [distances]
costs:
  time: O(V + E)
  space: O(V)
codes:
  - |-
    def example(graph):
        return distances
confidence: 1.0
source:
  - name: Example reference
    topic: Graph traversal
```

`subcategory` is an unrestricted string, not a closed taxonomy. `costs` is a
mapping; `codes`, `method_texts`, `inputs` and `outputs` are lists of strings;
`source` is a list of string-valued mappings. The project does not verify the
truth, provenance or safety of card claims: confidence is supplied by the author.

Safe loading rejects executable YAML tags, aliases and duplicate/non-string
mapping keys. Non-mapping YAML or mappings lacking required keys are skipped as
non-cards. Malformed syntax or invalid typed fields are per-file errors; other
files continue indexing. File-size and path/symlink policies still apply.

## Storage and lifecycle

Only this collection kind initializes `kc_cards`, `kc_fts` and `kc_embeddings`.
The original decoded YAML is stored in `kc_cards.raw_yaml`; indexed metadata,
source identity and path are retained separately. IDs must be unique within a
collection. Two files claiming the same ID produce a clear duplicate error rather
than overwrite one another; collections have independent ID namespaces.

The description always gets a vector. Nonblank positive and negative text each
get their own vector; nonempty code blocks are joined for one additional code
vector. All use the collection's chosen model and dimension. Code vectors are
stored but are not part of the specified general/expert scoring formulas; code
text is included in keyword search.

No Markdown sidecars, chunks or tokenizer files are created or required.
Whole fields must fit the provider's context window; the embedding request does
not silently truncate them. Model limits still apply, and oversized requests
are recorded as indexing failures.

Hash-based unchanged skipping, failed-file retry, durable jobs, cooperative
cancellation, source version records, confirmed removal/rebuild and missing-file
pruning apply to cards. Replacements update card metadata, FTS and vectors in one
transaction. Changing an ID in the same file removes the old ID. A malformed
replacement preserves old stored records but marks the source failed, excluding
it from retrieval until successfully retried. Replacing a card with non-card
YAML clears its stale index and marks it unsupported.

Parsing, SQL retrieval and card writes run outside the HTTP event loop. Worker
cancellation holds mutation ownership until cleanup completes. Only one index
mutation runs per collection; overview and search reads remain available.

## Defaults and request arguments

Environment values are read and validated when the engine starts. Invalid values
fail startup with `CONFIG_INVALID`; restart the daemon after changing defaults.

| Environment variable | Default | Accepted range |
| --- | --- | --- |
| `RAGDBMAN_KC_DEFAULT_TOP_K` | `3` | Integer at least 1; effective limit capped by `search.max_top_k` |
| `RAGDBMAN_KC_MIN_SIMILARITY` | `0.65` | Finite number 0 to 1 |
| `RAGDBMAN_KC_ALPHA_NEGATIVE` | `0.30` | Finite number 0 to 1 |
| `RAGDBMAN_KC_BETA_DESCRIPTION` | `0.20` | Finite number 0 to 1 |

The specialized administrative REST search accepts `collection`, `query`,
`query_type` (`general` or default `expert`), `mode` (`vector`, `keyword` or default
`hybrid`), optional `top_k`, and optional `minimum_similarity`.
An explicit threshold of `0` is honored, not replaced with the default.

POST this object to `/api/knowledge-cards/search` for a JSON response with
ranked `results` and combined ID-free `yaml`. Each result includes the full card,
source provenance, `score`, `rank_score`, surviving channel scores and its own
ID-free `yaml`. JSON is an administrative inspection surface and retains IDs;
the operational MCP card payload and YAML fields do not.

```json
{
  "collection": "principles",
  "query": "unweighted shortest paths",
  "query_type": "expert",
  "mode": "hybrid",
  "top_k": 3,
  "minimum_similarity": 0.65
}
```

MCP uses only `corpus_query`, with `collections`, `query`, `mode`
(`keyword`, `semantic`, `hybrid`), `perspective` (`general`, `expert`), `limit`
and `minimum_score`. Its default perspective is general, its global default
limit is 5, and its card cutoff uses `RAGDBMAN_KC_MIN_SIMILARITY` unless explicitly
overridden. `RAGDBMAN_KC_DEFAULT_TOP_K` applies to specialized card REST/engine
calls, not the unified tool's global limit. See [MCP.md](MCP.md) for the complete
contract and profile setup.

The administrative document search REST routes also accept cards with expert
weighting. Structured mode and nonempty document filters are rejected for cards;
cross-collection queries report that failure while returning successful results.

## Scoring definitions

Cosine similarities are computed by SQLite's `vec_distance_cosine` over float32
vectors. For general queries, raw similarity is description cosine only. For
expert queries with both applicability vectors present:

```text
raw = positive_cosine - alpha_negative * negative_cosine
      + beta_description * description_cosine
vector_score = raw * confidence
```

If either positive or negative is absent, expert mode falls back to description
cosine alone. Results below the configured minimum are excluded. Expert scores
are not clipped and can exceed 1; they are ranking signals, not probabilities.

Keyword search uses porter/unicode61 FTS5 across title, category, subcategory,
description, positive/negative text, methods, inputs, outputs and codes. Query
words are escaped literal OR terms, not raw FTS syntax. For the current set of
matching indexed cards, normalize BM25 strength as
`max(0, -bm25) / largest_matching_strength`, then multiply by confidence and
apply the same cutoff. Scores are query/corpus-relative, not calibrated cosine
equivalents.

Hybrid mode applies the cutoff independently to both confidence-weighted
channels, then takes their union. Eligible channel rankings contribute equal
reciprocal ranks `1 / (search.rrf_k + rank)`. `rank_score` determines hybrid
ordering; `score` is the maximum surviving channel score, not the fusion score.
Ties are deterministic by score then card ID. This explicit policy resolves
the specification's otherwise unspecified hybrid normalization.

Keyword mode never calls Ollama. If a hybrid embedding request reports
`OLLAMA_UNAVAILABLE`, search logs a warning and uses keyword-only ranks.
Vector-only failures and dimension/corrupt-vector errors are not hidden.

## YAML response guarantees

The MCP text renderer places each complete card in a numbered Markdown section
with fenced YAML and a `---` document marker, with only each top-level
`id` removed. Nested keys and values, lists, mappings, Unicode, and exact code
string indentation/newlines survive a YAML load/dump roundtrip. YAML comments,
key quoting and original formatting are not reproduced byte-for-byte; raw
source YAML remains in the database for inspection.

The specialized REST YAML field uses the following message when no card survives:

```text
No Knowledge Cards met the required relevance and confidence thresholds.
```

The unified MCP response instead contains an empty `results` list plus any
warnings and a readable no-results explanation. It always keeps its envelope
consistent, including when searching a mixture of collection types.

## Testing and licensing boundary

`tests/test_knowledge_cards.py` covers validation, scoring formulas, confidence
pruning, lifecycle operations, cancellation/responsiveness, and REST/MCP output.
The opt-in corpus checker validates, indexes, rescans and roundtrips every supplied
card while exercising all six query-type/retrieval combinations:

```sh
uv run python tools/check_card_corpus.py path/to/cards.zip
```

Tests use deterministic embeddings, not evidence of semantic ranking quality.
Card content retains its own authorship and licensing; accepting cards as input
does not place them under ragdbman's Apache-2.0 license. The supplied corpus is
not bundled into this source distribution.
