# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Explicit CLI contracts, local engine calls and optional administrative REST transport."""

import argparse
import asyncio
import inspect
import ipaddress
import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from .errors import RagError, require_confirmation
from .graph.query import GraphRequest
from .models import (
    CreateCollection,
    KnowledgeCardSearchRequest,
    MultiSearchRequest,
    NumericFilter,
    SearchFilters,
    SearchRequest,
)

COMMANDS = (
    "health-status",
    "list-collections",
    "get-collection",
    "create-collection",
    "update-collection-config",
    "delete-collection",
    "list-source-roots",
    "add-source-root",
    "remove-source-root",
    "start-scan",
    "add-file",
    "remove-source",
    "get-job",
    "list-jobs",
    "cancel-job",
    "resume-job",
    "search",
    "search-multi",
    "list-sources",
    "get-source",
    "list-keywords",
    "list-metadata-fields",
    "export-collection-manifest",
    "rebuild-collection",
    "vacuum-collection",
    "graph",
    "search-knowledge-cards",
)
JOBS = {"start-scan", "resume-job", "rebuild-collection"}
JOB_STATUSES = ("queued", "running", "paused", "completed", "completed_with_errors", "failed", "cancelled")
SOURCE_STATUSES = (
    "discovered",
    "extracting",
    "embedding",
    "indexed",
    "failed",
    "unsupported",
    "queued",
    "missing",
)


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def nonnegative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return value


def name(text):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", text):
        raise argparse.ArgumentTypeError("invalid collection name")
    return text


def nonempty(text):
    if not text.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def csv_list(text):
    values = [s.strip() for s in text.split(",")]
    if not all(values):
        raise argparse.ArgumentTypeError("expected a nonempty comma-separated list")
    return list(dict.fromkeys(values))


def collection_list(text):
    return [name(value) for value in csv_list(text)]


def numeric(text):
    try:
        values = shlex.split(text)
        if len(values) < 2:
            raise ValueError("expected field op [value]")
        field, op, *operands = values
        count = 0 if op == "exists" else 2 if op == "between" else 1
        if len(operands) != count:
            raise ValueError(f"{op} requires {count} operand(s)")
        data = {"field": field, "op": op}
        if op == "between":
            data.update({"from": operands[0], "to": operands[1]})
        elif op != "exists":
            data["value"] = operands[0]
        return NumericFilter(**data)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid numeric filter: {exc}") from exc


