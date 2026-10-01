# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Generate the canonical interface reference; --check detects documentation drift."""

import argparse
import json
from pathlib import Path

from ragdbman.operations import OPERATIONS, QUERY_OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


def render():
    lines = [
        "# Canonical interface reference",
        "",
        "Generated from `ragdbman.operations.OPERATIONS`. Run",
        "`uv run python tools/generate_interface_reference.py` to refresh, or add",
        "`--check` to verify. This catalog is shared by CLI, REST and MCP dispatch.",
        "",
        "CLI names and REST paths use hyphens. Python Engine methods and MCP tools",
        "use underscores. All REST operations use POST with a JSON object body,",
        "including read-only queries; HTTP method alone does not describe side effects.",
        "MCP arguments are the same flat object, never a nested `request` wrapper.",
        "",
        "The query MCP profile exposes only the three corpus operations. The optional",
        "admin profile exposes all 28 operations. Python/REST calls are administrative;",
        "query MCP additionally enforces the configured collection allowlist.",
        "",
        "## Operation names",
        "",
        "| CLI command | Python method / MCP tool | REST endpoint | Query MCP |",
        "| --- | --- | --- | --- |",
    ]
    for name in OPERATIONS:
        slug = name.replace("_", "-")
        lines.append(
            f"| `{slug}` | `{name}` | `/api/{slug}` | {'yes' if name in QUERY_OPERATIONS else 'no'} |"
        )
    lines += [
        "",
        "The CLI also has three local setup commands: `init`, `serve`,",
        "and `fetch-tokenizer`. They are process/setup actions, not remote tools.",
        "",
        "## Request fields and behavior",
        "",
        "All fields reject unknown keys. `collection` selects an existing collection;",
        "`name` is used by collection create/get/config-update/delete. `collections`",
        "is the list used by corpus discovery/query. File selectors retain `source_id`,",
        "the stable provenance identifier, and are not filenames or Knowledge Card IDs.",
        "",
        "Retrieval `format` is raw JSON by default in Python, REST and CLI. MCP query",
        "and graph tools default to `llm`. CLI additionally supports `table` as a local",
        "display mode, not a server-side format. Arrays use comma-separated CLI values;",
        "`filters` is a JSON object. CLI option names replace underscores with hyphens.",
        "",
    ]
    for name, spec in OPERATIONS.items():
        lines += [
            "### " + name.replace("_", "-"),
            "",
            spec.description,
            "",
            "| Field | Required | Default |",
            "| --- | --- | --- |",
        ]
        for key, field in spec.model.model_fields.items():
            default = (
                "required"
                if field.is_required()
                else json.dumps(
                    field.default_factory() if field.default_factory else field.default,
                    ensure_ascii=False,
                    default=lambda value: value.model_dump(),
                )
            )
            lines.append(f"| `{key}` | {'yes' if field.is_required() else 'no'} | `{default}` |")
        if not spec.model.model_fields:
            lines.append("| none | no | `{}` request body |")
        lines += [
            "",
            "Hints: "
            + ", ".join(
                f"`{key}={str(value).lower()}`"
                for key, value in (
                    ("readOnlyHint", spec.readonly),
                    ("destructiveHint", spec.destructive),
                    ("idempotentHint", spec.idempotent),
                    ("openWorldHint", False),
                )
            )
            + ".",
            "",
        ]
    lines += [
        "## Envelopes and errors",
        "",
        "Python and REST return the operation's native dictionary/list, or text for",
        "LLM retrieval. MCP returns text plus structuredContent in raw mode; list",
        'results are wrapped as `{"result": [...]}` because MCP structuredContent',
        "requires an object. Dictionary results are not double-wrapped. LLM output",
        "is one text block without duplicate structuredContent.",
        "",
        "Corpus queries report per-collection failures in `warnings` and successful",
        "collections in `collections_searched`. A successful HTTP response can contain",
        "zero successful collections; inspect these fields. Validation/authentication",
        "errors fail the request. CLI raw/table queries return exit 3 if every",
        "collection fails; readable LLM mode retains failures in text.",
        "",
        "Explicit confirmations are required for collection deletion, file removal,",
        "root removal, rebuild, and scans with missing-file pruning. They apply at",
        "the Engine and shared dispatch boundaries, not only in a web dialog.",
        "",
        "No compatibility aliases, old search endpoints or action-dispatch MCP",
        "management tools are registered. Existing SQLite data does not need rebuilding.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--check", action="store_true")
    check = args.parse_args().check
    dest = ROOT / "docs/INTERFACES.md"
    content = render()
    if check:
        if not dest.exists() or dest.read_text(encoding="utf-8") != content:
            raise SystemExit("docs/INTERFACES.md is stale; regenerate it")
        print("Canonical interface reference is current.")
    else:
        dest.write_text(content, encoding="utf-8")
        print(dest)
