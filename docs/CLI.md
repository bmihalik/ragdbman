# Command-line interface

The CLI uses the canonical operation names in [INTERFACES.md](INTERFACES.md).
It has 28 service operations plus three local setup commands: `init`, `serve`
and `fetch-tokenizer`. There are no compatibility aliases or separate
single-collection/multi-collection/card search commands.

## Help and configuration

```sh
uv run --locked ragdbman --help
uv run --locked ragdbman corpus-query --help
uv run --locked ragdbman collection-create --help
uv run --locked ragdbman scan-start --help
```

Every command explains purpose, behavior, defaults, safety and an example.
`--config` defaults to `~/.config/ragdbman/config.toml`; `--log-level` overrides
`RAGDBMAN_LOG`, then TOML. Both can appear before or after the command, with the
after-command value winning.

## Setup

```sh
uv run --locked ragdbman init
uv run --locked ragdbman fetch-tokenizer --hf-repo BAAI/bge-m3 --model bge-m3:567m
uv run --locked ragdbman serve
```

`init` refuses to overwrite files. Edit `storage.allowed_source_roots` before
indexing. `serve` stays running and uses configured bind/authentication settings.
The tokenizer download is separate from installing Ollama model weights.

## Unified corpus operations

```sh
ragdbman corpus-describe
ragdbman corpus-describe --collections books,code
ragdbman corpus-query --collections books --query "configuration" --mode keyword
ragdbman corpus-query --collections books,code --query "configuration" --format llm
ragdbman corpus-query --collections cards --query "shortest path" --perspective expert --minimum-score 0
ragdbman corpus-graph --collection code --action callers --symbol parse_config --depth 2
```

`--mode` is `keyword`, `semantic`, `hybrid` (default), or `structured`.
`--limit` is a global result count (default 5). Query scope is explicit or uses
configured corpus defaults, never silently all collections. `--perspective`
defaults to general, with expert scoring for Knowledge Cards.

`--format raw` is JSON, `llm` is service-formatted evidence, and `table` is a
compact local rendering. Management supports raw/table. Logs/errors/progress
go to stderr; results go to stdout. Tables retain warnings even with no rows.
Use raw for complete values and machine-readable partial-failure decisions.

```sh
ragdbman corpus-query --collections invoices --query "" --mode structured \
  --numeric "amount greater_than 1000" --numeric "date between 2024-01-01 2024-12-31" \
  --filters '{"source_extensions":["pdf"]}' --format table
```

The `--filters` JSON object uses the same field names as Python/REST/MCP.
`--numeric` appends filters; all filters are combined. Supported numeric
operators are equal, not_equal, less_than, less_than_or_equal, greater_than,
greater_than_or_equal, between and exists. Quote each complete expression.
Knowledge Cards do not accept structured/document filters.

Use `--no-include-text`, `--no-include-links`, or `--no-include-graph-context`
to omit the corresponding evidence. Graph traversal uses `--action`, an exact
`--entity-id` or `--symbol`, optional `--source-id`, `--depth` (1-5), and
`--limit` (1-200). `find` needs no selector. See [SOURCE_GRAPH.md](SOURCE_GRAPH.md).

## Collections and indexing

```sh
ragdbman collection-create --name code --kind source_code --source-roots /data/repo
ragdbman collections-list --format table
ragdbman collection-get --name code
ragdbman collection-config-update --name code --description "Application sources"
ragdbman collection-add-root --collection code --path /data/repo
ragdbman collection-list-roots --collection code
ragdbman scan-start --collection code --root /data/repo
ragdbman collection-list-files --collection code --status failed
ragdbman collection-add-file --collection code --path /data/repo/main.py
ragdbman collection-get-file --collection code --source-id SOURCE_ID
```

Collection creation probes the model but does not scan. Omitted description
on config-update clears it; model, kind and chunk strategy stay immutable.
Root registration does not scan. Use `--no-recursive` for shallow scans/roots.
Root/file paths refer to the executing server's filesystem.

Uploads use `collection-upload-file --collection NAME --filename NAME
--content-base64 BASE64`. This creates a new managed file, unlike indexing an
existing file with collection-add-file.

```sh
ragdbman scan-jobs-list --collection code
ragdbman scan-job-get --collection code --job-id JOB_ID --watch --server-url http://127.0.0.1:8765
ragdbman scan-job-cancel --job-id JOB_ID --server-url http://127.0.0.1:8765
ragdbman scan-job-resume --collection code --job-id JOB_ID
```

Direct scan/rebuild/resume waits until stopped, retaining Engine ownership.
Daemon-mode calls return immediately unless `--wait` is set. Job watching emits
newline-delimited raw JSON snapshots every two seconds, including one final
stopped record. Watching does not resume a paused job.

## Local ownership and daemon access

Without `--server-url`, service commands open local storage and hold OS advisory
locks before startup recovery. Stop a daemon using that storage first. Lock
files are not permission to bypass a running owner; never delete them to force
access. Direct calls rely on OS access, not HTTP tokens.

With `--server-url`, commands send the same flat JSON contract to
`POST /api/<command>`, use `RAGDBMAN_AUTH_TOKEN`, and never fall back to local
storage. Query-only tokens do not authorize administrative REST. HTTPS is
required except for loopback HTTP; embedded URL credentials, query strings,
fragments, redirects and environment proxies are disallowed.

`--timeout` defaults to 600 seconds per request, not a job deadline. The
daemon's configuration is authoritative; local `--config` does not change it.
`--output` for manifest export writes a new client-local JSON file and refuses
overwrite; source paths otherwise refer to the daemon host.

## Maintenance and confirmations

```sh
ragdbman collections-registry-repair
ragdbman collection-list-keywords --collection code
ragdbman collection-list-metadata-fields --collection code
ragdbman collection-export-manifest --collection code --output code-manifest.json
ragdbman collection-vacuum --collection code
ragdbman collection-remove-root --collection code --root-id ROOT_ID --confirm
ragdbman collection-remove-file --collection code --source-id SOURCE_ID --confirm
ragdbman scan-start --collection code --root /data/repo --prune-missing --confirm
ragdbman collection-rebuild --collection code --confirm
ragdbman collection-delete --name code --confirm
```

Root removal preserves indexed files. File removal preserves originals unless
`--delete-original-managed-file` selects an original within managed storage.
Collection deletion preserves managed files unless `--delete-files` is supplied;
external originals are never deleted. Rebuild clears first, then reindexes:
it is not a transactional index swap. A manifest is not a full backup.

## Signals and exit statuses

Ctrl+C/SIGTERM stops direct owned work and requests cleanup; interrupted jobs
are paused for explicit resume. Remote Ctrl+C stops the client, not accepted
daemon work. Use scan-job-cancel to cancel that work.

| Exit | Meaning |
| --- | --- |
| 0 | Request succeeded; inspect health/query warnings |
| 1 | Application, validation, ownership or transport failure |
| 2 | Argument parsing failure |
| 3 | Returned job stopped unsuccessfully, or raw/table query had no successful collection |
| 130 | Ctrl+C |
| 143 | Direct-mode SIGTERM |

Partial query success returns 0 with warnings. LLM output reports failures in
text; use raw for programmatic status decisions. Signal cleanup limits and
external-process boundaries are in [RUNTIME.md](RUNTIME.md).
