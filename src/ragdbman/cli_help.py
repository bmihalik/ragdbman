# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Human-readable command contracts and examples; no execution behavior."""

COMMAND_HELP = {
    "serve": (
        "Run the web UI, REST API and authenticated MCP endpoints.",
        "Keep this process running to serve requests and indexing jobs. Bind address, port, "
        "source permissions and MCP profiles come from TOML. Ctrl+C stops owned work and "
        "cleans up. Use --server-url on service commands to control this daemon.",
        "ragdbman serve --log-level debug",
    ),
    "init": (
        "Write a new configuration file with documented defaults.",
        "Creates the parent directory, but never overwrites an existing file. Edit "
        "storage.allowed_source_roots before indexing. This does not start the daemon "
        "or download an embedding model.",
        "ragdbman init --config ~/.config/ragdbman/config.toml",
    ),
    "registry-repair": (
        "Reconstruct the collection registry from local databases.",
        "Opens local storage and performs normal engine startup recovery. Stop the daemon "
        "first: this command takes exclusive storage/registry ownership. It does not "
        "repair arbitrary SQLite corruption or re-embed sources.",
        "ragdbman registry-repair --config ~/.config/ragdbman/config.toml",
    ),
    "fetch-tokenizer": (
        "Download an exact tokenizer for an embedding model.",
        "Fetches tokenizer.json from a Hugging Face-compatible repository and saves it "
        "under the configured data directory. The repository must match the model. "
        "This downloads a tokenizer, not Ollama model weights.",
        "ragdbman fetch-tokenizer --hf-repo BAAI/bge-m3 --model bge-m3:567m",
    ),
    "health-status": (
        "Check the engine, SQLite vector extension and Ollama.",
        "Direct mode checks a newly opened local engine, not a separately running daemon. "
        "Use --server-url to check that daemon. Inspect the returned status fields: "
        "Ollama being unavailable is a diagnostic, not necessarily a command failure.",
        "ragdbman health-status --server-url http://127.0.0.1:8765 --format table",
    ),
    "list-collections": (
        "List collections, recorded settings and index counts.",
        "Returns the collections visible to the local owner or REST administrator. "
        "Use get-collection for one collection's full configuration and counts.",
        "ragdbman list-collections --format table",
    ),
    "get-collection": (
        "Inspect one collection's settings, counts and graph status.",
        "Shows the recorded embedding/chunk settings and managed paths. This is "
        "administrative inspection, not the restricted MCP discovery envelope.",
        "ragdbman get-collection --name code --format table",
    ),
    "create-collection": (
        "Create an empty document, source-code or Knowledge Cards collection.",
        "Probes the selected embedding model, so Ollama must be available. Registering "
        "source roots does not index them: run start-scan afterwards. Source-code and "
        "Knowledge Cards collections never create Markdown sidecars. Cards reject chunk overrides.",
        "ragdbman create-collection --name code --kind source_code --source-roots /data/repo",
    ),
    "update-collection-config": (
        "Change or clear a collection's description.",
        "Only the description is mutable here; omit --description to clear it. Model, "
        "collection kind and chunk strategy remain unchanged. Create another collection "
        "to use a different model or strategy.",
        'ragdbman update-collection-config --name code --description "Application sources"',
    ),
    "delete-collection": (
        "Delete a collection's databases after explicit confirmation.",
        "Requires --confirm. By default leaves managed originals and artifacts on disk. "
        "--delete-files also removes the collection directory; external source roots "
        "are never deleted. A busy collection cannot be deleted.",
        "ragdbman delete-collection --name old_docs --confirm",
    ),
    "list-source-roots": (
        "List a collection's registered source directories and root IDs.",
        "Use the returned root ID with remove-source-root. Registration describes "
        "scan roots; it is separate from indexing individual files.",
        "ragdbman list-source-roots --collection code --format table",
    ),
    "add-source-root": (
        "Register an allowed source directory without scanning it.",
        "The path must pass the configured source allowlist. Index it separately with "
        "start-scan; --no-recursive records a nonrecursive root.",
        "ragdbman add-source-root --collection code --path /data/repo",
    ),
    "remove-source-root": (
        "Unregister a root while preserving indexed sources and originals.",
        "Use a root ID from list-source-roots, not a path. This does not remove "
        "existing source records; use remove-source for explicit index removal.",
        "ragdbman remove-source-root --collection code --root-id ROOT_ID",
    ),
    "start-scan": (
        "Index new and changed files under an allowed directory.",
        "Unchanged files are skipped. Direct mode waits until the job stops; daemon "
        "mode returns a job ID unless --wait is set. --prune-missing --confirm removes "
        "derived index data for missing files, not files merely excluded by scan policy.",
        "ragdbman start-scan --collection code --root /data/repo",
    ),
    "add-file": (
        "Index or update one allowed file and wait for its result.",
        "Uses the collection's extraction, model and chunk settings. Does not copy an "
        "external file into managed storage. Returns the actual classification, such as "
        "new, changed, unchanged, unsupported or not_a_card.",
        "ragdbman add-file --collection books --path /data/books/paper.pdf",
    ),
    "remove-source": (
        "Remove a source and its derived index data after confirmation.",
        "Requires --confirm and a source ID from list-sources. Preserves the original "
        "unless --delete-original explicitly requests deletion of a managed upload. "
        "It cannot delete an external original.",
        "ragdbman remove-source --collection books --source-id SOURCE_ID --confirm",
    ),
    "get-job": (
        "Inspect one indexing job, or watch its progress.",
        "--watch emits snapshots every two seconds until the job stops, including "
        "paused or failed states. Use daemon mode while another process owns indexing. "
        "Watching does not resume a paused job.",
        "ragdbman get-job --collection code --job-id JOB_ID --watch --server-url http://127.0.0.1:8765",
    ),
    "list-jobs": (
        "List recent indexing jobs and their status/progress.",
        "Filter by status or limit the number of returned records. Job IDs from this "
        "command can be inspected, cancelled or resumed.",
        "ragdbman list-jobs --collection code --status failed --format table",
    ),
    "cancel-job": (
        "Request cooperative cancellation of an active indexing job.",
        "Uses a globally unique job ID. Use --server-url to cancel work owned by a "
        "running daemon. Committed files remain indexed; finished job history is not "
        "rewritten. Cancellation can require time for in-flight cleanup.",
        "ragdbman cancel-job --job-id JOB_ID --server-url http://127.0.0.1:8765",
    ),
    "resume-job": (
        "Resume an interrupted or partially failed scan/rebuild job.",
        "Accepts paused, failed, cancelled or completed-with-errors jobs. Rediscovers "
        "sources and skips current indexed hashes; counters and timing restart for "
        "this attempt. Direct mode waits; daemon mode needs --wait to wait.",
        "ragdbman resume-job --collection code --job-id JOB_ID",
    ),
    "search": (
        "Retrieve evidence from one collection.",
        "keyword uses text matching; vector uses embeddings; hybrid combines ranks; "
        "structured applies filters without embedding the query. Cards reject document "
        "filters and structured mode. --format llm renders readable evidence, not "
        "an AI-generated answer. Source graph context is automatic when available.",
        'ragdbman search --collection code --query "parse configuration" --format llm',
    ),
    "search-multi": (
        "Search selected collections and combine their ranked results.",
        "Uses each collection's recorded model, then combines ranks rather than raw "
        "scores. The result limit is global. Partial failures are reported; use JSON "
        "for machine-readable failure details. No implicit all-collections search.",
        'ragdbman search-multi --collections books,code --query "configuration" --format table',
    ),
    "search-knowledge-cards": (
        "Retrieve full Knowledge Cards using general or expert scoring.",
        "Only for knowledge_cards collections. Expert scoring weights applicability, "
        "counter-indications and description. Defaults come from the Knowledge Card "
        "settings, not ordinary document search. Use search --format llm for readable cards.",
        'ragdbman search-knowledge-cards --collection cards --query "shortest path" '
        "--query-type expert --minimum-similarity 0",
    ),
    "list-sources": (
        "List indexed/tracked source files with pagination and filters.",
        "Returns source IDs, paths and statuses, including unsupported or failed "
        "sources. Use get-source for detailed diagnostics.",
        "ragdbman list-sources --collection books --status failed --format table",
    ),
    "get-source": (
        "Inspect a source's metadata, status and extraction diagnostics.",
        "Accepts a source ID from list-sources. For chunk text, use search responses "
        "or inspect SQLite; this command is not a full chunk browser.",
        "ragdbman get-source --collection books --source-id SOURCE_ID",
    ),
    "list-keywords": (
        "Inspect the indexed keyword vocabulary and chunk frequencies.",
        "Optionally filter canonical terms by substring. Frequencies can be temporarily "
        "stale during a scan and refresh at its end. Card full-text search does not "
        "populate the ordinary document keyword vocabulary.",
        "ragdbman list-keywords --collection books --query config --format table",
    ),
    "list-metadata-fields": (
        "List numeric/date fields available for structured filtering.",
        "Shows canonical field names, types and aliases. Use these names with repeated "
        '--numeric filters, for example --numeric "amount greater_than 1000". '
        "Document structured filters are not supported for Knowledge Cards.",
        "ragdbman list-metadata-fields --collection books --format table",
    ),
    "export-collection-manifest": (
        "Export collection configuration and tracked-source metadata.",
        "Writes JSON to stdout unless --output names a new file. Does not overwrite "
        "existing files. A manifest is not a backup of SQLite indexes or original files.",
        "ragdbman export-collection-manifest --collection books --output books-manifest.json",
    ),
    "rebuild-collection": (
        "Clear derived indexes and reindex tracked sources.",
        "Requires --confirm. This clears first, not an atomic index swap; back up "
        "important data. Preserves recorded model/chunk settings. Direct mode waits; "
        "daemon mode returns immediately unless --wait is supplied.",
        "ragdbman rebuild-collection --collection books --confirm",
    ),
    "vacuum-collection": (
        "Reclaim unused pages in the collection's primary SQLite database.",
        "Runs SQLite VACUUM while the collection is not busy. Does not re-embed, "
        "re-extract files or change collection settings. This can take time on a large index.",
        "ragdbman vacuum-collection --collection books",
    ),
    "graph": (
        "Inspect or traverse a source-code syntax graph.",
        "find discovers candidate entities; callers/callees follow calls; dependencies "
        "follows module dependencies; inheritance follows type bases; impact follows "
        "incoming relations. neighbors uses --direction. Preset actions choose their "
        "own direction; --relationships can override their relation set. Except for find, "
        "supply a symbol, entity ID or source ID. Ambiguous symbols return candidates, "
        "not a guessed match. Static analysis is not a runtime call graph.",
        "ragdbman graph --collection code --action callers --symbol parse_config --format llm",
    ),
}

