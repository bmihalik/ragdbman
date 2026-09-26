# Configuration

Knowledge Cards also expose four environment defaults, validated at daemon
startup: `RAGDBMAN_KC_DEFAULT_TOP_K=3`, `RAGDBMAN_KC_MIN_SIMILARITY=0.65`,
`RAGDBMAN_KC_ALPHA_NEGATIVE=0.30`, and `RAGDBMAN_KC_BETA_DESCRIPTION=0.20`.
See [Knowledge Cards](KNOWLEDGE_CARDS.md) for ranges, scoring and request overrides.

The daemon reads TOML from `~/.config/ragdbman/config.toml`. Every command accepts `--config PATH`; missing sections use defaults, malformed or unknown settings fail with `CONFIG_INVALID`.

Run `uv run ragdbman init` to write the complete current defaults. The command refuses to overwrite an existing configuration and includes commented examples for optional tools.

## Server and security

| Setting | Default | Meaning |
|---|---|---|
| `server.bind` | `127.0.0.1` | Listen address |
| `server.port` | `8765` | HTTP, UI and MCP port |
| `server.mcp_path` | `/mcp` | Endpoint prefix: `/query` and `/admin` are appended |
| `server.mcp_admin_enabled` | `false` | Expose the separate administrative MCP profile |
| `server.mcp_default_collections` | `[]` | Explicit scope when query omits `collections`; empty requires caller selection |
| `server.mcp_allowed_collections` | omitted | Query-profile allowlist; omitted permits explicit access to all, `[]` permits none |
| `server.web_auth_mode` | `local` | `local`, `password`, or `oauth_proxy` |
| `server.allow_remote_bind` | `false` | Non-loopback access requires this plus auth |
| `security.allow_file_uri_links` | `true` | Include local file links in results |
| `security.allow_http_source_urls` | `true` | Include persisted original URLs in results |
| `security.allow_arbitrary_paths_from_mcp` | `false` | Bypass source-root allowlist across interfaces; strongly discouraged |

`RAGDBMAN_AUTH_TOKEN` is the administrator secret. Set a distinct
`RAGDBMAN_QUERY_TOKEN` for query-only agents. MCP always requires Bearer
authentication, even on loopback. Configuring a query token or enabling admin MCP
also requires the admin secret. Any configured admin secret forces authentication
on web/REST routes, including in `local` mode. Query credentials never authorize those routes.
An unconfigured loopback-only UI remains usable without MCP access.

REST administrators send `Authorization: Bearer <admin token>`; browsers in
`password` mode, or protected `local` mode, use HTTP Basic with the admin token
as password. The username is not used. Do not put credentials in URLs or commit
them into configuration. Credentials are read at app creation: restart after
changing them. See [MCP setup](MCP.md).

For `oauth_proxy`, an authenticated reverse proxy must inject `Authorization: Bearer <token>` after validating the user, and strip any client-supplied copy. Set the same `RAGDBMAN_AUTH_TOKEN` on the daemon. The application is not an OAuth provider or token validator for arbitrary third-party JWTs.

Use TLS at the proxy, firewall the backend, and do not expose a local-mode server publicly. Origin checks reject cross-origin browser requests, and local mode rejects non-loopback hostnames.

## Storage

| Setting | Default |
|---|---|
| `storage.data_dir` | `~/.local/share/ragdbman` |
| `storage.registry_path` | `~/.config/ragdbman/collections.json` |
| `storage.temp_dir` | `~/.local/share/ragdbman/tmp` |
| `storage.allowed_source_roots` | `[]` |
| `storage.audit_log_retention_days` | `365` |
| `storage.markdown_sidecar_enabled` | `true` |
| `storage.markdown_sidecar_dir_name` | `.ragdbman` |

Paths expand `~`. External source paths must resolve inside an allowed root; managed uploads are allowed within their collection. A sidecar name must be a single directory name, never a path. Source-code collections always override sidecars to disabled.

`temp_dir` is reserved and does not currently select converter workspaces; these use `media.scratch_dir` or the system temporary directory. The archive does not contain user databases or cached models.

## Embeddings

| Setting under `[ollama]` | Default |
|---|---|
| `base_url` | `http://127.0.0.1:11434` |
| `embedding_model` | `bge-m3:567m` |
| `source_code_embedding_model` | `unclemusclez/jina-embeddings-v2-base-code:f16` |
| `keep_alive` | `24h` |
| `request_timeout_seconds` | `300` |
| `embedding_batch_size` | `32` |
| `max_concurrent_embedding_requests` | `1` |
| `health_check_seconds` | `30` |
| `bge_m3_options` | `{}` |

Requests use `/api/embed`, include `keep_alive`, and set `truncate=false`. Output counts, dimensions, and finite numeric values are checked; there is no fallback to fake or zero embeddings.

`bge_m3_options` is forwarded only for model names beginning with `bge-m3`. Use it for real Ollama runtime options, not an invented reasoning-effort parameter:

```toml
[ollama.bge_m3_options]
num_thread = 8
num_ctx = 8192
```

