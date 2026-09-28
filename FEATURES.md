# Features and implementation status

This document describes implemented functionality, not every aspiration in the vision. The application is organized into collection, extraction, indexing, retrieval, and service modules.

## Collections and persistence

- Named collections use `<data_dir>/collections/<name>/<name>.sqlite`, with `files`, `artifacts`, and `exports` subdirectories.
- General and source-code kinds select independent default models and chunk sizes. Creation accepts model, chunk-size, and overlap overrides.
- Knowledge Cards are a third kind: one card per YAML file, whole-field embeddings, no tokenizer or Markdown sidecars. Model overrides apply; chunk overrides are rejected.
- The selected embedding model is probed for dimensions. All subsequent writes and vector queries must use the recorded dimension.
- Collection descriptions are mutable. Existing collection model/chunk settings are not silently changed by editing global defaults; create a new collection for a different model or strategy.
- Registry metadata is atomically written and reconstructed from collection databases at startup. Invalid databases are reported in logs and are not silently deleted.
- Sources have stable identities across reindexing, version records, content/extraction hashes, status, diagnostics, location metadata, and optional Markdown paths.
- Transactional reindexing replaces chunks, vectors, FTS rows, numeric facts, and keyword links together. Failures preserve prior stored chunks but mark the source failed, excluding it from normal search until retried.
- Removing a source deletes dependent index records. Original files are preserved unless the caller explicitly requests deletion of a file inside the collection's managed upload tree.
- Collection deletion requires confirmation and records its intent in `<data_dir>/deletions.jsonl`; that record survives removal of the collection database.

## Extraction

| Format | Python implementation | Structure retained before sidecar conversion |
|---|---|---|
| Text, JSON/YAML/XML, logs, config text | UTF-8/BOM plus charset fallback | Text lines |
| CSV/TSV | Standard-library CSV reader | Header/value rows, quoted multiline fields |
| Markdown | markdown-it-py | Headings, section paths, fences, lists |
| HTML | BeautifulSoup | Title, headings, links, paragraphs, preformatted blocks |
| PDF | Selectable pypdf, external MinerU/Marker, opt-in PyMuPDF; configurable fallback | Page numbers where the backend supplies them |
| DOCX | ZIP plus defused XML | Paragraphs and heading styles |
| PPTX | ZIP plus defused XML | Numeric slide order and slide citations |
| XLSX | openpyxl | Sheet names and row positions |
| ODT/ODP/ODS | ZIP plus defused XML | Headings, slides, tables and repeated rows/cells |
| EPUB | ZIP plus defused XML and HTML | OPF reading order and chapter sections |
| MOBI/AZW/AZW3 | mobi/Kindle unpacking | Best-effort reflowable book text |
| DOC/PPT/XLS/RTF | Opt-in LibreOffice conversion | Structure from converted OOXML |
| Images | Opt-in Tesseract | OCR text |
| Audio/video | Opt-in ffmpeg and Whisper command | Transcript segments and timestamps |
| Source code | Tree-sitter AST boundaries for graph-supported languages; heuristic fallback | Declarations, original line positions, separate syntax graph |

Text indexing accepts Rust, Python, JavaScript/TypeScript, Go, Java, Kotlin, C/C++, C#, PHP, Swift, Scala, Objective-C, R, Ruby, shell, SQL, Lua, Perl, Vue and Svelte. The graph-supported subset uses Tree-sitter; other formats retain heuristic/line fallback. This is not a compiler. See [graph coverage](docs/SOURCE_GRAPH.md).

Source-code collections also sniff unrecognized names/suffixes, including
`Kconfig`, `LICENSE` and `sdkconfig.defaults`. A 64 KiB probe admits nonempty
UTF-8 or BOM-marked UTF-16/UTF-32 without binary signatures or disallowed control
characters. Full-content validation then protects against binary tails before
embedding. Sniffed files use source-line chunking, retain their actual extension,
and never create sidecars. Unknown legacy encodings may still be skipped;
recognized-format decoding policies and general/KC admission rules are unchanged.

External tools are disabled until configured. Arguments are passed without a shell, stdin is closed, the environment is allowlisted, and timeouts terminate the process group on POSIX. Each conversion uses its own scratch directory; LibreOffice gets a separate user profile and `GIO_USE_VFS=local`.

### PDF fallback behavior