OPTION_HELP = {
    "config": "TOML configuration path (default: ~/.config/ragdbman/config.toml). "
    "After-command value overrides a before-command value.",
    "log_level": "Diagnostic verbosity; overrides RAGDBMAN_LOG, then TOML (default: info). "
    "debug shows stage timings; trace adds connection/SQL metrics.",
    "server_url": "Use this daemon's administrative REST API instead of local storage. "
    "Requires HTTPS or loopback HTTP; uses RAGDBMAN_AUTH_TOKEN when set. No local fallback.",
    "timeout": "Seconds allowed per REST request (default: 600); not a job deadline. Ignored in direct mode.",
    "format": "Output presentation (default: json). table is compact/truncated; "
    "llm, where offered, is readable evidence. Logs and progress go to stderr.",
    "name": "Collection name: 1-128 letters/digits/_/-, starting with a letter or digit.",
    "collection": "Name of the collection to operate on; use list-collections to discover names.",
    "description": "Human-readable collection description; omission stores null (clears an existing description).",
    "source_roots": "Comma-separated allowed directories to register, not scan (default: none). "
    "For a path containing commas, use add-source-root separately.",
    "kind": "general: documents with optional sidecars; source_code: code/graphs without sidecars; "
    "knowledge_cards: whole YAML cards (default: general).",
    "embedding_model": "Ollama embedding model override; defaults to the configured model for this kind. "
    "The model must be available when creating the collection.",
    "chunk_size_tokens": "Target tokens per chunk; defaults to this kind's configuration. "
    "Not supported for Knowledge Cards; atomic blocks can exceed the target.",
    "chunk_overlap_tokens": "Overlap token budget, smaller than chunk size; defaults to this kind's "
    "configuration. Not supported for Knowledge Cards.",
    "confirm": "Explicitly authorize this destructive operation; required for delete/remove/rebuild "
    "and for scans using --prune-missing.",
    "delete_files": "Also delete the collection directory, artifacts and managed originals (default: keep). "
    "Never deletes external source roots.",
    "path": "Allowed filesystem path; interpreted on the daemon host when --server-url is used.",
    "root_id": "Registered root ID from list-source-roots; not the root path.",
    "recursive": "Do not descend into subdirectories (default: recursive).",
    "root": "Allowed directory to scan; interpreted on the daemon host in REST mode.",
    "prune_missing": "Remove derived data for missing sources and mark them missing; requires --confirm. "
    "Does not delete existing originals (default: no pruning).",
    "wait": "Wait for a daemon job to stop, reporting progress on stderr; direct jobs always wait.",
    "source_id": "Source ID from list-sources; not a filename or Knowledge Card ID.",
    "delete_original": "Also delete the original only if it is in managed upload storage "
    "(default: preserve original). External originals cannot be deleted.",
    "job_id": "Job ID returned by scan/rebuild or list-jobs.",
    "watch": "Emit snapshots every two seconds until stopped, including paused/failed states. "
    "JSON snapshots are newline-delimited; does not resume work.",
    "status": "Return only records in this status (default: all statuses).",
    "limit": "Maximum returned records (default: 50).",
    "offset": "Skip this many records for pagination (default: 0).",
    "query": 'Search text; use "" for filter-only structured search.',
    "top_k": "Maximum results, capped at search.max_top_k (default cap: 50). "
    "Default count is search.default_top_k (8), or KC default (3) for cards.",
    "mode": "Retrieval method (default: hybrid): keyword=text, vector=embedding, "
    "hybrid=rank fusion, structured=filters only where supported. MCP calls vector 'semantic'.",
    "collections": "Nonempty comma-separated collection names; duplicates are removed. "
    "Uses only this explicit scope.",
    "query_type": "Card scoring: general uses description; expert weights applicability and "
    "counter-indications (default: expert).",
    "minimum_similarity": "Finite card cutoff from 0 to 1; 0 disables the positive cutoff. "
    "Default: RAGDBMAN_KC_MIN_SIMILARITY or 0.65.",
    "extensions": "Comma-separated source extensions, with or without dots, e.g. .pdf,md (default: no filter).",
    "keywords": "Comma-separated canonical keywords; all must match (default: no keyword filter).",
    "source_ids": "Comma-separated source IDs to include (default: no source-ID filter).",
    "path_prefix": "Literal canonical-path prefix to match (default: no path filter).",
    "numeric": 'Repeatable quoted filter: "field op value", "field between low high", or "field exists". '
    "Operators: equal, not_equal, less_than, less_than_or_equal, greater_than, greater_than_or_equal, "
    "between, exists. All filters are combined; inspect skipped_filters for unknown fields.",
    "include_text": "Omit snippet text from results (default: include text).",
    "include_links": "Omit file/HTTP source links from results (default: include permitted links).",
    "graph_context": "Enable/disable source graph enrichment (default: automatic for source-code "
    "collections when graph support is enabled). Does not build a graph.",
    "extension": "Filter by one source extension, with or without its dot (default: all extensions).",
    "output": "Create a new UTF-8 JSON manifest at this client-local path; refuse overwrite. "
    "Omit to print on stdout.",
    "action": "Graph operation (default: neighbors); find lists candidates without requiring a selector.",
    "symbol": "Exact symbol for traversal; substring for find. Mutually exclusive with --entity-id.",
    "entity_id": "Exact opaque entity ID from graph find/candidates; mutually exclusive with --symbol.",
    "direction": "Edge direction for neighbors only (default: outgoing). Other traversal actions "
    "choose their own direction; find does not traverse.",
    "relationships": "Comma-separated relation filter: contains, imports, calls, inherits, implements, "
    "type_base, references, depends_on. Overrides preset relation sets.",
    "depth": "Maximum graph traversal hops, 1-5 (default: 1); ignored by find.",
    "hf_repo": "Hugging Face repository containing the matching tokenizer.json, e.g. BAAI/bge-m3.",
    "model": "Model cache key to save under (default: ollama.embedding_model in TOML).",
    "revision": "Repository branch, tag or commit to fetch (default: main).",
    "hub_base_url": "Hugging Face-compatible base URL (default: https://huggingface.co).",
}


