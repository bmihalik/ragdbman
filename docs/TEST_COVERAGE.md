# Test coverage map

## Source graphs

`tests/test_source_graph.py` contains 35 parser and integration cases covering
all bundled grammar variants, imports/aliases, type relations, shadowing,
mixed-language isolation, bounded traversal, revision-safe citations, outbox
recovery, graph failure isolation, unchanged backfill, lifecycle operations
and authenticated MCP/REST. These use actual parsers with synthetic repositories
and deterministic embedding doubles. See [VERIFICATION.md](VERIFICATION.md) for
the executed interpreter/profile matrix and [SOURCE_GRAPH.md](SOURCE_GRAPH.md)
for limits that tests do not turn into compiler/runtime guarantees.

## Coverage map

`tests/test_mcp_source_declarations.py` checks all 28 explicitly named tool
functions for literal boolean annotations, confirms that only the three query
tools are outside the admin branch, and compares generated source against the
operation catalog. This is a static-source regression, not a replacement for
the existing initialization, schema and `tools/list` wire tests.

`tests/test_repo_consistency.py` makes cross-surface drift executable. It checks
that all 31 CLI commands have detailed descriptions/examples, every option has
nontrivial help, examples parse, 28 service contracts bind to their Engine
signatures, relative Markdown links resolve, the generated reference matches REST
routes, and direct Engine calls in the Python guide bind to current signatures.
It also covers empty-result table diagnostics.

`tests/test_mcp_capabilities.py` contains 24 cases covering actual initialization
capabilities on both profiles, catalog-matched tool counts and usable discovery,
unsupported prompt/resource/template/subscription methods, serial/concurrent
stateless pings, expected teardown without ERROR logs, unexpected closure with
ERROR logs retained, source/lock/installed-package dependency requirements,
and all four explicit boolean annotations with their intended values on every
tool in both profiles' serialized `tools/list` replies.

`test_web_graph_ui.py` checks administrative authentication on the new graph
pages. Optional `browser_search_graph.mjs` covers formats, graph controls,
selection, error/disabled/empty states, escaping, copying and mobile width;
`browser_job_record.mjs` retains the stable-inspector regression.

`tests/test_cli_commands.py` contains 60 CLI contract and workflow cases, including
actual foreground and daemon subprocesses, cancellation/resume, ownership
contention, watch output, confirmations, filters, table escaping and manifests.
See [CLI.md](CLI.md) for supported execution modes and limits.

`tests/test_output_formats.py` adds 28 format-contract cases. They check
service-side raw/LLM presentation, MCP/REST defaults, no duplicate JSON in
text mode, authorization, graph uncertainty/citations, card YAML, escaping,
score display and no additional embedding calls.

The test suite covers application behavior using temporary sources and databases.
This map identifies the main test modules; passing cases do not establish
compatibility with every real document, external tool version, or deployment.

| Area | Test modules in `tests/` |
| --- | --- |
| Configuration, CLI, schema initialization, vectors, registry, scanning | `test_core.py` |
| Collection lifecycle, indexing, restart persistence, jobs, four search modes, filters, atomic failure handling | `test_engine.py` |
| Format extraction, sidecars, path safety, external converter contracts | `test_extraction.py` |
| PDF backend isolation, fallback, MinerU CLI adapters and PATH lookup, licensing | `test_pdf_options.py` |
| Tokenizers, chunk boundaries, overlap, Unicode offsets, facts and keywords | `test_chunking_metadata.py` |
| Ollama HTTP contracts, REST requests, authentication and web guards | `test_ollama_web.py` |
| Logging, complete fresh schema, extraction edge cases, subprocess failures, tokenizer downloads | `test_regressions.py` |
| Overview HTTP requests during blocked scan stages, cancellation rollback, shutdown cleanup, bounded health checks | `test_responsiveness.py` |
| YAML validation, field embeddings, confidence formulas/fallback, duplicates, replacement, rebuild/pruning, restart, MCP/REST and responsive parsing | `test_knowledge_cards.py` |
| Same-named launcher collisions, source-qualified resources, import guards, CLI invocation and local environment selection | `test_launcher.py` |
| Query/admin MCP profiles, transport authorization, REST bypass denial, scoped discovery, unified queries, canonical operation validation and card rendering | `test_corpus.py` |
| Canonical names, removed aliases, flat schemas, API/MCP/Python/CLI parity, confirmations and strict arguments | `test_canonical_interfaces.py` |
| Tools-only capability discovery, unsupported protocol methods, stateless teardown and SDK dependency requirements | `test_mcp_capabilities.py` |
| Citation/CodeMeta identity, author, license, release-version consistency and wheel inclusion plan | `test_release_metadata.py` |
| Total/processed counts, percentage, ETA, empty scans, cancellation/resume and downtime-safe recovery | `test_scan_progress.py` |
| Extensionless/unknown source text detection, Unicode, binary rejection, full validation and line chunking | `test_source_sniff.py` |
| Job inspection expansion, text selection, keyboard focus and explicit snapshot refresh during live updates | `browser_job_record.mjs` (optional Chromium test, separate from pytest) |
| WAL NORMAL, batched vocabulary, connection leases, bounded file pipelines, log levels, converter descendants, real SIGINT with SSE and forced deadline | `test_performance_shutdown.py` |

Source-code collections are tested for the absence of sidecars across multiple
input formats. General collections are separately tested for intentional
document-style indexing of code, including Markdown materialization.

The suite includes MCP protocol checks and shared-engine integration coverage.
See [testing instructions](TESTING.md) for execution and mocking boundaries, and
[verification results](VERIFICATION.md) for actual runs and outstanding acceptance work.
