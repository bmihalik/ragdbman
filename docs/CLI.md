# Command-line interface

ragdbman 0.5.4 provides 31 commands: four infrastructure commands, 25
engine-service commands from the CLI extension specification, plus `graph` and
`search-knowledge-cards` for the current engine's specialized retrieval services.
Service command names are engine method names with underscores replaced by
hyphens. MCP retains its separate compact `corpus_` interface; it does not expose
one tool per engine method.

## Configuration and execution

```sh
uv run ragdbman --help
uv run ragdbman search --help
uv run ragdbman --config /path/config.toml list-collections
uv run ragdbman list-collections --config /path/config.toml --log-level debug
```

The top-level help lists every command with a one-line purpose. Each command's
help is designed to stand alone: it explains what the command does, direct versus
daemon behavior, option meanings/defaults, destructive effects, where to obtain
IDs and one parseable example. Optional syntax in the `usage:` line is only a
summary; the `options:` section is authoritative.

Examples:

```sh
uv run ragdbman create-collection --help
uv run ragdbman start-scan --help
uv run ragdbman graph --help
```

Every subcommand accepts `--config` and `--log-level`; these may also precede
the command. If specified in both positions, the subcommand value wins.
The default config is `~/.config/ragdbman/config.toml`. Log levels are
`trace`, `debug`, `verbose`, `info`, `warning`/`warn`, `error`, `critical`.
CLI log level overrides `RAGDBMAN_LOG`, then TOML.

Service commands default to JSON on stdout, with logs/progress/errors on stderr.
`--format table` is available on all service commands; list/search commands
have selected columns, while other records use field/value rows. Cells are
escaped and capped at 80 characters: use JSON for complete values.
Empty tables show `(no rows)`. Search tables retain collection/filter diagnostics.
If a multi-search has no result rows, its `collections_failed` and
`skipped_filters` diagnostics are still printed after `(no rows)`.
Search, search-multi and graph also accept `--format llm`, using the 0.5.1
readable presentation; CLI `json` corresponds to the Python API's `raw`.

### Direct local operation

Without `--server-url`, the CLI creates an engine, invokes its method, and
closes it on the same event loop. The direct CLI needs filesystem access and
does not require the daemon's HTTP token, even when the server configuration
uses authentication.

`start-scan`, `resume-job` and `rebuild-collection` run in the foreground until
the job stops. They do not return a queued job and immediately close its engine.
Progress goes to stderr; stdout contains one final job record, whose identifier
is `id`. Keep this process running for the duration of the scan.

`serve`, `registry-repair` and direct service commands hold OS advisory locks
for the data directory and registry path before constructing the engine.
Conflicting commands fail with `DATA_DIRECTORY_BUSY` instead of performing
startup recovery against another process's running jobs. Lock files remain on
disk; their presence does not mean the lock is held, and they should not be
deleted to bypass ownership. The OS releases the lock when the owner exits.
This is not a distributed/multi-host worker lease; network storage behavior
and Windows locking have not been certified by the Linux verification matrix.
The guard protects only cooperating owners. Stop any pre-existing daemon or
embedded engine that does not hold these locks before direct operation, or use
`--server-url` to leave its storage under that owner's control.

### Controlling a daemon

All service commands accept `--server-url URL` and `--timeout SECONDS` (600
seconds per HTTP request by default). In this mode, the CLI uses administrative
REST and never opens local databases or creates an engine. It never falls back
to local operation after a connection/authentication failure.

```sh
# Use the administrator token already configured for the daemon.
# Load RAGDBMAN_AUTH_TOKEN securely into this shell's environment; no CLI token flag.
uv run ragdbman list-collections --server-url http://127.0.0.1:8765
uv run ragdbman start-scan --collection code --root /server/projects/app \
  --server-url http://127.0.0.1:8765
uv run ragdbman get-job --collection code --job-id JOB_ID --watch \
  --server-url http://127.0.0.1:8765
uv run ragdbman cancel-job --job-id JOB_ID --server-url http://127.0.0.1:8765
```