def complete_help(item, command):
    """Fail at parser construction if a newly added option lacks an explanation."""
    for action in item._actions:
        if action.dest in OPTION_HELP:
            action.help = OPTION_HELP[action.dest]
        if action.required and action.help:
            action.help += " Required."
    overrides = {
        ("list-keywords", "query"): "Case-insensitive substring of a canonical keyword (default: all terms).",
        ("search-multi", "top_k"): "Global result limit across collections; defaults to "
        "search.default_top_k (8), capped at search.max_top_k (50).",
        ("search-knowledge-cards", "query"): "Nonblank query text for Knowledge Card retrieval. Required.",
        ("graph", "source_id"): "Restrict selection to a source ID; by itself selects its file module "
        "for traversal. Use list-sources to find IDs.",
        ("graph", "limit"): "Maximum returned graph edges/candidates, 1-200 (default: 50).",
    }
    for action in item._actions:
        if (command, action.dest) in overrides:
            action.help = overrides[command, action.dest]
        if not action.help:
            raise ValueError(f"Missing CLI help: {command} {action.dest}")


def epilog(command, service):
    notes = (
        "\n\nExecution:\n"
        "  Without --server-url, this command owns local storage; stop the daemon first.\n"
        "  With --server-url, it uses administrative REST and never opens local databases.\n"
        "  Paths refer to the daemon host, except --output, which is client-local.\n"
        "  Use JSON for complete values and machine-readable diagnostics."
        if service
        else ""
    )
    return f"Example:\n  {COMMAND_HELP[command][2]}{notes}\n\nMore details: docs/CLI.md"
