# PDF backend selection

PDF dependencies and execution policy are separate choices. Installing an optional
backend never silently activates it; an explicit backend also never silently
activates an unrelated optional native library.

## Recommended setup for PDF chapter detection

**PDF chapter detection requires MinerU or Marker in ragdbman's current pipeline.**
For textbooks, manuals and other long PDFs where chapter/section boundaries
matter, install and configure one of these converters as the recommended setup.
They are optional dependencies for basic PDF text retrieval, but they are the
required conversion route for PDF heading-based chapter/section chunking.

ragdbman reads the Markdown headings produced by the selected converter and
passes them to the heading-aware chunker. It does not independently infer a PDF
table of contents or guarantee that every chapter will be recognized. The
current pypdf and PyMuPDF adapters emit text blocks with page information rather
than heading structure; installing PyMuPDF alone does not enable chapter detection.

Recommended MinerU setup:

```toml
[media]
pdf_backend = "mineru"
mineru_command = "mineru"
mineru_cli = "legacy" # choose the interface supported by your installation
pdf_fallback = false
subprocess_timeout_seconds = 1200
```

Alternatively, configure a separately installed Marker executable:

```toml
[media]
pdf_backend = "marker"
marker_command = "marker_single"
pdf_fallback = false
subprocess_timeout_seconds = 1200
```

The Marker adapter calls `COMMAND INPUT --output_dir SCRATCH --output_format
markdown --paginate_output`. Check that your installed command or controlled
wrapper supports these arguments. Both executables must be available to the
daemon, including in its systemd environment; installation alone is insufficient
without command/backend configuration.

Keep `pdf_fallback = false` when heading structure is a requirement. Enabling
fallback permits successful text-only extraction via pypdf if conversion fails,
so the resulting index may lack chapter boundaries. This recommendation does not
change the shipped global default (`auto` with fallback enabled).

Verify a representative PDF by inspecting the generated Markdown headings
(for general collections), stored `chunks.heading` / `chunks.section_path`
values, or search provenance before indexing a large library. When changing
backends for already indexed PDFs, explicitly rebuild the collection after
confirmation; an unchanged-file scan does not re-extract identical source bytes.
Rebuild clears existing indexes before reindexing, so back up first.

This is heading/section-aware chunking, not one guaranteed chunk per chapter:
token limits and within-section splitting still apply. Converter quality on real
documents, including MinerU 3.4.5, remains an acceptance-test responsibility.

## Selection and fallback

| `media.pdf_backend` | Primary behavior | With `pdf_fallback = true` |
| --- | --- | --- |
| `auto` (default) | Configured MinerU, then configured Marker | pypdf, then raw stream recovery |
| `pypdf` | Only pypdf, ignoring configured external tools | pypdf-based raw recovery on failure |
| `mineru` | External `mineru_command` only | pypdf, then raw recovery; no Marker/PyMuPDF |
| `marker` | External `marker_command` only | pypdf, then raw recovery; no MinerU/PyMuPDF |
| `pymupdf` | Explicit optional PyMuPDF; Tesseract if configured | pypdf, then raw recovery |

Set `pdf_fallback = false` to propagate the selected backend's failure without
trying the next backend or raw recovery. In `auto`, this means the first configured
converter's failure stops the chain. Missing required command configuration or a
missing explicitly selected PyMuPDF installation is always an actionable error.
Successful fallback records warnings so reduced extraction quality is inspectable.

## pypdf without PyMuPDF

```sh
uv sync --locked
uv run python -c "import importlib.util; assert importlib.util.find_spec('pymupdf') is None"
```

```toml
[media]
pdf_backend = "pypdf"
pdf_fallback = true
```

pypdf is a required base dependency, so this selection needs no extra installation.
Neither production nor default development requirements install PyMuPDF. pypdf
extracts embedded text and page numbers; blank scanned pages are reported
instead of silently rendered through an optional library. Use MinerU or an
explicitly chosen OCR-capable backend for image-only PDFs.

## MinerU as an external tool

Use your existing MinerU installation or install it in its own environment
following the instructions for that version. Set `mineru_command = "mineru"` to
resolve the executable from the ragdbman service's PATH; an absolute executable
path can also be configured when needed. ragdbman does not import `mineru`,
install it as a dependency, download its models or alter its environment.

The maintainer plans to test with **MinerU 3.4.5**. That is an acceptance-test
target, not a claim of completed version-specific verification. Run
`mineru --version` and `mineru --help` in the environment that starts ragdbman,
then select the matching interface below. A systemd service may have a different
PATH from an interactive terminal.

For the directory-output command documented in the
[MinerU repository](https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/quick_usage.md):

```toml
[media]
pdf_backend = "mineru"
mineru_command = "mineru"
mineru_cli = "legacy"
mineru_extra_args = [] # add backend flags only if supported by your installed version
pdf_fallback = false
subprocess_timeout_seconds = 1200
```

The call is `COMMAND -p INPUT -o SCRATCH_DIR`, followed by the extra arguments.
The adapter searches nested output for Markdown, prefers a file matching the
input stem, and copies referenced local images into general-collection sidecars
before temporary outputs are removed.

For installations exposing the newer `parse` interface:

```toml
[media]
pdf_backend = "mineru"
mineru_command = "mineru"
mineru_cli = "parse"
mineru_extra_args = ["--wait", "1200"]
pdf_fallback = false
subprocess_timeout_seconds = 1300
```

The call is `COMMAND parse INPUT --pages all -o SCRATCH_DIR/document.md`,
followed by the extra arguments. The all-pages flag is intentional: the
[MinerU CLI documentation](https://opendatalab.github.io/MinerU/usage/cli_tools/)
states that this interface otherwise defaults to the first ten PDF pages.

Check your executable's `--help` to choose the matching interface and arguments.
The adapters are contract-tested with executable fixtures, not certified against
every upstream release. The `parse` command may maintain its own model/cache or
document-library state outside ragdbman's temporary directory.

Arguments are passed without a shell. Paths and full-document page selection
cannot be overridden through `mineru_extra_args`. A controlled wrapper can load
installation-specific environment settings that ragdbman's allowlisted process
environment intentionally does not inherit. External executables are trusted
administrator tools, not sandboxed code.

Both MinerU modes preserve the SourceCode rule: no `.ragdbman` directory, Markdown
sidecar or copied image tree is written beside those sources. General collections
still use inspectable Markdown sidecars.

## Optional PyMuPDF

```sh
uv sync --locked --extra pymupdf
uv run --extra pymupdf ragdbman serve
```

```toml
[media]
pdf_backend = "pymupdf"
tesseract_path = "/usr/bin/tesseract" # optional blank-page OCR
```

Review PyMuPDF's separate license before choosing this installation. The base
installation, `auto`, `pypdf`, and MinerU fallback do not need or import it.
See [LICENSING.md](LICENSING.md) for the license boundary and upstream references.