def arguments(item, command):
    item.add_argument("--server-url", type=nonempty, help="Explicit daemon URL; never opens local databases")
    item.add_argument(
        "--timeout", type=positive, default=600, help="REST request timeout in seconds (default 600)"
    )
    formats = ["json", "table"]
    if command in {"search", "search-multi", "graph"}:
        formats.append("llm")
    item.add_argument("--format", choices=formats, default="json")
    if command in {"get-collection", "create-collection", "update-collection-config", "delete-collection"}:
        item.add_argument("--name", type=name, required=True)
    elif command not in {"health-status", "list-collections", "cancel-job", "search-multi"}:
        item.add_argument("--collection", type=name, required=True)
    if command == "create-collection":
        item.add_argument("--description")
        item.add_argument("--source-roots", type=csv_list, default=[])
        item.add_argument("--kind", choices=["general", "source_code", "knowledge_cards"], default="general")
        item.add_argument("--embedding-model")
        item.add_argument("--chunk-size-tokens", type=positive)
        item.add_argument("--chunk-overlap-tokens", type=nonnegative)
    if command == "update-collection-config":
        item.add_argument("--description")
    if command in {"delete-collection", "remove-source", "rebuild-collection", "start-scan"}:
        item.add_argument("--confirm", action="store_true")
    if command == "delete-collection":
        item.add_argument("--delete-files", action="store_true")
    if command in {"add-source-root", "add-file"}:
        item.add_argument("--path", type=nonempty, required=True)
    if command == "remove-source-root":
        item.add_argument("--root-id", type=nonempty, required=True)
    if command in {"add-source-root", "start-scan"}:
        item.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)
    if command == "start-scan":
        item.add_argument("--root", type=nonempty, required=True)
        item.add_argument("--prune-missing", action="store_true")
    if command in JOBS:
        item.add_argument("--wait", action="store_true", help="Wait for a daemon job; local jobs always wait")
    if command in {"remove-source", "get-source"}:
        item.add_argument("--source-id", type=nonempty, required=True)
    if command == "remove-source":
        item.add_argument("--delete-original", action="store_true")
    if command in {"get-job", "cancel-job", "resume-job"}:
        item.add_argument("--job-id", type=nonempty, required=True)
    if command == "get-job":
        item.add_argument(
            "--watch", action="store_true", help="Emit snapshots every two seconds until stopped"
        )
    if command in {"list-jobs", "list-sources"}:
        item.add_argument("--status", choices=JOB_STATUSES if command == "list-jobs" else SOURCE_STATUSES)
    if command in {"list-jobs", "list-sources", "list-keywords"}:
        item.add_argument("--limit", type=positive, default=50)
    if command in {"list-sources", "list-keywords"}:
        item.add_argument("--offset", type=nonnegative, default=0)
    if command in {"search", "search-multi", "search-knowledge-cards"}:
        item.add_argument("--query", required=True)
        item.add_argument("--top-k", type=positive)
        item.add_argument(
            "--mode",
            choices=["keyword", "vector", "hybrid"]
            + ([] if command == "search-knowledge-cards" else ["structured"]),
            default="hybrid",
        )
    if command == "search-multi":
        item.add_argument("--collections", type=collection_list, required=True)
    if command == "search-knowledge-cards":
        item.add_argument("--query-type", choices=["general", "expert"], default="expert")
        item.add_argument("--minimum-similarity", type=float)
    if command in {"search", "search-multi"}:
        item.add_argument("--extensions", type=csv_list, default=[])
        item.add_argument("--keywords", type=csv_list, default=[])
        item.add_argument("--source-ids", type=csv_list, default=[])
        item.add_argument("--path-prefix")
        item.add_argument("--numeric", type=numeric, action="append", default=[])
        item.add_argument("--no-text", dest="include_text", action="store_false", default=True)
        item.add_argument("--no-links", dest="include_links", action="store_false", default=True)
        item.add_argument("--graph-context", action=argparse.BooleanOptionalAction, default=None)
    if command == "list-sources":
        item.add_argument("--extension")
        item.add_argument("--path-prefix")
    if command == "list-keywords":
        item.add_argument("--query")
    if command == "export-collection-manifest":
        item.add_argument(
            "--output", type=nonempty, help="Create a new UTF-8 JSON file; existing files are not overwritten"
        )
    if command == "graph":
        item.add_argument(
            "--action",
            choices=["find", "neighbors", "callers", "callees", "dependencies", "inheritance", "impact"],
            default="neighbors",
        )
        selector = item.add_mutually_exclusive_group()
        selector.add_argument("--symbol")
        selector.add_argument("--entity-id")
        item.add_argument("--source-id")
        item.add_argument("--direction", choices=["outgoing", "incoming", "both"], default="outgoing")
        item.add_argument("--relationships", type=csv_list)
        item.add_argument("--depth", type=positive, default=1)
        item.add_argument("--limit", type=positive, default=50)


def contract(args):
    """Validated, explicit method/kwargs mapping; no arbitrary method execution."""
    command = args.command
    a = vars(args)
    if command in {"delete-collection", "remove-source", "rebuild-collection"} or (
        command == "start-scan" and args.prune_missing
    ):
        require_confirmation(args.confirm)
    keys = {
        "health-status": [],
        "list-collections": [],
        "get-collection": ["name"],
        "create-collection": [
            "name",
            "description",
            "source_roots",
            "kind",
            "embedding_model",
            "chunk_size_tokens",
            "chunk_overlap_tokens",
        ],
        "update-collection-config": ["name", "description"],
        "delete-collection": ["name", "confirm", "delete_files"],
        "list-source-roots": ["collection"],
        "add-source-root": ["collection", "path", "recursive"],
        "remove-source-root": ["collection", "root_id"],
        "start-scan": ["collection", "root", "recursive", "prune_missing"],
        "add-file": ["collection", "path"],
        "remove-source": ["collection", "source_id", "confirm"],
        "get-job": ["collection", "job_id"],
        "list-jobs": ["collection", "status", "limit"],
        "cancel-job": ["job_id"],
        "resume-job": ["collection", "job_id"],
        "list-sources": ["collection", "extension", "path_prefix", "status", "limit", "offset"],
        "get-source": ["collection", "source_id"],
        "list-keywords": ["collection", "query", "limit", "offset"],
        "list-metadata-fields": ["collection"],
        "export-collection-manifest": ["collection"],
        "rebuild-collection": ["collection", "confirm"],
        "vacuum-collection": ["collection"],
        "graph": [
            "collection",
            "action",
            "symbol",
            "entity_id",
            "source_id",
            "direction",
            "relationships",
            "depth",
            "limit",
        ],
        "search-knowledge-cards": [
            "collection",
            "query",
            "query_type",
            "mode",
            "top_k",
            "minimum_similarity",
        ],
    }
    if command in {"search", "search-multi"}:
        data = {k: a[k] for k in ("query", "mode", "top_k", "include_text", "include_links")}
        data.update(
            format="llm" if args.format == "llm" else "raw",
            include_graph_context=args.graph_context,
            filters=SearchFilters(
                source_extensions=args.extensions,
                keywords=args.keywords,
                source_ids=args.source_ids,
                path_prefix=args.path_prefix,
                numeric=args.numeric,
            ),
        )
        if command == "search":
            request = SearchRequest(collection=args.collection, **data)
        else:
            for value in args.collections:
                name(value)
            request = MultiSearchRequest(collections=args.collections, **data)
        return command.replace("-", "_"), {"request": request}
    data = {k: a[k] for k in keys[command]}
    if command == "create-collection":
        return "create_collection", {"request": CreateCollection(**data)}
    if command == "graph":
        data["format"] = "llm" if args.format == "llm" else "raw"
        return "graph", {"request": GraphRequest(**data)}
    if command == "search-knowledge-cards":
        return "search_knowledge_cards", {"request": KnowledgeCardSearchRequest(**data)}
    if command == "remove-source":
        data["delete_original_managed_file"] = args.delete_original
    return command.replace("-", "_"), data