The CLI sends `RAGDBMAN_AUTH_TOKEN` as a Bearer credential. The query-only token
cannot authorize REST administration. Unauthenticated loopback REST works only
when the daemon's configured security policy permits it. Remote connections
require HTTPS; HTTP is accepted only for loopback IPs or `localhost`. Embedded
credentials, query strings and fragments in the server URL are rejected.
Redirects and environment HTTP proxies are disabled to avoid unintended token
forwarding. Existing reverse-proxy deployment/security rules still apply.

Filesystem paths in requests refer to the server filesystem, not the CLI
machine. `--output` is the exception: it writes the manifest on the client.
The daemon owns the active configuration in this mode; local `--config` does
not reconfigure it. Request timeout is not a job deadline.

Daemon-mode scan/resume/rebuild return the initial job record immediately.
Add `--wait` to wait for a stopped record; local versions always wait whether
or not this flag is specified. `get-job --watch` prints newline-delimited JSON
snapshots every two seconds (or table snapshots), including the final stopped
record exactly once. `paused` counts as stopped; a watcher does not resume jobs.
Use daemon mode to watch/cancel from another terminal while a daemon owns work.
A second direct CLI cannot inspect a foreground local owner's locked storage.

### Interruption and exit status

Ctrl+C/SIGTERM in direct mode requests shutdown, cancels active owned work and
waits for cleanup. Interrupted foreground jobs are paused for explicit resume;
committed sources remain intact. The configured `server.shutdown_timeout_seconds`
also bounds foreground CLI cleanup; a repeated signal or deadline forces process
exit after terminating owned converters. Remote-mode Ctrl+C stops the client,
not an already accepted daemon job; use `cancel-job` to cancel that job.

| Exit | Meaning |
| --- | --- |
| 0 | Command returned successfully; inspect health/partial-search diagnostics |
| 1 | Application, validation, I/O, ownership or transport failure |
| 2 | argparse usage/argument error |
| 3 | Returned job is paused/failed/cancelled/completed-with-errors, or JSON/table multi-search has no successful collection |
| 130 | Foreground/client Ctrl+C |
| 143 | Direct-mode SIGTERM |

JSON/table multi-search with at least one successful collection returns 0 even
when others fail, with `collections_failed` preserved. Readable LLM responses
report failures in their text; use JSON for machine decisions about partial or
all-collection failures. Structured health results can report Ollama unavailable
while returning 0: existing keyword retrieval and inspection may still work.
Usage and transport failures never print a successful-result object to stdout.
Application errors are JSON objects on stderr, possibly alongside diagnostic logs.

## Command reference

All service commands below accept `--config`, `--log-level`, `--server-url`,
`--timeout`, and `--format json|table`; options shown as optional have defaults.

### Infrastructure

```text
serve
init
registry-repair
fetch-tokenizer --hf-repo REPO [--model MODEL] [--revision main]
                [--hub-base-url https://huggingface.co]
```

These retain their existing human-readable setup output and config/log flags,
not REST/table flags. `init` refuses to overwrite an existing config.
`registry-repair` opens local storage and must run while the daemon is stopped.

### Collections and health

```text
health-status
list-collections
get-collection --name NAME
create-collection --name NAME [--description TEXT] [--source-roots PATH1,PATH2]
                  [--kind general|source_code|knowledge_cards]
                  [--embedding-model MODEL] [--chunk-size-tokens N]
                  [--chunk-overlap-tokens N]
update-collection-config --name NAME [--description TEXT]
delete-collection --name NAME --confirm [--delete-files]
```

Creation probes the embedding model first. Knowledge Cards accept model overrides
but reject chunk overrides. Updating changes only the description. Rebuild does
not change the recorded model/chunk settings; create a new collection for those
changes. `--delete-files` additionally removes the collection directory and its
managed originals; external source roots are not deleted.

`health-status` in direct mode checks its own engine, vector extension and
Ollama, not whether an independent daemon exists. Use `--server-url` for that
daemon's health and live job count.

### Roots, sources and indexing

```text
list-source-roots --collection NAME
add-source-root --collection NAME --path PATH [--no-recursive]
remove-source-root --collection NAME --root-id ID
start-scan --collection NAME --root PATH [--no-recursive]
           [--prune-missing --confirm] [--wait]
add-file --collection NAME --path PATH
remove-source --collection NAME --source-id ID --confirm [--delete-original]
list-sources --collection NAME [--extension .pdf] [--path-prefix PATH]
             [--status STATUS] [--limit 50] [--offset 0]
get-source --collection NAME --source-id ID
```

