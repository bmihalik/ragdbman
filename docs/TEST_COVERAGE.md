# Test coverage map

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
| Two/five-tool MCP profiles, transport authorization, REST bypass denial, scoped discovery, unified queries, action validation and card rendering | `test_corpus.py` |
| Citation/CodeMeta identity, author, license, release-version consistency and wheel inclusion plan | `test_release_metadata.py` |

Source-code collections are tested for the absence of sidecars across multiple
input formats. General collections are separately tested for intentional
document-style indexing of code, including Markdown materialization.

The suite includes MCP protocol checks and shared-engine integration coverage.
See [testing instructions](TESTING.md) for execution and mocking boundaries, and
[verification results](VERIFICATION.md) for actual runs and outstanding acceptance work.
