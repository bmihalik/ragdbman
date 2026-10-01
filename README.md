# ragdbman

An inspectable, local document intelligence system, implemented in Python. Organize named collections, follow indexing jobs, inspect Markdown sidecars and SQLite records, and retrieve source-backed evidence through MCP, REST, or the administrative UI.

Collections use SQLite files and embeddings come from Ollama. The shared engine exposes document, source-code and Knowledge Cards indexing through one canonical operation vocabulary. Query MCP has three read-only corpus tools; the separately enabled admin profile exposes the full 28-operation catalog.

Version 0.6.0 aligns CLI, MCP, Python and REST names without compatibility aliases.
Use `corpus-query`, `corpus-graph` and `corpus-describe` in the CLI; use the same
names with underscores in Python/MCP and `POST /api/<hyphenated-name>` in REST.
All use the same flat fields. See the generated [interface reference](docs/INTERFACES.md)
and explanatory [CLI help](docs/CLI.md). Existing indexes do not need rebuilding.

Version 0.5.3 tightens the MCP dependency to `>=1.30.0,<2` and stops advertising
unused prompt/resource capabilities on both MCP profiles. The three operational
tools remain unchanged; no index rebuild or re-embedding is required.
The annotation follow-up explicitly declares `readOnlyHint`, `destructiveHint`,
`idempotentHint` and `openWorldHint` on every query and administrative tool;
their values and scope are documented in [MCP setup](docs/MCP.md).

Stop the old daemon before replacing the source, run `uv sync --locked`, then
start with `uv run --locked ragdbman serve`. Preserve any optional extras in both
commands (for example, `--extra pymupdf`). Reload or reconnect your MCP client
so it discovers the current capabilities; Hermes users can use `/reload-mcp`
or restart Hermes. See [MCP setup and troubleshooting](docs/MCP.md).

## Source-code knowledge graphs

Version 0.5.1 adds service-side output formatting. MCP `corpus_query` and
`corpus_graph` default to `format="llm"`: readable evidence with compact graph
context, not nested provenance JSON. Choose `format="raw"` for the complete
structured response; REST and Python APIs retain raw defaults.
See [output formats and examples](docs/OUTPUT_FORMATS.md).

Version 0.5.0 automatically extracts source-code entities and relationships with
Tree-sitter while indexing `source_code` collections. Supported graph grammars
are Python, Rust, C, C++, JavaScript/JSX, TypeScript/TSX, Go, Java and C#.
Normal source-code searches include bounded entity, call and import context;
set `include_graph_context=false` to omit it. `corpus_graph` answers explicit
callers, callees, dependency, inheritance and impact queries without adding
another search mode.

Each source-code collection has a separate `<name>.graph.sqlite` database.
Extraction makes no LLM calls, runs no source code and downloads no grammars at
indexing time. Parser-observed syntax is deterministic, but target resolution
is best-effort static analysis, not compiler verification or a runtime call
graph. Unresolved and ambiguous relationships remain explicitly labelled.
General collections and Knowledge Cards do not build graphs.

An ordinary scan fills missing graph data for unchanged sources without new
embedding calls. A confirmed rebuild also regenerates chunks using AST
boundaries. Unsupported languages retain line-based/heuristic extraction,
and source-code collections still never create Markdown sidecars.
See [source graph setup, coverage and examples](docs/SOURCE_GRAPH.md).

The web Search pages expose **Raw JSON** and **LLM text** output plus source
graph-context controls. Open **Graphs** in the navigation, **Graph explorer**
on a source-code collection, or **Explore source graph** on a raw search hit
to inspect entities, callers, dependencies and type relationships.
See [web query and graph guide](docs/WEB_UI.md) for the read-only explorer.

## Install with uv

Use Python 3.11 or newer. Python 3.12 is recommended for the widest compatibility with optional converter installations.

```bash
cd ragdbman
uv sync --locked
uv run ragdbman init
```

