# Changelog

## 0.5.4

- Replace terse argparse listings with a self-contained CLI help catalog:
  every command has a purpose, operational caveats and a valid example; every
  option explains accepted values, defaults, effects and relevant safety limits.
- Explain direct versus daemon ownership, host interpretation of paths, output
  behavior and discovery of IDs in each service command's help.
- Preserve multi-search failure and skipped-filter diagnostics in table output
  even when no result rows exist.
- Map invalid Knowledge Card content to HTTP 422 and duplicate card IDs to
  HTTP 409 instead of the generic 500 fallback; preserve existing error codes.
- Add offline repository consistency tests for every CLI command/example/option,
  CLI-to-Engine signature binding, Markdown relative links, documented REST
  routes, TOML setup examples, error-status mappings and Python guide Engine calls.
- Correct documentation version/command-count drift and refresh CLI, Python API,
  feature, testing and release records. Indexes and request schemas are unchanged.

### Repository consistency review in 0.5.4

This review covers the current Python repository's interfaces, help, documentation,
release metadata and regression behavior. It combines source inspection,
machine-checked contract comparisons and executable tests; it is not a claim
that every algorithm or deployment has been formally verified.

### Problems corrected

- **CLI discoverability:** The top-level command list previously omitted command
  descriptions, and many options had no explanation. All 31 commands now have
  a purpose, behavior/safety notes and a copyable example. Every option explains
  its meaning, with relevant defaults, limits and source of IDs.
- **Missing diagnostics:** Empty search tables returned before printing
  collection failures and skipped-filter information. The output now preserves
  those diagnostics after `(no rows)`.
- **Knowledge Card HTTP errors:** `KNOWLEDGE_CARD_INVALID` and
  `KNOWLEDGE_CARD_DUPLICATE` lacked status mappings and incorrectly used the
  generic 500 fallback. They now return 422 and 409 respectively. A real
  REST/Engine regression checks malformed YAML, duplicate rejection and
  preservation of the original card.
- **Command-count ambiguity:** The CLI guide now states the exact breakdown:
  four infrastructure commands, 25 specified engine-service commands and two
  specialized retrieval commands, 31 in total.
- **Collection-kind drift:** Contributor guidance now explicitly preserves all
  three collection kinds, including whole-field Knowledge Card indexing.
- **Reserved settings:** Configuration and Python guidance explicitly distinguish
  the unused global `defaults.recursive_scan` setting from the active per-request
  recursion flag. Reserved artifact/temp/health-poll settings remain documented
  as such instead of claiming behavior they do not implement.
- **Shutdown scope:** Runtime documentation now states that the configured
  cleanup deadline also applies to direct CLI service operations, not only serve.
- **Coverage invocation:** README now uses the same source-directory coverage
  target as the testing guide, avoiding ambiguity with the same-named launcher.
- **Release identity:** Package metadata, runtime version, lockfile, citation,
  CodeMeta and README citation identify 0.5.4. Historical changelog and
  verification records retain their actual release versions.

### Checks added to the repository

`tests/test_repo_consistency.py` checks:

- All CLI commands have detailed help, nonempty option explanations and examples.
- All command examples parse; service example arguments bind to actual Engine
  signatures without executing operations or opening user databases.
- Rendered examples remain intact rather than being broken into separate shell
  commands by terminal-width wrapping.
- Relative Markdown link targets exist across root documentation and `docs/`.
- Documented REST routes/methods match the FastAPI route declarations.
- Direct Engine calls in Python-guide code blocks bind to current signatures.
- Current TOML setup examples parse and validate against `GlobalConfig`.
- Literal application error codes have a declared HTTP status mapping.
- Empty table output preserves failure and skipped-filter diagnostics.

These supplement existing tests for release metadata, MCP wire discovery and
annotations, authorization, source/Knowledge Card indexing, SQLite recovery,
graph provenance, converters, CLI subprocesses and shutdown.

### Review scope and retained boundaries