`media.pdf_backend` selects `auto`, `pypdf`, `mineru`, `marker`, or `pymupdf`.
Default `auto` tries configured MinerU, then Marker, then pypdf/raw recovery.
PyMuPDF is never auto-detected or used in this chain: it requires both its extra
dependency and explicit selection. `pdf_fallback = false` stops at the selected
backend's failure rather than silently downgrading extraction.

PyMuPDF and pypdf can handle empty-user-password PDFs; a non-empty required password
is reported, not bypassed. The raw fallback recovers uncompressed/Flate text-showing
streams without relying on cross-reference tables.

The optional PyMuPDF backend can render blank-text pages for configured Tesseract.
pypdf alone does not render/OCR pages; use an external converter or explicitly
select PyMuPDF for that workflow. Marker pagination supports the original
number-plus-divider convention and brace-style page markers; MinerU Markdown has
no guaranteed page positions. MinerU supports a directory-output CLI adapter and
an all-pages `parse` adapter, with an administrator-configured argument list.

### Sidecars

General collections create `<original-parent>/<markdown_sidecar_dir_name>` only when indexing supported input. Markdown/plain-text originals are linked or copied for inspection. Other formats are converted to Markdown and reparsed before chunking, including source code intentionally indexed as a general document.

Source-code collections bypass sidecar creation entirely for every format. Disabling `storage.markdown_sidecar_enabled` also bypasses sidecars in general collections.

Generated filenames append a short hash of the full original filename, avoiding collisions between same-stem files, case variants, and punctuation variants. Atomic replacement never writes through an existing file symlink; sidecar directory symlinks are rejected. Converter image copies are confined to their output tree.

Markdown flattening does not preserve every original page/slide/line/timestamp coordinate. Such results expose `percent_position` and `markdown_path` instead. Disable sidecars or use an appropriate direct-extraction collection if original location metadata is essential.

## Chunking

- Exact tokenization reads per-model `tokenizer.json` files; missing exact tokenizers fail clearly unless approximate counts are explicitly allowed.
- A heading or section transition forces a chunk boundary. Overlap never crosses that boundary.
- Prose uses sentence boundaries where possible, then token windows for oversized sentences.
- Adjacent duplicate prose blocks are suppressed while chunk offsets remain valid in the reconstructed extracted text.
- Code uses physical line boundaries. A single oversized line remains intact and may exceed the token budget.
- Atomic tables, fenced blocks and transcript segments may also exceed the budget rather than be split.
- Chunk records contain tokens, reconstructed-text character offsets, percentage position, sections, and available page/slide/time/line anchors.

## Jobs

After candidate discovery, jobs expose a fixed total, processed count, percentage
and phase. REST/MCP/SSE compute live elapsed and approximate remaining time from
the current attempt. Skipped, unchanged and failed files count as processed;
cleanup is a separate phase. Cancellation freezes elapsed time, recovery uses
the last durable update rather than counting downtime, and resume starts a new
attempt. The browser displays these values with an explicitly approximate ETA.

Scans classify files as new, unchanged, changed, previously failed, unsupported or missing. Hidden files, symlink traversal and recursion are configurable; sidecar directories are always pruned. Canonical path checks prevent symlink traversal from escaping allowed roots.

Only one scan/index mutation runs per collection. Job records, per-file records, progress and errors persist in SQLite. Interrupted jobs become paused and unfinished items retryable at restart. Explicit resume rescans and skips already indexed hashes; destructive work is never automatically replayed. Cancellation is cooperative and prevents the next source commit, but an in-flight converter or embedding request may finish before it is observed.

Within a scan, a bounded file pipeline (default four) overlaps extraction and
embedding. One persistent collection writer serializes index/status writes;
cached read leases keep HTTP inspection independent of that writer. Keyword
lookups and inserts are batched, and frequencies refresh once at the end of a
scan rather than once per file. Standalone add/remove still refresh immediately.
WAL NORMAL and its durability trade-off are described in [RUNTIME.md](docs/RUNTIME.md).

Console SIGINT/SIGTERM cancels work before HTTP/SSE draining and kills owned
POSIX converter groups even if the original process exited with descendants
holding pipes. A configurable process-exit watchdog prevents non-cooperative
threads from keeping `serve` alive forever. Graceful cleanup preserves commit
boundaries; the forced deadline is an emergency exit, not successful completion.

Extraction, sidecar handling, tokenization/chunking, index writes and pruning run
outside the HTTP event loop so the overview and job controls remain available
during those stages. Worker cancellation retains collection locks until cleanup
finishes; cancelled writes roll back. The Ollama health probe has a three-second
deadline, including time spent waiting for the embedding request slot.