Edit `~/.config/ragdbman/config.toml` and explicitly allow your source directories:

```toml
[storage]
allowed_source_roots = ["/home/you/Documents", "/home/you/Projects"]
```

Run Ollama separately and install the embedding models you intend to use:

```bash
ollama pull bge-m3:567m
ollama pull unclemusclez/jina-embeddings-v2-base-code:f16
```

Download the corresponding exact tokenizers:

```bash
uv run ragdbman fetch-tokenizer --hf-repo BAAI/bge-m3
uv run ragdbman fetch-tokenizer \
  --hf-repo jinaai/jina-embeddings-v2-base-code \
  --model unclemusclez/jina-embeddings-v2-base-code:f16
uv run ragdbman serve
```

Use the project environment rather than mixing distribution Python packages
with packages under `~/.local`. After `uv sync --locked`, the bundled executable
`./ragdbman.py serve` is also supported: from system Python it selects the local
`.venv` if present, and from an already active virtual environment it keeps that
interpreter. The installed `ragdbman` command remains the recommended entry point.

### Startup troubleshooting

If opening `/` reports `asyncio.run() cannot be called from a running event loop`
and the traceback imports a top-level `ragdbman.py` during resource loading, a
same-named custom launcher is shadowing the package and executing its `main()`
again. Replace that launcher with the bundled guarded version; resource loading
is also anchored to the actual package, not a hard-coded import name.

If a traceback mixes `/usr/lib/python3/dist-packages` with `~/.local/lib`, stop
the daemon and run `uv sync --locked` followed by `uv run --locked ragdbman serve`.
Do not fix this by suppressing Pydantic warnings or installing individual
dependencies into the system interpreter. An unresolved MCP `lifespan` warning
is separate from the launcher recursion; reproduce it in the locked environment
before diagnosing upstream dependency compatibility.

Open `http://127.0.0.1:8765` for the UI or `/docs` for the REST schema. MCP clients use `/mcp/query` with a query token; the optional administrator profile is `/mcp/admin`. See [MCP setup](docs/MCP.md) for separate credentials and collection scope. Collection creation probes the selected model; it requires Ollama and the model to be available. The daemon can start without Ollama, and keyword/structured retrieval of an existing collection remains available.

If a model has no available tokenizer, explicitly opt into estimated counts:

```toml
[defaults]
allow_approximate_tokenizer = true
```

Exact tokenization is the default requirement for document and source-code collections. Knowledge Cards embed whole YAML fields and do not need a tokenizer. The selected mode is recorded in collection metadata.

## Command line and Python API

The canonical CLI covers collection, file, scan and maintenance operations.
All retrieval uses corpus-query, including Knowledge Cards and multiple
collections. `--format raw` returns JSON, `table` is compact local output,
and corpus query/graph also support `llm`.

```sh
uv run ragdbman collection-create --name code --kind source_code \
  --source-roots /home/you/Projects/app
uv run ragdbman scan-start --collection code --root /home/you/Projects/app
uv run ragdbman corpus-query --collections code --query "configuration loading" \
  --mode keyword --format llm
uv run ragdbman corpus-graph --collection code --action callers --symbol parse_config
```

Direct scans/rebuilds/resumes stay in the foreground until stopped, then close
the engine cleanly. When `serve` owns the data, use an explicit daemon URL
instead of starting a competing engine:

```sh
uv run ragdbman collections-list --server-url http://127.0.0.1:8765
uv run ragdbman scan-job-get --collection code --job-id JOB_ID --watch \
  --server-url http://127.0.0.1:8765
```

Daemon commands use the existing `RAGDBMAN_AUTH_TOKEN` administrator credential
when configured; no token is put in command arguments. Local CLI/serve ownership
locks prevent accidental job recovery by a second process. See the complete
[CLI reference](docs/CLI.md) for all 31 commands, confirmations, filters,
foreground/daemon behavior and exit codes.
The supplied [Python API guide](docs/PYTHON_API_GUIDE.md) is included and
corrected to the current interfaces and lifecycle rules.