The review compared CLI/REST/MCP dispatch and public request models, configuration
defaults and reserved fields, collection/index lifecycle descriptions, graph
contracts, PDF setup guidance, ownership/shutdown rules and packaging metadata.
No source-sidecar policy, retrieval format default, authentication scope or
index schema changed. Existing data does not require rebuilding.

See [VERIFICATION.md](VERIFICATION.md) for actual test results and interpreter
profiles. Tests use disposable files/databases and deterministic embedding
fixtures, not the owner's production corpus. External link availability,
directory acceptance, real Hermes behavior, real Ollama quality, MinerU 3.4.5,
other external converters and non-Linux deployments remain separate acceptance
work. Existing documented limitations such as best-effort graph resolution,
exact vector-search scaling and the pending web chunk browser are not relabelled
as completed by this consistency review.

## 0.5.3

- Annotation follow-up: declare all four boolean MCP tool hints directly on
  every decorator, including the admin-only tools. Add `idempotentHint=true`
  to read-only tools and `false` to action-dispatch administrative tools.
  Verify actual `tools/list` JSON rather than only in-process SDK objects.
- Require MCP SDK `>=1.30.0,<2`; retain the tested 1.30.0 lockfile resolution.
  Expected stateless transport teardown is handled by the SDK, without a
  ragdbman log filter or third-party transport monkeypatch.
- Make both MCP profiles tools-only: omit unused prompt/resource capabilities
  from initialization and remove their handlers, including resource templates
  and subscriptions. Unsupported requests return JSON-RPC Method Not Found.
- Preserve three query tools, six admin tools, authentication, collection scope,
  and raw/LLM output contracts. No index rebuild or re-embedding is required.
- Add discovery, unsupported-method, repeated/concurrent ping, expected and
  unexpected stream-closure, and dependency-metadata regression tests.
- Document isolated-environment installation and client capability refresh.

## 0.5.2

- Web UI follow-up: expose raw/LLM search formats, graph-context controls,
  exact-entity graph navigation and all read-only graph actions; support
  JSON/text responses with safe static copy/select panels and mobile layouts.

- Extend the CLI with all 25 requested engine-service commands, retaining
  serve/init/registry-repair/fetch-tokenizer, plus graph and Knowledge Card search.
- Add global config/log flags, validated named arguments, repeated numeric
  filters, JSON/table output, existing LLM presentation and exclusive manifest export.
- Run local scan/rebuild/resume jobs to a stopped state before engine cleanup;
  provide two-second job watching and predictable process exit statuses.
- Add explicit `--server-url` administrative REST transport for daemon-owned
  jobs, with environment-token auth, no redirects or local fallback, and
  HTTPS except for loopback HTTP.
- Acquire data-directory and registry process locks before CLI/serve engine
  startup; add bounded foreground SIGINT/SIGTERM cleanup and resumable pauses.
- Preserve finished job history when cancellation is requested after completion.
- Include the supplied guide as `docs/PYTHON_API_GUIDE.md`, correcting obsolete
  MCP mapping, job IDs, async lifecycle, collection kinds and retrieval examples.
- Add `docs/CLI.md`, update release/API/runtime documentation and CLI regression tests.

## 0.5.1

- Add deterministic `raw`/`llm` formatting to corpus queries, graph traversal,
  and administrative single/multi-collection search.
- MCP query and graph tools default to LLM-ready text without duplicate
  `structuredContent`; raw mode preserves complete structured envelopes.
  REST/Python defaults remain raw, and REST text responses use UTF-8 plain text.
- Render numbered evidence, actual score policies, file locations and compact
  static Calls/Called by/Imports/type/reference context without generated summaries.
- Preserve uncertainty, partial-result warnings, adaptive fences and Knowledge
  Card YAML; graph discovery retains only the IDs needed for exact follow-up.
- Keep tool names/counts, retrieval behavior and authentication unchanged.
- Add output-format regression tests, guide and updated citation metadata.

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
