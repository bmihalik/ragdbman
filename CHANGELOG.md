# Changelog

## 0.5.0

- Automatic Tree-sitter syntax graphs and AST-aware chunk boundaries for
  Python, Rust, C/C++, JavaScript/JSX, TypeScript/TSX, Go, Java and C# source files.
- Separate per-collection graph SQLite storage with stable source provenance,
  transactional outbox/replay, revision validation and current chunk citations.
- Bounded automatic source search enrichment, controlled by
  `include_graph_context`; ordinary retrieval remains available on graph failure.
- One read-only `corpus_graph` tool for discovery, neighborhoods, callers/callees,
  dependencies, type hierarchies and impact traversal. Query/admin profiles now
  expose three/six tools with unchanged authentication and collection scoping.
- Administrative `POST /api/corpus/graph`, graph configuration and diagnostics.
- Missing graph data can be filled by ordinary scans without re-embedding
  unchanged sources. Confirmed rebuild also refreshes AST chunk boundaries.
- Explicit unresolved/ambiguous static bindings and bounded parser/traversal
  behavior; no source execution, graph LLM calls or runtime grammar downloads.
- Preserve normal text fallback for unsupported/erroring source grammars and
  keep general/KC indexing separate. Source-code collections never create sidecars.
- Associate unchanged standalone additions with a later scan root so missing-file
  pruning can remove their document and graph records.
- Updated citation metadata, documentation and graph regression tests.

## 0.4.4

- Add effective TRACE/DEBUG/VERBOSE and richer INFO/WARNING/ERROR diagnostics,
  with CLI/environment/config precedence and stage/batch/queue/transaction timings.
- Stop indexing and owned converter groups on the first console signal, before
  HTTP/SSE drain; fix cleanup when an exited parent leaves descendants holding
  pipes. Add an overall shutdown watchdog for non-cooperative native threads.
- Batch keyword vocabulary SELECTs and bulk inserts, add the keyword-ID lookup
  index, and refresh frequencies once at scan end rather than per scanned file.
- Reuse one persistent collection writer and exclusively leased cached readers.
  Use WAL synchronous=NORMAL with documented power-loss durability limitations.
- Run bounded file pipelines (default four) with a separately bounded Ollama
  semaphore. Keep atomic source replacement, cancellation cleanup, partial-failure
  handling and PyMuPDF serialization.
- Add actual SIGINT/SSE/descendant-process tests and a reproducible local benchmark.

## 0.4.3

- Preserve job-panel DOM nodes during live updates so inspection details stay
  expanded and JSON text selection and keyboard focus are not repeatedly lost.
- Make “Inspect job record” a stable snapshot, updated only when opened or when
  the user clicks “Refresh record”; status/counts/timing continue updating live.
- Add an optional browser regression covering selection, focus, expansion,
  terminal updates and explicit snapshot refresh.

## 0.4.2

- Show total and processed file counts, percentage, elapsed time and approximate
  remaining time in live scan progress. Expose the same values in REST/MCP job
  replies, with explicit discovery/indexing/cleanup phases and per-attempt timing.
- Freeze elapsed time on cancellation/completion and avoid counting daemon
  downtime when recovering interrupted jobs.
- In source-code collections, sniff extensionless and unrecognized-suffix files
  for Unicode text. Preserve source-line chunking and the no-sidecar rule; reject
  binary/empty inputs and validate full contents before embedding.
- Keep general and Knowledge Cards admission rules unchanged. A normal scan can
  now index previously unsupported source text without a destructive rebuild.

## 0.4.1

- Add CITATION.cff and codemeta.json with synchronized release, author and license
  metadata; include them in source distributions and installed packages.
- Recommend configured MinerU or Marker for PDF chapter/section detection, and
  explain heading-quality limits and the loss of structure with text-only fallback.
- Document sqlite3/search-response chunk inspection and identify a dedicated web
  chunk browser as a fast-follow.
- No extraction, indexing, MCP, authentication or database-schema behavior changes.

