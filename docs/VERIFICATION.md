# Release verification

This record distinguishes automated development checks from real-environment
acceptance. It is not production certification or an evaluation of real model
quality; reproduction instructions are in [TESTING.md](TESTING.md).

## Version 0.6.0

Canonical-interface implementation and release packaging were checked on Linux
on 1 October 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 614 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 614 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 616 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 614 passed, 2 optional tests skipped |

Full suites ran serially, with installed-wheel runs outside the source checkout.
The catalog has 28 service operations, available in CLI/REST/Python and on
the optional admin MCP endpoint. Query MCP retains exactly three read-only
corpus operations. Tests compare registered REST operation IDs, MCP tool fields,
Python methods and CLI contracts against the shared catalog.

Cross-interface tests verify raw corpus query/graph parity, flat MCP arguments,
strict unknown-field rejection, per-operation boolean annotations, query scope,
confirmation checks, and removal of old tool/route/CLI aliases. Existing tests
were ported to the canonical names; lower-level retrieval tests continue to
exercise internal implementations without exposing competing public query APIs.
The 60 CLI cases retain real foreground/daemon subprocess, ownership, signal,
watch/cancel/resume, upload/collection and query workflows.

Both Chromium regressions passed after the browser requests were converted to
canonical POST endpoints. They cover source/card/multiple-collection queries,
raw/LLM formats, graph controls and selection, errors, escaping, clipboard
fallback, mobile width, and stable job inspection.
A separate disposable live server was checked through visible controls for
collection creation, base64 upload/indexing, root registration/scanning,
manifest inspection, raw/LLM retrieval and source graph traversal. Desktop
and mobile/light-dark views were inspected without page errors or horizontal
overflow. These checks use deterministic embedding fixtures, not real models.

Ruff, formatting, first-party Apache-2.0 headers, JavaScript syntax, lockfile
consistency and wheel/sdist builds pass. The generated `docs/INTERFACES.md`
matches the operation catalog and is checked by the test suite.
The full SDK teardown/discovery tests remain part of every run.

Real Hermes/client acceptance, real Ollama retrieval quality, MinerU 3.4.5 and
other converter deployments remain separate acceptance work. Existing indexes
need no rebuild for this release. Earlier records below describe their actual
historical releases, not the current supported interface vocabulary.

## Version 0.5.4

Repository consistency, expanded CLI help and release packaging were checked
on Linux on 30 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 606 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 606 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 608 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 606 passed, 2 optional tests skipped |

The new consistency module validates all 31 command help pages, every option
description and parseable example, and binds all 27 service command examples
to current Engine signatures without opening user storage. It checks current
TOML examples against `GlobalConfig`, relative Markdown links, API.md methods
and paths against FastAPI decorators, Python-guide Engine calls against current
signatures, and literal `RagError` codes against HTTP status mappings.

That review found and corrected three behavioral/documentation problems:
empty result tables lost collection/filter diagnostics; invalid and duplicate
Knowledge Cards fell through to HTTP 500 despite having stable application
codes; and CLI/version/count/reserved-setting prose had drifted. REST integration
now verifies malformed card YAML returns 422, duplicate card IDs return 409,
and the original indexed card remains unchanged.

Both optional Chromium regressions passed, covering stable job inspection and
the complete search/graph UI fixture. JavaScript syntax, Ruff, Python formatting,
lockfile consistency, first-party Apache-2.0 headers and wheel/sdist builds pass.
The rebuilt wheel contains CLI help, SQL/static resources, citation metadata,
LICENSE and NOTICE.

The review record in [CHANGELOG at 0.5.4](../CHANGELOG.md) describes the inspected
surfaces and boundaries. Automated consistency checks cannot prove prose
completeness, external-link availability, model quality or real converter/client
compatibility. Real Hermes, Ollama, MinerU 3.4.5 and non-Linux acceptance remain
outside these local checks.

## Version 0.5.3

### Tool-annotation follow-up