Roots and source paths obey the engine allowlist. `remove-source-root` unregisters
only the root; it does not delete source records or originals. Missing-file
pruning removes derived index data and marks sources missing, and requires
explicit CLI confirmation. `--delete-original` is limited to managed originals.
General/source/KC collection semantics, including code sidecar suppression, are
unchanged.

`add-file` returns the engine's actual classification: `new`, `changed`,
`previously_failed`, `unchanged`, `unsupported`, or card-specific `not_a_card`.
There is no synthetic `updated` alias. Source status choices are `discovered`,
`extracting`, `embedding`, `indexed`, `failed`, `unsupported`, `queued`, `missing`.
Comma lists reject empty items; paths containing literal commas can instead be
registered individually with `add-source-root --path`.

### Jobs

```text
get-job --collection NAME --job-id ID [--watch]
list-jobs --collection NAME [--status STATUS] [--limit 50]
cancel-job --job-id ID
resume-job --collection NAME --job-id ID [--wait]
```

Job status choices are `queued`, `running`, `paused`, `completed`,
`completed_with_errors`, `failed`, `cancelled`. Resume supports paused, failed,
cancelled and completed-with-errors scan/rebuild jobs. Cancel does not rewrite
finished completed/failed records, and repeating cancellation of an already
cancelled job is idempotent.

### Search and graph traversal

```text
search --collection NAME --query TEXT [--mode vector|keyword|hybrid|structured]
       [--top-k N] [--extensions .pdf,.md] [--keywords term1,term2]
       [--path-prefix PATH] [--source-ids ID1,ID2] [--numeric "field op value"]
       [--no-text] [--no-links] [--graph-context|--no-graph-context]
       [--format json|table|llm]

search-multi --collections A,B,C --query TEXT
             [same search options and filters as search]

search-knowledge-cards --collection NAME --query TEXT
                       [--mode keyword|vector|hybrid] [--query-type general|expert]
                       [--top-k N] [--minimum-similarity NUMBER]

graph --collection NAME [--action find|neighbors|callers|callees|dependencies|inheritance|impact]
      [--symbol NAME|--entity-id ID] [--source-id ID]
      [--direction outgoing|incoming|both] [--relationships calls,imports,...]
      [--depth 1] [--limit 50] [--format json|table|llm]
```

Search defaults to hybrid; corpus MCP's `semantic` spelling remains `vector`
at the engine/CLI layer. Graph defaults to neighbors and requires a selector
except for find; depth is 1–5 and limit 1–200. Graph queries are source-code-only.
Knowledge Card search retains its ranked match list, including full card data;
use normal `search --format llm` for readable card results.

`--numeric` is repeatable. Valid operators are `equal`, `not_equal`,
`less_than`, `less_than_or_equal`, `greater_than`, `greater_than_or_equal`,
`between`, and `exists`. Ordinary operators take one value; between takes two;
exists takes none. Quote the entire filter so the shell passes one argument.

```sh
uv run ragdbman search --collection invoices --query "" --mode structured \
  --numeric "amount greater_than 1000" \
  --numeric "date between 2024-01-01 2024-12-31" \
  --numeric "amount exists" --extensions .pdf --format table
```

Dates/numbers remain strings until interpreted according to the metadata field.
Unknown fields appear in `skipped_filters`; inspect those diagnostics rather
than assuming every filter was applied. Top-k still bounds structured results.

### Inspection and maintenance

```text
list-keywords --collection NAME [--query TERM] [--limit 50] [--offset 0]
list-metadata-fields --collection NAME
export-collection-manifest --collection NAME [--output FILE]
rebuild-collection --collection NAME --confirm [--wait]
vacuum-collection --collection NAME
```

Manifest files are always UTF-8 JSON, independent of table display selection,
and are created exclusively: existing files are never overwritten. Without
`--output`, the response is written to stdout. A manifest is not a backup of
all index/vector/source bytes. Rebuild retains confirmed clear-then-index
semantics and current collection settings. Vacuum requires an idle collection.

For embedding in Python, see [PYTHON_API_GUIDE.md](PYTHON_API_GUIDE.md).
