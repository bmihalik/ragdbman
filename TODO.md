# Roadmap

Future work is guided by the [product vision](docs/VISION.md). Source-code collection sidecar suppression is an explicit design decision.

## Document intelligence

- Extend Knowledge Cards with authoring/curation workflows; structured YAML indexing and retrieval are implemented.
- Define configurable document-type chunking policies for textbooks, research papers and code.
- Add AST-aware source boundaries while retaining line-citation fallback.
- Preserve richer tables, equations, footnotes, images and original page anchors through Markdown materialization.
- Recover MinerU page/region provenance from structured converter output.
- Add an editing/reindex workflow for manually curated sidecars; current rescan decisions use original-source hashes.

## Reliability and scale

- Benchmark exact vector search against large collections and add an index strategy without sacrificing filter correctness.
- Profile large-search and explicit maintenance workloads for remaining event-loop latency.
- Introduce cross-process worker leases before supporting multiple daemon processes on one data directory.
- Add bounded resource consumption for decompression, converter output and complex malformed files.
- Offer a transactional rebuild mode that swaps complete indexes rather than clearing first.
- Add real-tool CI matrices for supported LibreOffice, Tesseract, Whisper, Marker and MinerU versions.
- Expand real-book, scanned-PDF and non-Latin fixture coverage.
- Review reserved configuration settings that currently have no active worker behavior.

## Community readiness

- Fast-follow: add a web chunk browser for all chunks of a source, with full text,
  boundaries and provenance; current inspection uses sqlite3 or search responses.
- Review the exact selected dependency/converter/model licenses for each distributed deployment bundle.
- Expand the deployment matrix beyond Linux.
- Test and document the intended Hermes-Agent deployment directly.
- Add richer browser controls for numeric/date filters instead of requiring JSON.

General collections intentionally index source code as documents. There is no TODO to “fix” that behavior by silently forcing code-style indexing.