Rebuild clears indexes only with explicit confirmation, then reindexes tracked source paths, including standalone additions and uploads. Missing-file pruning removes index data only for paths that no longer exist, not files merely excluded by a changed scan policy.

## Retrieval

The following four modes describe ordinary document/source-code collections.
Knowledge Cards use confidence-weighted cosine similarity and normalized BM25
with general/expert queries, as specified in [their guide](docs/KNOWLEDGE_CARDS.md).
Both kinds participate in multi-collection rank fusion; document structured
filters are explicitly rejected for cards rather than silently ignored.

- **Keyword:** FTS5/BM25 over text, headings, sections and filenames.
- **Vector:** exact L2 distances from sqlite-vec, reported as `1 / (1 + distance)`.
- **Hybrid:** weighted reciprocal rank fusion of vector and keyword ranks.
- **Structured:** numeric, currency, date and keyword facts without requiring an embedding request.
- **Multi-collection:** independent searches with per-collection model settings; ranks are fused rather than comparing incompatible raw embedding scores. Failures are reported per collection.
- **Filters:** extension, source IDs, path prefix, keywords, and numeric/date operators, including between/exists. Unknown metadata fields are reported as skipped.
- **Evidence:** source and chunk IDs, filename/path, optional file link, location anchors, percentage, Markdown path, facts, keyword vocabulary, citation label, and separate vector/keyword scores.

Numeric facts are only extracted from explicit supported labels. Unrelated numbers are not inferred into prices, ratings or other fields. Date parsing and currency normalization are deterministic.

## Service interfaces

The CLI exposes 31 explicit commands: four infrastructure commands, the 25
specified engine-service commands, and graph/card search. It supports validated
flags, repeated numeric filters, JSON/table output, readable search output,
manifest export, and two-second job watching. Direct jobs retain their engine
until stopped; optional daemon transport uses existing administrative REST.
CLI/serve acquire storage/registry ownership locks before startup recovery.
See [CLI.md](docs/CLI.md) and [PYTHON_API_GUIDE.md](docs/PYTHON_API_GUIDE.md).

Query/graph output has `raw` and `llm` presentations. MCP defaults to readable
text without duplicated metadata; REST/Python default to existing JSON.
The renderer flattens graph context, preserves provenance locations and
uncertainty, and does not synthesize summaries or change retrieval.
See [output formats](docs/OUTPUT_FORMATS.md).

The service provides three operational MCP tools (`corpus_describe`, `corpus_query`, `corpus_graph`)
and three additional tools on the separately authorized admin profile
(`corpus_manage`, `corpus_ingest`, `corpus_job`). The admin profile can be disabled
without disabling web administration. Distinct tokens and middleware enforce the
boundary across MCP and REST; query access also supports a collection allowlist.
The admin UI retains collection creation, model/chunk overrides, roots/scans,
uploads, source inspection, jobs/SSE, search, manifests, vacuum, rebuild and
confirmed deletion. Specialized REST routes remain available to administrators.

Search now exposes raw/LLM output and source graph-context options. A read-only
graph explorer supports candidate discovery, exact-ID follow-up, callers/callees,
dependencies, inheritance, impact and configurable traversal limits. Raw views
include entity/relationship inspection and complete JSON; LLM views preserve the
server's text with copy/select controls. See [WEB_UI.md](docs/WEB_UI.md).

The service provides password/token authentication and a shared-secret boundary for an OAuth reverse proxy. OAuth itself remains the reverse proxy's responsibility. Host/origin checks and source-root checks apply to REST and MCP.

## Known limitations

- Knowledge Cards are implemented; no custom document-type policy language or automatic source summarization yet.
- Source graph resolution is best-effort static analysis, not runtime or compiler verification; unsupported languages retain heuristics. Layout/reading-order quality depends on the chosen extractor.
- The Markdown renderer is deliberately simple; complex table, equation, footnote and image layouts are not losslessly reconstructed.
- DRM-protected and unusual fixed-layout Kindle files are not guaranteed; real non-empty PDF passwords are unsupported.
- OCR/converter/transcription adapters are contract-tested with fake executables. Their real models, GPU environments and version-specific output variations require deployment smoke tests.
- The vector path computes exact distances and applies filters without candidate starvation. It is not an ANN index and will require optimization for very large collections.
- External commands have timeout/environment controls, not network, filesystem or OS-level containment. Administrators must trust configured tools.
- Chunk offsets are Unicode character positions in reconstructed extracted text, not byte offsets.
- The Python application depends on packages that may ship compiled wheels.