The 30 September annotation follow-up retains version 0.5.3 and explicitly
declares all four boolean hints on each of the six tool decorators. Before
the fix, new HTTP wire tests failed on missing `idempotentHint` while showing
the other three hints already present. After the fix:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.12.13 | Locked editable base, complete suite | 544 passed, 2 optional tests skipped |
| CPython 3.11.15 | Rebuilt installed base wheel, MCP capability suite | 24 passed |
| CPython 3.12.13 | Locked editable PyMuPDF extra, MCP capability suite | 24 passed |
| CPython 3.13.12 | Rebuilt installed base wheel, MCP capability suite | 24 passed |

The two new cases verify every tool name, hint presence, exact boolean type
and intended value on both authenticated profiles' actual `tools/list` JSON.
Ruff, formatting and first-party license-header checks pass. This follow-up
does not claim full extra-profile or full 3.11/3.13 reruns; their complete-suite
baselines are recorded below. The m8ven scanner and OpenAI directory were not
run as acceptance checks, and annotations alone do not establish approval.

### Initial capability/dependency patch

MCP capability/dependency changes and release packaging were checked on Linux
on 30 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 542 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 542 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 544 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 542 passed, 2 optional tests skipped |

All runs used MCP SDK 1.30.0 and AnyIO 4.15.1. Full suites ran serially,
and installed-wheel suites ran outside the source checkout. Wheel metadata
was inspected and tested for the `mcp>=1.30.0,<2` requirement.

The 22 new cases exercise actual HTTP initialization for both authenticated
profiles, absence of prompt/resource capability fields, unchanged three/six
tool counts, usable `corpus_describe`, and Method Not Found responses for
unused prompt/resource/template/subscription operations. Each profile receives
ten serial and twenty concurrent stateless pings, with successful JSON-RPC
results and no MCP ERROR logs.

A deterministic transport lifecycle test closes the stream before its router
begins receiving and verifies the expected terminated-stream DEBUG message.
A separate injected unexpected closure must still produce an ERROR carrying
`ClosedResourceError`. This verifies that the patch relies on SDK behavior
rather than hiding transport errors.

Ruff, formatting, lockfile consistency and first-party Apache-2.0 header checks
pass. Existing Starlette test-client and `imghdr` dependency deprecation warnings
remain; no new prompt/resource or transport warning suppression is introduced.
No frontend files were changed, so the browser checks below remain the latest
UI-specific verification rather than being claimed as rerun for this patch.

These are local automated checks, not a live Hermes acceptance test or proof
that every possible transport failure is resolved. The user's client must
reload/reconnect to refresh discovery. Real Ollama/model-quality and MinerU
3.4.5 acceptance boundaries remain unchanged.

## Version 0.5.2

### Web UI follow-up

The raw/LLM and graph UI update was checked on 28 September 2026 with CPython
3.12.13: **520 passed, 2 optional tests skipped** in the base profile, and
**522 passed** with the PyMuPDF extra. Two new route tests check graph-page
administrative authentication.

The Chromium `browser_search_graph.mjs` regression passes, covering query/card
format mappings, graph context, graph actions/options, exact entity selection,
empty/disabled/error states, escaped hostile evidence, clipboard-denial fallback
and mobile width. The existing `browser_job_record.mjs` regression also passes,
including actual mouse selection, stable DOM identity, expansion and focus.

Separate live-backend checks used an isolated synthetic repository and the real
Engine/SQLite/Tree-sitter pipeline with deterministic embedding fixtures.
Callers included local and imported functions with current source-line evidence.
Desktop and 375-pixel mobile layouts, light/dark themes and readable output were
inspected without page errors or horizontal overflow. These are development
checks, not real-user collection or embedding-quality acceptance.

### CLI release checks

CLI implementation and source packaging were checked on Linux on
28 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 518 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 518 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 520 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 518 passed, 2 optional tests skipped |

