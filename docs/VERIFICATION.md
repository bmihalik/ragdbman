# Release verification

This record distinguishes automated development checks from real-environment
acceptance. It is not production certification or an evaluation of real model
quality; reproduction instructions are in [TESTING.md](TESTING.md).

## Version 0.4.2

Scan-progress and source-text admission checks ran on Linux on 26 September 2026:

| Interpreter | Installation/profile | Result |
| --- | --- | --- |
| CPython 3.12.13 | Editable base, complete suite | 375 passed, 2 optional tests skipped |
| CPython 3.12.13 | Editable PyMuPDF extra, complete suite | 377 passed |
| CPython 3.11.15 | Installed base wheel, progress/sniff/metadata tests | 43 passed |
| CPython 3.13.12 | Installed base wheel, progress/sniff/metadata tests | 43 passed |

The focused wheel runs are not claimed as complete Python 3.11/3.13 suite reruns.
Base-profile statement coverage remains approximately 93%.

Forty added cases cover candidate totals before the first embedding finishes,
processed/percentage calculations, elapsed/ETA formulas, unavailable estimates,
empty scans, cancellation, resumed attempts, stopped-time freezing and recovery
without counting daemon downtime. Text detection cases cover the requested
filenames, Unicode encodings, multibyte probe boundaries, binary signatures,
control bytes, binary tails, skipped-file retry, line provenance and intact
oversized source lines. General-collection admission remains unchanged.

Chromium checks used synthetic files and delayed deterministic embeddings, not
production data or a real model. A source-code scan showed 1/33 processed and an
approximate ETA while indexing, remained navigable through the overview, froze
timing on cancellation, resumed, and finished at 33/33 (100%) with zero remaining
time. Reloading preserved the final elapsed time. Desktop 1280px and mobile 375px
views were inspected, including dark mode; no page errors or horizontal overflow
were recorded. The new browser checks supplement the HTTP responsiveness tests.

The following records describe earlier verification baselines.

## Version 0.4.1

The metadata/documentation release was checked on Linux on 26 September 2026:

| Interpreter | Installation/profile | Result |
| --- | --- | --- |
| CPython 3.12.13 | Locked editable base, no PyMuPDF | 335 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable with explicit `pymupdf` extra | 337 passed |

CITATION.cff passes the CFF 1.2.0 schema using `cffconvert`. CodeMeta JSON-LD
expansion through PyLD resolves all nine metadata properties against the published
CodeMeta 3.1 context and preserves the release version and author. Offline tests
check identity, author, license, release dates, description/keywords and version
agreement with package metadata, plus the wheel inclusion plan.

The built wheel contains both files under `ragdbman/`; the source distribution
contains both at its root. Their bytes match the source files. Ruff, license-header
and whitespace checks pass. No extraction, indexing, MCP, authorization or database
schema behavior changed. The following 0.4.0 matrix is retained as a functionality
baseline, not represented as fresh 0.4.1 Python 3.11/3.13 runs.

## Version 0.4.0 functionality baseline

The following checks were executed on Linux on 24 September 2026.
Installed-wheel suites run outside the source directory and import the package
from isolated environments, not the editable checkout.

| Interpreter | Installation/profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Base wheel, no PyMuPDF | 332 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, no PyMuPDF | 332 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable with explicit `pymupdf` extra | 334 passed |
| CPython 3.13.12 | Base wheel, no PyMuPDF | 332 passed, 2 optional tests skipped |

The skipped tests cover optional PyMuPDF extraction and PDF-rendering/OCR.
Base-profile statement coverage is approximately 93%, not branch coverage or a
guarantee for all inputs. Dependency deprecation warnings from Starlette's
TestClient and mobi's imghdr import are reported rather than suppressed.

