# Authors

ragdbman is a project created and directed by Bela Istvan MIHALIK, developed
with assistance from [Perplexity Computer](https://www.perplexity.ai/).
The following credits distinguish project ownership and human direction from
AI-assisted implementation work.

## Bela Istvan MIHALIK

- **Original idea and vision:** Conceived the application, its purpose, and its
  inspectable, local document-intelligence approach; supplied the product vision.
- **System design and requirements:** Defined the desired workflows, functional
  requirements, collection semantics, and design constraints, including the
  distinction between source-code indexing and document-style indexing.
  Supplied the Knowledge Cards specification and representative card corpus.
  Supplied the CLI extension specification and Python API guide used for the
  implementation and documentation work. Requested the repository consistency
  review and more explanatory command-line help delivered in 0.5.4.
- **Technical and product direction:** Made the final decisions on technology,
  community focus, optional PDF backends, external-tool integration, and
  Apache-2.0 licensing; reviewed proposals and requested refinements.
- **Hands-on testing and feedback:** Tested development builds in the intended
  environment, supplied logs and observations, identified issues, and guided
  fixes. Real-world acceptance and release decisions remain with the project owner.

## Perplexity Computer

- **Architecture assistance:** Helped elaborate the system architecture and
  technical design under Bela Istvan MIHALIK's requirements and direction.
- **Code generation and implementation:** Generated and revised application code,
  database definitions, extraction adapters, indexing and retrieval logic,
  command-line and service interfaces, administrative UI, and supporting tooling,
  including the Knowledge Cards implementation and deterministic scoring details.
  Implemented Tree-sitter source graphs, provenance/recovery, search enrichment
  and graph traversal under the owner's requested design.
- **Automated testing and debugging:** Designed and generated test cases, executed
  automated suites and development-environment checks, investigated failures,
  and implemented corrections. Assisted with browser and packaging verification.
- **Documentation and release preparation:** Drafted and updated guides,
  configuration examples, feature and test documentation, packaging, CI
  configuration, and license notices at the project owner's direction.
  Performed the 0.5.4 source/documentation consistency review and generated
  executable drift checks and expanded command help under that direction.

## Scope of these credits

System design was collaborative, with human goals and decisions directing
AI-assisted technical work. Automated tests using fixtures or mocked services
are not a substitute for the owner's real-environment testing, and these credits
do not imply that every external converter, model, or deployment has been verified.

Third-party libraries, tools, and models retain their own authorship and licenses.
See [LICENSE](LICENSE), [NOTICE](NOTICE), and
[dependency licensing](docs/LICENSING.md) for the project's licensing boundaries.
