# Testing and release verification

The Python tests exercise real SQLite/FTS5/sqlite-vec databases and real document
parsers against temporary fixtures. They do not require access to private files,
a running Ollama service, model downloads, or a GPU.

## Reproduce the automated checks

From the repository root:

```sh
uv sync --locked
uv run pytest -q --cov=src/ragdbman --cov-config=pyproject.toml --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv build
```

The base profile contains no PyMuPDF installation. Two tests specifically for
the optional PyMuPDF extraction/OCR paths skip when the extra is absent; the
ordinary PDF fixtures and all pypdf/MinerU contract tests run without it.
To include the optional backend:

```sh
uv sync --locked --extra pymupdf
uv run --no-sync pytest -q
uv run --no-sync python tools/license_headers.py
```

The explicit coverage configuration prevents unrelated parent-directory settings
from excluding this checkout. CI runs the test and packaging commands on Linux
with Python 3.11, 3.12, and 3.13 for both the base and optional PyMuPDF profiles.
A configured CI matrix is not a claim that a
remote CI run has already occurred.

## Test boundaries

Source-graph tests exercise the bundled native grammars without network downloads
or LLM extraction. They include mocked graph-write failures and replay, current
chunk provenance, and query-profile authorization. Run just that group with
`uv run pytest tests/test_source_graph.py -q`. Successful fixtures do not imply
complete compiler binding, dynamic-call coverage or production-scale throughput.

- **Real dependencies:** SQLite extension loading, vector distances, FTS queries,
  schema initialization, transactions, tokenizers, XML/ZIP/Office parsers, pypdf extraction
  and decryption, subprocess execution, HTTP routing, MCP wire protocol.
  PDF rendering/OCR additionally runs in the explicit PyMuPDF profile.
- **Ollama:** HTTP contract tests use `httpx.MockTransport`; engine tests inject a
  deterministic test-only embedder. Production has no synthetic-vector fallback.
  Retrieval ranking quality requires evaluation with the actual embedding model.
- **External converters:** temporary executable fixtures exercise MinerU, Marker,
  LibreOffice, ffmpeg, Whisper and Tesseract invocation/output contracts. These
  tests do not establish compatibility with every installed upstream version or
  the quality of its output.
- **Kindle:** malformed-input handling is tested. A valid real-world DRM-free
  MOBI/AZW3 corpus still needs acceptance testing; encrypted DRM is unsupported.
- **Persistence:** complete fresh schema creation, repeated initialization, and
  restarting with populated indexes are tested. Source/chunk IDs, vectors and
  keyword retrieval must survive a normal restart without reindexing.
- **Platforms:** Linux is the primary deployment target. Process groups,
  executable fixtures, systemd, and symlink tests are POSIX-oriented.
- **Knowledge Cards:** synthetic fixtures test formulas, schemas, lifecycle and interfaces.
  Use `uv run python tools/check_card_corpus.py path/to/cards.zip` for opt-in corpus
  validation, full indexing/rescanning, retrieval plumbing and lossless YAML-value
  roundtrips. The utility uses deterministic test vectors, not a real model.
  Supplied third-party card contents are not bundled or relicensed with ragdbman.
- **Vision:** Knowledge Cards authoring workflows and declarative per-document
  chunking policies are not implemented.

## Browser QA inventory

`test_performance_shutdown.py` includes real process/HTTP/SSE SIGINT checks and
an isolated forced-deadline test. Run it on Linux for the procfs/process-group
assertions. `uv run python tools/benchmark_indexing.py` runs the documented
synthetic vocabulary and concurrency fixtures without Ollama or model downloads.

With the JavaScript Playwright package and its Chromium browser installed,
`node tests/browser_job_record.mjs` runs an isolated UI regression with synthetic
job responses and a controlled SSE test double. It checks real mouse selection,
stable DOM nodes, details expansion, keyboard focus, explicit refresh/reopen and
continued live counters. This optional browser check is separate from pytest
and does not require Ollama, a daemon or user data.

`test_responsiveness.py` deliberately holds text/PDF parsing, chunking, an index
write transaction, or pruning open while requesting overview and job endpoints.
Thread identity and timing assertions prevent a false pass after the blocking
stage has already timed out. Additional tests cover cancellation rollback,
shutdown lock ownership, external-process cleanup and the health-probe deadline.

`uv run python tests/browser_server.py` starts a loopback-only disposable server
on port 8766 with a test-only embedder. Its log reports the allowed temporary
source directory. Never use this server for real indexing.

Exercise the following through visible controls:

| Surface | Controls and states to check |
| --- | --- |
| Dashboard | Collection/source/chunk counters, model status, light/dark toggle |
| Collections | Create general and source-code kinds, description, model/chunk overrides, validation |
| Collection detail | Register/scan/unregister root, full configuration, manifest |
| Upload | File chooser, upload/index feedback, failure handling |
| Sources | Extension/status filters, details, index-removal confirmation, pagination |
| Jobs | Live SSE progress, terminal state, cancel/resume, navigation |
| Search | All four modes, JSON filters, provenance, result limits, empty results |
| Multi-search | Collection selection, merged results and per-collection errors |
| Maintenance | Vacuum, rebuild confirmation, deletion confirmation and cancellation |
| Responsive layout | Desktop 1280 px and mobile 375 px; scrollable tables; no page-level horizontal overflow |
| Exploratory failures | Invalid filter JSON; nonexistent collection; rejected source path |

Automated API/engine tests cover busy/cancel/resume, pagination, guards and errors
even where a fast browser fixture makes timing-dependent states difficult to
observe. See `VERIFICATION.md` for the checks actually executed for this release.

## Real-service acceptance on a fresh installation

Run `ragdbman init`, select a fresh data directory, and allowlist a disposable
representative source corpus. Follow the setup commands in `README.md`.
Check each deployed embedding model, token count, collection kind, metadata filter,
MCP client, and configured converter against a representative document corpus.
Compare evidence and source citations, not just result counts. Confirm the
SourceCode corpus remains free of newly created `.ragdbman` directories.

Run only one daemon process and one Uvicorn worker per data directory.
Back up valuable source files before performing real-environment acceptance tests.

### MinerU 3.4.5 acceptance target

Bela Istvan MIHALIK plans to test the external integration with MinerU 3.4.5.
Configure `mineru_command = "mineru"` and check its availability using
`mineru --version` and `mineru --help` from the service's environment.
Choose the CLI adapter matching that executable and initially use
`pdf_fallback = false`, so a failed integration cannot be hidden by pypdf fallback.

Test a multi-page scientific paper with equations, tables and figures in both
collection kinds. Inspect the extracted text and output completeness, confirm
general-collection Markdown/images, and verify that source-code indexing creates
no `.ragdbman` sidecar directory. Automated executable fixtures cover PATH lookup
and invocation contracts; they do not establish MinerU 3.4.5 output quality or
compatibility with a particular GPU/model installation.