## Select a PDF backend

The default installation includes pypdf and does **not** install PyMuPDF, MinerU,
Marker or their models. The default `auto` policy tries separately configured
MinerU/Marker commands, then pypdf; it never imports PyMuPDF.

**PDF chapter detection requires MinerU or Marker in the current pipeline.**
For textbooks and other long PDFs, configure one of these converters as the
recommended setup for heading/section-aware chunking, not merely an optional
quality enhancement. ragdbman uses the headings in their Markdown output;
chapter recognition still depends on the converter and the input document.
The pypdf and PyMuPDF adapters provide text/pages, not chapter detection.
See [chapter-aware PDF setup](docs/PDF_BACKENDS.md#recommended-setup-for-pdf-chapter-detection).

For pypdf only, even if external converters are configured:

```toml
[media]
pdf_backend = "pypdf"
```

For your independently installed MinerU:

```toml
[media]
pdf_backend = "mineru"
mineru_command = "mineru" # resolved from the service's PATH
mineru_cli = "legacy"   # -p INPUT -o OUTPUT_DIR
mineru_extra_args = [] # e.g. ["-b", "pipeline"] if your version supports it
pdf_fallback = false  # preserve the chapter-aware requirement; fail instead of text-only fallback
```

If the installed executable uses `mineru parse`, set `mineru_cli = "parse"`.
That adapter requests all pages explicitly. MinerU always runs as a separate
executable, not an imported Python library; no MinerU package or model is bundled.
MinerU 3.4.5 is the maintainer's planned real-installation test target, not yet a
verified version. Check `mineru --help` against the configured CLI interface.

PyMuPDF remains an explicit alternative: install `uv sync --locked --extra pymupdf`
and set `media.pdf_backend = "pymupdf"` only if you choose to accept its separate
licensing. pypdf extracts text, but does not render scanned PDF pages for OCR.
See [PDF backends](docs/PDF_BACKENDS.md) and [licensing](docs/LICENSING.md) for details.

## Choose the indexing strategy

- **General collections:** document-oriented indexing. With the default sidecar setting, code and binary documents are materialized as Markdown and indexed as ordinary documents.
- **Source-code collections:** direct extraction and line-boundary code chunking, with code-oriented model and chunk defaults. No `.ragdbman` directory is created for any file in these collections, including Markdown, PDFs, and plain text.
- **Unrecognized source filenames:** source-code collections sniff extensionless
  files such as `Kconfig` and `LICENSE`, plus unfamiliar suffixes such as
  `sdkconfig.defaults`. UTF-8 text and BOM-marked UTF-16/UTF-32 are indexed with
  line provenance; binary signatures, NUL/control content and empty files are
  skipped. A bounded 64 KiB probe is followed by full-content validation before
  embedding. General and Knowledge Cards collection policies are unchanged.
- **Independent collections:** index the same repository in both collection kinds when you want different retrieval strategies. Settings and indexes are independent.

```bash
curl -X POST http://127.0.0.1:8765/api/collection-create \
  -H 'Content-Type: application/json' \
  -d '{"name":"code","kind":"source_code","source_roots":["/home/you/Projects"]}'

curl -X POST http://127.0.0.1:8765/api/scan-start \
  -H 'Content-Type: application/json' \
  -d '{"collection":"code","root":"/home/you/Projects","recursive":true}'

curl -X POST http://127.0.0.1:8765/api/corpus-query \
  -H 'Content-Type: application/json' \
  -d '{"collections":["code"],"query":"document retrieval","mode":"hybrid"}'
```

Existing sidecar directories are not deleted when a source is indexed into a source-code collection. They are excluded from scanning, including when hidden-file indexing is enabled.

## Features

- **Storage:** one SQLite database per collection; atomic registry writes and database reconciliation; FTS5, sqlite-vec, metadata, jobs, errors, audit records, and source versions.
- **Indexing:** SHA-256 change detection, unchanged-file skipping, failed-source retries, resumable jobs, cancellation before commit, transactional source replacement, and optional missing-file pruning.
- **Extraction:** text, CSV/TSV, Markdown, HTML, PDF, OOXML, ODF, EPUB, best-effort MOBI/AZW/AZW3, source code, and opt-in external OCR, legacy Office, and transcription.
- **Chunking:** exact Hugging Face tokenizers or explicitly approximate counts, sentence/token windows, heading and section boundaries, atomic blocks, code-line boundaries, overlap, and duplicate suppression.
- **Retrieval:** keyword/BM25, vector distance, hybrid rank fusion, structured filters, multi-collection rank fusion, source citations, numeric/date facts, and keyword vocabulary.
- **Interfaces:** `corpus_describe`, `corpus_query` and `corpus_graph` for query agents; explicit named collection/file/scan operations for administrators. REST/OpenAPI, managed uploads, maintenance controls, and live SSE job progress remain available.
- **Knowledge Cards:** structured YAML collections, separate field vectors, confidence-weighted retrieval, and complete ID-free YAML within the unified `corpus_query` response. See the [Knowledge Cards guide](docs/KNOWLEDGE_CARDS.md).

## Documentation

- [Canonical interface names, fields and hints](docs/INTERFACES.md)

- [Features and limitations](FEATURES.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [PDF backend selection](docs/PDF_BACKENDS.md)
- [License and dependency boundaries](docs/LICENSING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [REST and MCP interfaces](docs/API.md)
- [Testing and verification](docs/TESTING.md)
- [Test coverage map](docs/TEST_COVERAGE.md)
- [Release verification record](docs/VERIFICATION.md)
- [Contribution guide](CONTRIBUTING.md)
- [Product vision](docs/VISION.md)
- [Roadmap](TODO.md)
- [Changelog](CHANGELOG.md)
- [Attribution](AUTHORS.md)

`docs/VISION.md` describes the product direction, not a release-status checklist. Its broad “every source is converted” wording does not override the source-code or Knowledge Cards collection exemptions. Structured Knowledge Cards collections are implemented; authoring/curation workflows and fully configurable document-type chunking strategies remain future work.

## Scan progress

The job view reports processed/total files, percentage, elapsed time and
approximate remaining time. Discovery runs first; the total is shown as unknown
until the scan's file list is ready. The total respects hidden-file, symlink,
recursion and collection-kind filters, and includes files later skipped as
unsupported.

Processed files include completed, unchanged, failed and skipped outcomes.
Elapsed time covers the current attempt; ETA uses its average processing time
per file, excluding initial discovery. It is an estimate, not a guarantee:
large PDFs or slow converters can change it substantially. ETA is unavailable
before the first processed file or during missing-source cleanup. Cancellation
and terminal states freeze timing; resuming starts a fresh attempt with updated
totals and counters. The same fields are available in REST, MCP job replies and
the live SSE stream.

“Inspect job record” is a stable snapshot: opening it captures the latest record.
Live updates above it do not collapse the section or change its JSON while you
read or select text. Use **Refresh record**, or close and reopen the section, to
capture newer values. This remains true when the job finishes.

## Inspecting chunks

Chunk inspection currently uses `sqlite3` or the search response. The web UI
shows retrieved chunks and their provenance, but it does not yet offer a
dedicated browser for all chunks of a source; that web chunk browser is a
fast-follow, not yet implemented.

For full stored chunk text and boundaries, open the collection database read-only:

```sh
sqlite3 -readonly "$HOME/.local/share/ragdbman/collections/books/books.sqlite" \
  "SELECT source_id, chunk_index, heading, section_path, token_count, text
   FROM chunks ORDER BY source_id, chunk_index LIMIT 20;"
```

Replace `books` and the data directory with your collection's settings.
Search responses contain matching excerpts and provenance; excerpts may be
truncated according to `search.return_context_chars_per_chunk`. Read SQLite when
you need the full stored text or chunks that did not appear in search results.
Knowledge Cards are whole records in `kc_cards`, not rows in `chunks`.

## Citing ragdbman

Bela Istvan MIHALIK (2026). ragdbman (Version 0.6.0) [Computer software].
Machine-readable citation and software metadata are provided in
[CITATION.cff](CITATION.cff) and [codemeta.json](codemeta.json).
Human and AI-assisted contributions are distinguished in [AUTHORS.md](AUTHORS.md).

## Runtime diagnostics and tuning

Use `uv run ragdbman serve --log-level debug` for detailed stage and database
timings, `--log-level trace` for queue/connection/keyword diagnostics, or
`--log-level verbose` for per-file outcomes. The command-line level overrides
`RAGDBMAN_LOG`, which overrides `[logging] level`.

Scans default to four files in flight and the Ollama client defaults to four
concurrent requests. Existing explicit settings of `1` are still honored.
Merge these values into the corresponding TOML sections to enable both:

```toml
[defaults]
max_concurrent_files = 4

[ollama]
max_concurrent_embedding_requests = 4
```

Vocabulary operations are batched, keyword frequencies refresh once per scan,
and collections reuse a serialized SQLite writer plus cached readers. WAL
`synchronous=NORMAL` improves throughput with a power-loss durability trade-off.
Ctrl+C now stops active work and owned converter process groups before HTTP/SSE
drain; a second signal or the overall shutdown deadline can force exit if a
non-cooperative worker remains. See [runtime tuning and shutdown](docs/RUNTIME.md)
for configuration, safeguards, limitations and reproducible benchmarks.

## Develop and test

```bash
uv sync --locked
uv run pytest
uv run pytest --cov=src/ragdbman --cov-config=pyproject.toml --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv build
```

Automated tests use generated local document fixtures, deterministic test-only embeddings, HTTP mocks, and fake external executables. They do not download models or require a GPU. See [TESTING.md](docs/TESTING.md) for what was and was not exercised.

## Operational safety

Bind to loopback by default. Use an authenticated reverse proxy with TLS for remote access, set explicit source-root allowlists, and do not run the service as root. External commands are administrator-configured executables, not an OS security sandbox.

Start with a fresh data directory and explicitly allow only the source roots you intend to index. Run one daemon process per data directory, and back up collection databases and the registry before destructive maintenance.

## License

ragdbman is licensed under [Apache License 2.0](LICENSE).
Copyright 2026 Bela Istvan MIHALIK. See [NOTICE](NOTICE) and
[dependency licensing](docs/LICENSING.md); the project license does not relicense
third-party packages, external converters or model weights.

## Badges

  - [![Python tests](https://github.com/bmihalik/ragdbman/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/bmihalik/ragdbman/actions/workflows/tests.yml)

  - [![M8ven Score](https://m8ven.ai/badge/mcp/bmihalik/ragdbman?variant=verified)](https://m8ven.ai/mcp/bmihalik/ragdbman)

  - [![License](https://img.shields.io/github/license/bmihalik/ragdbman)](LICENSE)

  - [![Python](https://img.shields.io/badge/Python-%3E%3D3.11-blue?logo=python&logoColor=white)](https://www.python.org/)

  - [![Coverage](https://codecov.io/gh/bmihalik/ragdbman/branch/master/graph/badge.svg)](https://codecov.io/gh/bmihalik/ragdbman)

  - Codecov code coverage statistics:
    [![Codecov_Stats](https://codecov.io/gh/bmihalik/ragdbman/graphs/sunburst.svg?token=F4E5Q5HFO9)](https://codecov.io/gh/bmihalik/ragdbman)