def clean(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[1:-1] if isinstance(value, str) else text


def table(command, payload):
    rows = (
        payload
        if isinstance(payload, list)
        else payload.get("results")
        if isinstance(payload, dict)
        else None
    )
    if rows is None:
        rows = (
            [{"field": k, "value": v} for k, v in payload.items()]
            if isinstance(payload, dict)
            else [{"value": payload}]
        )
    if not rows:
        return "(no rows)"
    columns = {
        "list-collections": ["name", "kind", "counts", "embedding", "chunking"],
        "list-sources": ["id", "original_filename", "extension", "status"],
        "list-jobs": ["id", "kind", "status", "progress"],
        "list-keywords": ["canonical_form", "chunk_frequency"],
        "search": ["score", "source_filename", "citation_label", "text"],
        "search-multi": ["collection_id", "score", "source_filename", "citation_label", "text"],
    }.get(command, list(rows[0]))
    data = [[clean(row.get(k, "")) for k in columns] for row in rows]
    widths = [min(80, max(len(k), *(len(row[i]) for row in data))) for i, k in enumerate(columns)]

    def line(values):
        return " | ".join(
            (v if len(v) <= w else v[: w - 3] + "...").ljust(w) for v, w in zip(values, widths, strict=True)
        )

    output = [line(columns), "-+-".join("-" * w for w in widths), *[line(row) for row in data]]
    if isinstance(payload, dict):
        for key in ("collections_failed", "skipped_filters"):
            if payload.get(key):
                output.append(key + ": " + clean(payload[key]))
    return "\n".join(output)


def emit(args, payload, snapshot=False):
    if isinstance(payload, str):
        output = payload
    elif args.format == "table":
        output = table(args.command, payload)
    else:
        output = json.dumps(payload, ensure_ascii=False, indent=None if snapshot else 2, allow_nan=False)
    if getattr(args, "output", None):
        with Path(args.output).expanduser().open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    else:
        print(output, flush=True)


def exit_status(args, payload):
    if isinstance(payload, dict):
        if args.command in JOBS | {"get-job"} and payload.get("status") in {
            "failed",
            "completed_with_errors",
            "cancelled",
            "paused",
        }:
            return 3
        if (
            args.command == "search-multi"
            and payload.get("collections_failed")
            and not payload.get("collections_searched")
        ):
            return 3
    return 0


async def wait_job(args, getter, job, task=None, watch=False):
    while job["status"] in {"queued", "running"}:
        if watch:
            emit(args, job, snapshot=True)
        else:
            print(f"Job {job['id']}: {job['status']} {clean(job.get('progress', {}))}", file=sys.stderr)
        if task is not None:
            await asyncio.wait({task}, timeout=2)
        else:
            await asyncio.sleep(2)
        job = await getter(job["id"])
        if task is not None and task.done() and job["status"] in {"queued", "running"}:
            raise RagError("INTERNAL", "Job task exited without a stopped job status")
    return job


async def local(engine, args, method, kwargs):
    result = getattr(engine, method)(**kwargs)
    if inspect.isawaitable(result):
        result = await result

    async def getter(job_id):
        return engine.get_job(args.collection, job_id)

    if args.command in JOBS:
        result = await wait_job(args, getter, result, engine.tasks.get(result["id"]))
    elif args.command == "get-job" and args.watch:
        result = await wait_job(args, getter, result, watch=True)
    return result


def endpoint(args, kwargs):
    c = "/api/collections/" + quote(getattr(args, "collection", None) or getattr(args, "name", ""), safe="")
    command = args.command
    body = {
        k: v
        for k, v in kwargs.items()
        if k not in {"collection", "name", "root_id", "source_id", "job_id"} and v is not None
    }
    params = {}
    routes = {
        "health-status": ("GET", "/api/health"),
        "list-collections": ("GET", "/api/collections"),
        "get-collection": ("GET", c),
        "create-collection": ("POST", "/api/collections"),
        "update-collection-config": ("PATCH", c),
        "delete-collection": ("DELETE", c),
        "list-source-roots": ("GET", c + "/roots"),
        "add-source-root": ("POST", c + "/roots"),
        "remove-source-root": ("DELETE", c + "/roots/" + quote(getattr(args, "root_id", ""), safe="")),
        "start-scan": ("POST", c + "/scan"),
        "add-file": ("POST", c + "/add_file"),
        "remove-source": ("DELETE", c + "/sources/" + quote(getattr(args, "source_id", "") or "", safe="")),
        "get-source": ("GET", c + "/sources/" + quote(getattr(args, "source_id", "") or "", safe="")),
        "list-sources": ("GET", c + "/sources"),
        "list-jobs": ("GET", c + "/jobs"),
        "get-job": ("GET", c + "/jobs/" + quote(getattr(args, "job_id", ""), safe="")),
        "resume-job": ("POST", c + "/jobs/" + quote(getattr(args, "job_id", ""), safe="") + "/resume"),
        "cancel-job": ("POST", "/api/jobs/" + quote(getattr(args, "job_id", ""), safe="") + "/cancel"),
        "list-keywords": ("GET", c + "/keywords"),
        "list-metadata-fields": ("GET", c + "/metadata_fields"),
        "export-collection-manifest": ("GET", c + "/manifest"),
        "rebuild-collection": ("POST", c + "/rebuild"),
        "vacuum-collection": ("POST", c + "/vacuum"),
        "search": ("POST", "/api/search"),
        "search-multi": ("POST", "/api/search/multi"),
        "graph": ("POST", "/api/corpus/graph"),
        "search-knowledge-cards": ("POST", "/api/knowledge-cards/search"),
    }
    verb, path = routes[command]
    if "request" in kwargs:
        body = kwargs["request"].model_dump(by_alias=True)
    if verb in {"GET", "DELETE"}:
        params, body = body, None
    return verb, path, params, body


async def remote(args, kwargs):
    url = urlsplit(args.server_url)
    try:
        loopback = url.hostname == "localhost" or ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = False
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or (url.scheme == "http" and not loopback)
    ):
        raise RagError(
            "CONFIG_INVALID",
            "--server-url requires HTTPS or loopback HTTP, without embedded credentials/query/fragment",
        )
    token = os.environ.get("RAGDBMAN_AUTH_TOKEN")
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with httpx.AsyncClient(
        headers=headers, timeout=args.timeout, follow_redirects=False, trust_env=False
    ) as client:

        async def request(verb, path, params=None, body=None):
            try:
                response = await client.request(
                    verb, args.server_url.rstrip("/") + path, params=params, json=body
                )
            except httpx.HTTPError as exc:
                raise RagError(
                    "DAEMON_UNAVAILABLE", "Daemon request failed; no local fallback was attempted"
                ) from exc
            if not response.is_success:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                raise RagError(
                    payload.get("code", "REMOTE_ERROR"),
                    payload.get("message", f"Daemon returned HTTP {response.status_code}"),
                )
            if response.headers.get("content-type", "").startswith("text/plain"):
                return response.text
            return response.json()

        result = await request(*endpoint(args, kwargs))

        async def getter(job_id):
            return await request(
                "GET",
                "/api/collections/" + quote(args.collection, safe="") + "/jobs/" + quote(job_id, safe=""),
            )

        if args.command in JOBS and args.wait:
            result = await wait_job(args, getter, result)
        elif args.command == "get-job" and args.watch:
            result = await wait_job(args, getter, result, watch=True)
        if args.command == "search-knowledge-cards":
            result = [{k: v for k, v in row.items() if k != "yaml"} for row in result["results"]]
        return result
