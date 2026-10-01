# Contributing

ragdbman's application code is Python. Keep the shared Engine as the owner of
collection/index/search behavior, so REST, MCP, and the browser do not drift into
separate implementations.

## Local workflow

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

Develop against temporary sources and disposable databases. Never use a private
production corpus as a committed fixture. Add focused unit tests and an engine or
transport regression for changes that affect the external contract.

## Design rules

- Preserve all three collection kinds. Source-code collections must never create
  Markdown sidecars, while general collections may deliberately index code as
  documents. Knowledge Cards retain whole-field YAML indexing without sidecars.
- Preserve stable source IDs, transactional updates, explicit deletion
  confirmation, and original-file protection.
- Validate all embedding vectors and dimensions; never hide provider errors by
  synthesizing vectors.
- Keep external commands opt-in, argument-based rather than shell strings, and
  bounded by timeout. Document changes in executable contracts.
- Test complete fresh database initialization, repeated initialization, and
  preservation of indexed data and search results across normal restarts.
- Keep user text escaped in the UI and validate HTTP/MCP paths and requests.
- Keep vision items in the roadmap until their implementation and tests exist.

## Tests and fixtures

The test-only embedder is explicitly isolated in `tests/conftest.py`. Generated
Office/PDF fixtures keep the repository small and reproducible. Optional external
tools use fake executable contracts in ordinary CI; test real installed tools
separately before claiming support for a new upstream version.

For source-language changes, include representative syntax for that language
rather than testing only a renamed Python file. For chunking, test text offsets,
line/page/section boundaries, overlaps, oversized atomic input, and Unicode.

## Sharing a release

Review `README.md` and `docs/VERIFICATION.md`, run the base and optional-PDF
test profiles, smoke-test an installed wheel, and update the changelog. ragdbman
uses Apache-2.0; include LICENSE and NOTICE in all release artifacts. Keep
first-party SPDX headers consistent using `python tools/license_headers.py`
or add them with `--write`. Do not replace third-party copyright notices.

Review dependency obligations separately. Never add PyMuPDF to the base
requirements or silently load it in `auto`/`pypdf` mode; the explicit optional
dependency boundary is intentional. MinerU remains a separately installed
executable, not an imported dependency. See `docs/LICENSING.md`.
