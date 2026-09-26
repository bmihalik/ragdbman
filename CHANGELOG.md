# Changelog

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