The 59 CLI cases cover all service-command contracts and REST route mappings,
global flag placement, numeric filters and malformed operands, confirmation
before engine construction, JSON/table/LLM output, exclusive manifest files,
watch snapshots and polling, unsafe remote URLs, administrative credentials,
ownership locks and transport failure behavior. Explicit empty daemon URLs
and empty identifiers are rejected; connection failure is verified not to
construct a local engine or create local storage.

Real subprocess workflows create/index/query/inspect/rebuild/delete temporary
collections through the actual CLI entry point. They verify that direct scans
complete rather than being paused by immediate engine closure, that Ctrl+C
pauses owned work and permits a later resume, that a competing direct command
cannot recover an owner's live jobs, and that daemon-mode start/watch/cancel/
resume operate through REST without taking local engine ownership. Finished-job
history is checked after an invalid cancellation request.

Embedding calls in these workflows use a local deterministic HTTP fixture,
not real Ollama models. Installed-wheel suites run outside the source checkout.
The Windows lock branch, non-Linux console behavior and network-filesystem
ownership semantics are not certified by this Linux matrix. Guards require
cooperating CLI/serve/embedded owners.

Ruff, formatting, lockfile and Apache-2.0 header checks pass. In-process statement
coverage is approximately 90%; separately spawned CLI/server/signal processes
are exercised but not included in that coverage percentage. The supplied
Python guide was corrected to current signatures and lifecycle semantics and
included as `docs/PYTHON_API_GUIDE.md`.

## Version 0.5.1

Output-format implementation and release packaging were checked on Linux on
28 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 459 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 459 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 461 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 459 passed, 2 optional tests skipped |

The 28 new formatting cases cover raw/LLM defaults and validation, MCP wire
responses on both profiles, text-only output without duplicate structured
content, raw envelope parity, REST content types and authorization, all graph
actions, uncertainty and truncation, candidate selection, safe inline labels
and adaptive fences, YAML code preservation, score policies and small-score
precision, general/card/source output, and unchanged embedding-call counts.
Existing card/MCP tests now explicitly distinguish default text from raw mode.

Tests use actual parsers/SQLite and deterministic embedding doubles. No
formatting request needs an LLM; native client frameworks such as Claude or
Perplexity were not individually tested. The default web UI JSON path and
all prior indexing/recovery/shutdown regressions pass. Complete matrix runs
were executed serially; installed-wheel tests run outside the source directory.
Ruff, formatting and first-party Apache-2.0 header checks pass.

## Version 0.5.0

Source-graph implementation and release packaging were checked on Linux on
26 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 431 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 431 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 433 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 431 passed, 2 optional tests skipped |

The 35 graph cases exercise actual installed Tree-sitter grammars for Python,
Rust, C, C++, JavaScript, TypeScript, TSX, Go, Java and C#. They cover cross-file
aliases/relative imports, trait implementation, inheritance, qualified bases,
metaclasses, mixed-language isolation, common shadowing, ambiguity, cycles,
limits, Unicode, syntax errors and unsupported formats.

Integration cases cover automatic enrichment and opt-out, readable MCP output,
authorized REST/MCP traversal and denied collection scope, stable source IDs,
fresh chunk citations after reindexing, stale-hit suppression, removal/pruning,
rebuild/deletion, unchanged backfill without embedding, graph-only failure
isolation, durable outbox replay and graph-commit-before-ack restart recovery.
The existing shutdown, concurrency, Knowledge Cards, extraction and UI API
regression tests remain in the complete suite.

Final matrix runs were serial to avoid competing process-timing fixtures.
An initial concurrent run of the optional profile hit two immediate
descendant-exit assertions; isolated complete reruns passed, including the
real SIGINT/SSE/converter-descendant tests. These tests remain Linux/POSIX
fixture checks, not verification of arbitrary external programs.

