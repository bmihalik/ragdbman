# Licensing and optional PDF dependencies

ragdbman is licensed under Apache-2.0 at the project owner's direction.
The copyright notice is `Copyright 2026 Bela Istvan MIHALIK`; the full license
is in `LICENSE` and project attribution is in `NOTICE`.

## Project files

Package metadata uses the SPDX identifier `Apache-2.0`. First-party Python,
JavaScript, CSS, HTML, SQL, build configuration, CI and service files carry SPDX
copyright/license headers. LICENSE and NOTICE are included in the wheel, source
distribution and downloadable source archive. Authorship and development
contributions are described in `AUTHORS.md`.

The license text is the standard
[Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0.txt).
Third-party notices must not be replaced with the project's header; the project's
license does not change a dependency's or model's terms.

## PDF installation choices

- **pypdf:** included in the base installation; its upstream project identifies
  its license as BSD-3-Clause in the
  [pypdf FAQ](https://pypdf.readthedocs.io/en/stable/meta/faq.html).
  Choosing this route removes the need to install or invoke PyMuPDF; it does not
  remove attribution/notice obligations for pypdf or other dependencies.
- **PyMuPDF:** excluded from default runtime and development requirements, available
  only through the `pymupdf` extra and explicit backend selection. Its upstream
  documentation describes AGPL and commercial options in the
  [PyMuPDF licensing section](https://pymupdf.readthedocs.io/en/latest/about.html).
  Installing it into an existing environment, even outside ragdbman, is a separate
  choice; check your complete deployment rather than just this package metadata.
- **MinerU and Marker:** optional separately installed external programs. ragdbman
  passes arguments and reads conversion output without importing or bundling their
  packages, models or transitive dependencies. External execution is a technical
  integration boundary, not a claim that their licensing obligations disappear.
  Review the exact tool versions, model weights and any redistribution bundle.

The lockfile contains optional PyMuPDF resolution information for reproducible
extra installs. A lockfile entry is not a bundled library or an installed
dependency. A fresh `uv sync --locked` base environment is tested to contain no
PyMuPDF installation.

## Source parser dependencies

The base environment installs Tree-sitter and individual language grammar
packages. ragdbman does not vendor grammar source or replace upstream notices,
and never downloads grammars while indexing. The locked package versions are
recorded in `uv.lock`; include their original notices when redistributing an
environment containing those wheels. This does not change ragdbman's Apache-2.0
license or the separate PDF backend choices.

## Distribution checklist

Include LICENSE and NOTICE, preserve first-party copyright notices, and retain
required third-party notices when redistributing dependencies. Check any optional
converter/model bundle separately and do not describe the complete stack as
license-free. This file documents package boundaries and is not a comprehensive
legal audit of every deployment.