`health_check_seconds` is retained in the configuration model; health probes currently run on request rather than in a background polling loop. The concurrency limit applies across collections sharing the client.

## Scan and chunk defaults

| Setting under `[defaults]` | Default |
|---|---|
| `chunk_size_tokens` / `chunk_overlap_tokens` | `256` / `64` |
| `scan_batch_size` | `100` |
| `max_file_size_mb` | `500` |
| `recursive_scan` | `true` |
| `follow_symlinks` | `false` |
| `store_derived_text` | `true` |
| `preserve_artifacts` | `true` |
| `index_hidden_files` | `false` |
| `allow_approximate_tokenizer` | `false` |
| `locale` | `en` |

`[source_code]` defaults are `chunk_size_tokens=400` and `chunk_overlap_tokens=60`. Overlap must be nonnegative and smaller than size. An exact tokenizer is resolved for the actual collection model, not the global default.

The worker processes one file at a time per collection; `scan_batch_size` is reserved and is not a concurrency control. The recursive scan request defaults to true and can explicitly override recursion. Derived extracted text is stored in the artifacts table when enabled; converter scratch files are cleaned up after each call regardless of the reserved `preserve_artifacts` setting. Persistent sidecars are controlled by the sidecar settings.

## Search

Under `[search]`, defaults are `default_top_k=8`, `max_top_k=50`, `vector_weight=0.65`, `keyword_weight=0.35`, `rrf_k=60`, and `return_context_chars_per_chunk=2400`. Requested result counts are capped at `max_top_k`.

Hybrid scoring uses each channel's rank with the configured weight. Multi-collection scoring uses independent collection ranks to avoid comparing different model distance scales directly.

## Optional converters

```toml
[media]
pdf_backend = "auto"  # auto | pypdf | mineru | marker | pymupdf
pdf_fallback = true
mineru_cli = "legacy" # legacy (-p/-o directories) | parse (all-pages Markdown file)
mineru_extra_args = []
ffmpeg_path = "/usr/bin/ffmpeg"
subprocess_timeout_seconds = 600
transcription_language = "auto"
whisper_backend = "whisper_cpp"
keep_extracted_audio = false

# Install tools separately, then enable only those needed.
# libreoffice_path = "/usr/bin/soffice"
# tesseract_path = "/usr/bin/tesseract"
# marker_command = "/path/to/marker-env/bin/marker_single"
# mineru_command = "mineru" # resolved from the service's PATH
# whisper_command = "/usr/local/bin/whisper-cli"
# whisper_model_path = "/path/to/ggml-model.bin"
# scratch_dir = "/path/visible/to/containerized/tools"
```

- `whisper_cpp`: `-f WAV --output-json --output-file BASE -l LANG`; optional `-m MODEL`. Read `BASE.json` with millisecond `transcription[].offsets`.
- `faster_whisper`: `WAV --output_format json --output_dir DIR --language LANG`; optional `--model MODEL`. Read `audio.json` with second-based `segments`.
- `external_command`: `COMMAND WAV LANG`. Parse second-based `segments` JSON from stdout.
- MinerU (`mineru_cli = "legacy"`): `-p INPUT -o OUTPUT_DIR`, followed by `mineru_extra_args`.
- MinerU (`mineru_cli = "parse"`): `parse INPUT --pages all -o OUTPUT_FILE.md`, followed by `mineru_extra_args`.
- Marker: `INPUT --output_dir OUTPUT_DIR --output_format markdown --paginate_output`.
- Tesseract: `INPUT stdout`.
- LibreOffice: `--headless --convert-to FORMAT --outdir OUTPUT_DIR INPUT`, with a private user profile.

Commands run with an allowlisted environment, so model/provider secrets are not inherited automatically. If a trusted converter requires additional settings, use a controlled wrapper script that loads its own environment. This is deliberately not a credential passthrough mechanism.

`auto` preserves preference for configured external converters but uses only pypdf
as the built-in backend. `pypdf` bypasses all external converters and PyMuPDF.
Selecting `mineru` or `marker` requires its command; a missing selection-specific
command is a configuration error, not a silent fallback. Selecting `pymupdf`
requires installing the separate `pymupdf` extra. With fallback enabled, a failed
selected external converter/PyMuPDF extraction falls back to pypdf and then raw
stream recovery. With fallback disabled, errors propagate and raw recovery is
also disabled. See [PDF_BACKENDS.md](PDF_BACKENDS.md) for complete examples.

`mineru_extra_args` must be an array of separate argument strings, not a shell
command. Input/output paths and `--pages` are owned by ragdbman and cannot be
overridden there. Use only flags supported by your installed version.

## Logging

`[logging] level` accepts `error`, `warn`, `info`, `debug`, or `trace`. `RAGDBMAN_LOG` overrides it; Python maps trace to debug.

Debug logs include command arguments, resolved executable/shebang, return codes and bounded output excerpts. Noisy Python PDF-library warning/error events are summarized per extraction. Source-level warnings and durable job errors remain inspectable through the API and database.