Ruff and first-party license-header checks pass. In-process statement coverage
is approximately 91% overall and 88% for the graph modules. Separately spawned
daemon processes are tested but not included in that coverage measurement.
Installed-wheel suites run from outside the source directory and exercise the
packaged graph SQL resource. Embedding tests use deterministic doubles; no
claim is made about real Ollama throughput, production repository completeness,
or compiler-accurate target resolution. The existing MinerU 3.4.5 real-environment
acceptance target is unchanged.

## Version 0.4.4

Logging, shutdown and indexing optimizations were checked on Linux on
26 September 2026:

| Interpreter | Profile | Result |
| --- | --- | --- |
| CPython 3.11.15 | Installed base wheel, complete suite | 396 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable base, complete suite | 396 passed, 2 optional tests skipped |
| CPython 3.12.13 | Locked editable PyMuPDF extra, complete suite | 398 passed |
| CPython 3.13.12 | Installed base wheel, complete suite | 396 passed, 2 optional tests skipped |

Installed-wheel tests run outside the source directory. The 21 additional cases
cover bounded file concurrency, one refresh per scan, batched vocabulary SQL and
deduplication, WAL NORMAL, reader/writer reuse, fresh-reader responsiveness during
a write transaction, metadata reuse, duplicate-card transactions, immediate
cancel/shutdown, runtime limits, debug/trace/verbose output and payload suppression.
Failure injection verifies that a failed final keyword refresh is reported as a
failed job, with committed source data retained.

Real subprocess tests launch `serve`, start a scan with an executable converter
fixture whose parent exits but leaves a child holding output pipes, keep an SSE
stream open, then send SIGINT. The daemon exits within the test's five-second
bound, leaves no running fixture child, persists the job as paused, and does not
use the emergency watchdog. Separate tests exercise converter timeout/cancellation
and the forced deadline with a non-cooperative thread. These are Linux/POSIX
fixture results, not certification of every external converter or platform.

The optional Chromium job-inspection regression still passes. Ruff, formatting,
license-header and build checks pass. In-process statement coverage is about 91%;
the separately launched server/signal processes are tested but are not included
in that in-process coverage percentage.

### Observed local performance fixture

One standalone run of `tools/benchmark_indexing.py` produced:

| Fixture | Reference/serial | Batched/concurrent | Observation |
| --- | --- | --- | --- |
| 20,000 keyword links, 200 unique terms | 0.1213 s, 20,000 SELECTs | 0.0494 s, 1 SELECT | About 2.5× faster in this microbenchmark |
| 32 sources, synthetic 40 ms embedding delay | 1.4485 s, one file in flight | 0.4309 s, four in flight | About 3.4× faster in this fixture |

Both scan measurements use the new implementation with different concurrency
settings; they are not an old-release versus new-release end-to-end comparison.
The vocabulary fixture compares the reference per-term algorithm with the batch
helper using the same data. Timings vary with machine/cache/load and do not
measure real Ollama, GPU or scientific-PDF conversion throughput. No universal
10–50× speedup is claimed. See [RUNTIME.md](RUNTIME.md) for operational and
power-loss durability trade-offs.

## Version 0.4.3

The job-inspection UI patch was checked on Linux on 26 September 2026 with
CPython 3.12.13: **375 passed, 2 optional tests skipped** in the base profile.
JavaScript syntax checks and the optional `tests/browser_job_record.mjs`
Chromium regression also passed. That regression verifies actual mouse selection,
stable inspection DOM nodes, expansion, keyboard focus, explicit refresh/reopen,
terminal-state updates and live counters using controlled progress events.

A separate real-daemon Chromium check used synthetic sources and delayed
deterministic embeddings. Opening the record, selecting text and waiting for
live SSE timing updates preserved both expansion and selected text. Refresh
replaced the snapshot explicitly; it stayed open and retained its snapshot after
completion. Desktop and mobile dark-mode views were inspected with no page errors
or horizontal overflow. This release changes the frontend only, besides release
metadata/documentation; optional-backend and cross-version records below remain
earlier verification baselines.

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