## 0.4.0

- Expose two operational `corpus_` tools and three optional management tools
  through separately authorized `/mcp/query` and `/mcp/admin` profiles.
- Add a unified cross-kind/cross-collection query contract with general/expert
  perspectives, global limits, explicit score policies and per-collection warnings.
- Return structured results and readable numbered Markdown/YAML evidence,
  preserving card values and code while excluding internal card IDs.
- Add default/allowed collection scopes and distinct query/admin credentials;
  prevent query tokens and anonymous requests from bypassing MCP restrictions
  through web/REST administration when MCP credentials are configured.
- Preserve specialized administrative REST/UI workflows independently of MCP
  management visibility. Document profile setup and action-specific contracts.

## 0.3.1

- Anchor HTML, JavaScript/CSS and SQL resources to the actual importing package,
  preventing a same-named launcher from being imported during an HTTP request.
- Include a guarded source-checkout `ragdbman.py` launcher with canonical package
  imports, safe package/resource discovery and local `.venv` selection.
- Guard the package `__main__` entry point against execution on import.
- Add isolated-process launcher/import/resource regressions and document how to
  avoid mixed system/user dependency installations.

## 0.3.0

- Add `knowledge_cards` collections with safe YAML validation, independent field
  vectors, transactional card replacement, incremental scans and lifecycle cleanup.
- Add confidence-weighted cosine/BM25 retrieval with general/expert queries and
  hybrid rank fusion. Environment defaults configure cutoffs and formula weights.
- Add `search_knowledge_cards` MCP and REST/UI support, returning complete YAML
  with top-level card IDs removed while preserving nested values and code text.
- Add formula, validation, lifecycle, cancellation and interface tests plus an
  opt-in card-corpus verification utility.

## 0.2.3

- Keep the web server responsive while scanning: extraction (including PDF and
  converter-output parsing), sidecar handling, tokenizer loading/chunking, index
  writes, and missing-source pruning run outside the HTTP event loop.
- Retain per-collection mutation locks until worker cleanup finishes, use
  thread-safe cancellation signals, and roll back cancelled index/prune writes.
- Forward shutdown cancellation to converter event loops and reap subprocesses
  before releasing their scratch directories and collection locks.
- Bound the Ollama health probe to three seconds, including any wait for its
  embedding request slot; a busy provider no longer stalls the health panel.
- Add responsiveness, cancellation, restart-safety and converter-cleanup
  regression tests. The database schema and collection-kind behavior are unchanged.

## 0.2.2

First-distribution preparation for the Python application. This entry summarizes
the available release-candidate functionality, not a claim of publication.

- Local collection management with SQLite, FTS5 and sqlite-vec, plus Ollama
  embeddings and exact or explicitly approximate tokenization.
- Document extraction, chunking, metadata, incremental scanning, persistent jobs,
  cancellation/resume, keyword/vector/hybrid/structured search and source evidence.
- REST, 25 MCP tools, command-line setup and an administrative browser interface.
- General collections with inspectable Markdown sidecars; source-code
  collections with direct indexing and no sidecar creation for any file format.
- pypdf in the base installation; explicitly selected optional PyMuPDF, plus
  separately installed MinerU and Marker executable adapters.
- MinerU examples use `mineru` from PATH. Version 3.4.5 is the maintainer's
  planned real-installation acceptance target; automated tests use fixtures.
- Complete fresh database schema with idempotent initialization and tests for
  stored data, embeddings and search across normal restarts.
- Apache-2.0 licensing, LICENSE/NOTICE, and first-party SPDX headers naming
  Bela Istvan MIHALIK; detailed human and Perplexity Computer contribution credits.
- Installation, configuration, architecture, API, testing, dependency-license
  and product-vision documentation, plus reproducible packaging and CI profiles.

Knowledge Cards/KCDB, declarative document-type chunking policies, AST-aware
code parsing and richer sidecar provenance are future work. See `TODO.md` and
`FEATURES.md` for the roadmap and current limitations.