Ruff lint/format and first-party Apache-2.0 header checks pass. Wheel and source
distribution builds include LICENSE/NOTICE, the guarded executable launcher,
MCP contracts and documentation. The base environment does not install PyMuPDF
or MinerU. The CI matrix defines Python 3.11–3.13 and optional-backend profiles;
this table records actual local checks, not an unexecuted remote CI run.

## Corpus interface and authorization

Thirty-nine new cases cover:

- Exact two-tool query and five-tool admin discovery over MCP Streamable HTTP.
- Initialization, tool calls and explicit structured/text envelopes.
- Query-only denial for guessed mutation tools, the admin endpoint, anonymous
  administrative requests, and direct REST/web bypass attempts.
- Hidden admin MCP with authenticated web administration still available.
- Missing/equal credentials, admin-only local authentication, collection
  allowlists, explicit defaults and fail-closed unauthorized selection.
- Unified keyword/semantic/hybrid queries with general/expert perspectives
  across documents, source code and Knowledge Cards, global limits and ranks.
- Confidence thresholds, unsupported-filter diagnostics, per-collection failures
  and card keyword fallback when Ollama is unavailable.
- Action-specific management validation, creation/inspection/updates, roots,
  scans, rebuild/removal confirmation, uploads, jobs, cancellation/resume,
  manifests, vacuum and deletion.
- Filename/base64 validation, empty query/limit validation and invalid MCP paths.
- Numbered card rendering, dynamic Markdown fences, top-level ID suppression
  and preservation of code strings with trailing newlines.

The test suite uses real SQLite/FTS5/sqlite-vec and HTTP/MCP routing. Engine tests
inject deterministic embeddings and provider contract tests use HTTP mocks.
Production has no synthetic-vector fallback. Authentication tests establish
the application boundary; they are not a deployment penetration test or protection
against an actor that controls the daemon's operating-system account.

## Existing application regression coverage

Document extraction, source-code sidecar suppression, deliberate general-collection
code indexing, tokenization, filters, durable jobs, restart recovery and SQLite
transactions remain covered. Blocking-stage tests request overview/job endpoints
while parsing, chunking, writes or pruning remain held open, and cancellation
tests verify rollback, retained mutation ownership and worker/subprocess cleanup.

Launcher tests exercise direct script and module execution, imports from the
checkout root, virtual-environment selection, executable permission and resource
lookup under source-qualified package imports. A hostile same-named launcher must
not be imported when loading UI/static resources or either database schema.

## Knowledge Cards corpus checks

The supplied archive was verified during Knowledge Cards development: 533 valid
cards, no duplicate IDs, 1,770 field embeddings, 533 unchanged-file skips on rescan,
all six retrieval/query-type combinations and every ID-free YAML-value roundtrip.
`tools/check_card_corpus.py` provides the opt-in reproduction command.
The original archive was not modified, redistributed or relicensed in the source
package. These checks use deterministic vectors, not actual relevance judgments.

## Browser and external-tool boundaries

Existing interface browser checks covered collection creation, scans and overview
navigation during indexing, Knowledge Cards modes/thresholds and YAML display,
desktop/mobile layouts and mobile dark mode. This MCP-focused release preserves
those views; its new web authentication boundary is exercised through HTTP tests,
not claimed as a fresh exhaustive browser audit.

MinerU, Marker and other converter integrations are tested with temporary
executable fixtures. Real upstream models/tools and output quality are not certified.
Bela Istvan MIHALIK's MinerU acceptance target remains 3.4.5, invoked as `mineru`
through the daemon's PATH. The daemon does not import or bundle MinerU.

## Deployment acceptance still required

- Real Ollama model compatibility and semantic ranking quality.
- The intended MCP client, its credential storage and Streamable HTTP setup.
- MinerU 3.4.5 scientific-document conversion and other configured external tools.
- Representative DRM-free MOBI/AZW3 inputs.
- Large-corpus memory, latency and concurrency behavior.
- Remote TLS/proxy/firewall policies and complete dependency/license review.

No user production databases were opened or altered during these checks.
