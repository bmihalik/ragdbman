# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Canonical CLI parsing, rendering and local/REST dispatch."""

import argparse
import asyncio
import ipaddress
import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .errors import RagError
from .models import NumericFilter
from .operations import JOB_OPERATIONS, OPERATIONS, invoke, validate

COMMANDS = tuple(name.replace("_", "-") for name in OPERATIONS)
JOBS = {name.replace("_", "-") for name in JOB_OPERATIONS}


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def nonnegative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return value


def nonempty(text):
    if not text.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def csv_list(text):
    values = [v.strip() for v in text.split(",")]
    if not all(values):
        raise argparse.ArgumentTypeError("expected a nonempty comma-separated list")
    return list(dict.fromkeys(values))


def collection_name(text):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", text):
        raise argparse.ArgumentTypeError("invalid collection name")
    return text


def collection_list(text):
    return [collection_name(value) for value in csv_list(text)]


def numeric(text):
    try:
        field, op, *operands = shlex.split(text)
        count = 0 if op == "exists" else 2 if op == "between" else 1
        if len(operands) != count:
            raise ValueError(f"{op} requires {count} operand(s)")
        values = {"field": field, "op": op}
        if op == "between":
            values.update({"from": operands[0], "to": operands[1]})
        elif op != "exists":
            values["value"] = operands[0]
        return NumericFilter(**values)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid numeric filter: {exc}") from exc


def arguments(item, command):
    op = command.replace("-", "_")
    schema = OPERATIONS[op].model.model_json_schema()
    item.add_argument(
        "--server-url", type=nonempty, help="Daemon administrative REST URL; no local fallback."
    )
    item.add_argument("--timeout", type=positive, default=600, help="Per-request REST timeout in seconds.")
    if op not in {"corpus_query", "corpus_graph"}:
        item.add_argument("--format", choices=["raw", "table"], default="raw", help="Output presentation.")
    for name, prop in schema["properties"].items():
        option = "--" + name.replace("_", "-")
        default = prop.get("default")
        required = name in schema.get("required", [])
        help_text = prop.get("description") or f"{name.replace('_', ' ').capitalize()} for {command}."
        kwargs = dict(default=default, required=required, help=help_text)
        if name == "format":
            kwargs.update(choices=["raw", "llm", "table"], default="raw")
        elif name in {"collections", "source_roots", "relationships"}:
            kwargs["type"] = collection_list if name == "collections" else csv_list
            if name == "source_roots":
                kwargs["default"] = []
        elif name == "filters":
            kwargs.update(type=json.loads, default={})
        elif name in {"confirm", "delete_files", "delete_original_managed_file", "prune_missing"}:
            kwargs.update(action="store_true", default=False)
        elif name in {"recursive", "include_text", "include_links", "include_graph_context"}:
            kwargs.update(action=argparse.BooleanOptionalAction)
        elif name in {"limit", "depth", "chunk_size_tokens"}:
            kwargs["type"] = positive
        elif name in {"offset", "chunk_overlap_tokens"}:
            kwargs["type"] = nonnegative
        elif name == "minimum_score":
            kwargs["type"] = float
        elif name in {"collection", "name"}:
            kwargs["type"] = collection_name
        elif name in {"source_id", "root_id", "job_id", "path", "root", "filename"}:
            kwargs["type"] = nonempty
        else:
            choices = prop.get("enum")
            if not choices:
                choices = next((p.get("enum") for p in prop.get("anyOf", []) if p.get("enum")), None)
            if choices:
                kwargs["choices"] = choices
        item.add_argument(option, **kwargs)
    if op == "corpus_query":
        item.add_argument(
            "--numeric", type=numeric, action="append", default=[], help="Repeatable numeric filter."
        )
    if command in JOBS:
        item.add_argument(
            "--wait", action="store_true", help="Wait for a daemon job; direct jobs always wait."
        )
    if op == "scan_job_get":
        item.add_argument(
            "--watch", action="store_true", help="Print snapshots every two seconds until stopped."
        )
    if op == "collection_export_manifest":
        item.add_argument("--output", help="Write a new client-local JSON file; refuse overwrite.")


def contract(args):
    op = args.command.replace("-", "_")
    values = {key: getattr(args, key) for key in OPERATIONS[op].model.model_fields}
    if values.get("format") == "table":
        values["format"] = "raw"
    if op == "corpus_query":
        values["filters"] = dict(values["filters"])
        values["filters"]["numeric"] = values["filters"].get("numeric", []) + [
            v.model_dump(by_alias=True) for v in args.numeric
        ]
    return op, validate(op, values).model_dump()


def clean(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[1:-1] if isinstance(value, str) else text


def table(command, payload):
    diagnostics = []
    if isinstance(payload, dict):
        for key in ("warnings", "collections_failed", "skipped_filters"):
            if payload.get(key):
                diagnostics.append(key + ": " + clean(payload[key]))
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
        return "\n".join(["(no rows)", *diagnostics])
    if command == "corpus-query":
        rows = [
            {
                "rank": r["rank"],
                "collection": r["collection"],
                "kind": r["kind"],
                "title": r["title"],
                "score": r["relevance"]["score"],
                "content": r["content"],
            }
            for r in rows
        ]
    columns = list(rows[0])
    data = [[clean(row.get(k, "")) for k in columns] for row in rows]
    widths = [min(80, max(len(k), *(len(row[i]) for row in data))) for i, k in enumerate(columns)]

    def line(values):
        return " | ".join(
            (v if len(v) <= w else v[: w - 3] + "...").ljust(w) for v, w in zip(values, widths, strict=True)
        )

    return "\n".join([line(columns), "-+-".join("-" * w for w in widths), *map(line, data), *diagnostics])


def emit(args, payload, snapshot=False):
    output = (
        payload
        if isinstance(payload, str)
        else table(args.command, payload)
        if args.format == "table"
        else (json.dumps(payload, ensure_ascii=False, indent=None if snapshot else 2, allow_nan=False))
    )
    if getattr(args, "output", None):
        with Path(args.output).expanduser().open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    else:
        print(output, flush=True)


def exit_status(args, payload):
    if isinstance(payload, dict):
        if args.command in JOBS | {"scan-job-get"} and payload.get("status") in {
            "failed",
            "completed_with_errors",
            "cancelled",
            "paused",
        }:
            return 3
        if (
            args.command == "corpus-query"
            and payload.get("warnings")
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
    result = await invoke(engine, method, kwargs)

    async def getter(job_id):
        return engine.scan_job_get(args.collection, job_id)

    if args.command in JOBS:
        return await wait_job(args, getter, result, engine.tasks.get(result["id"]))
    if args.command == "scan-job-get" and args.watch:
        return await wait_job(args, getter, result, watch=True)
    return result


def endpoint(args, kwargs):
    return "POST", "/api/" + args.command, {}, kwargs


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
            "--server-url requires HTTPS or loopback HTTP without credentials/query/fragment",
        )
    token = os.environ.get("RAGDBMAN_AUTH_TOKEN")
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token} if token else {},
        timeout=args.timeout,
        follow_redirects=False,
        trust_env=False,
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
            return (
                response.text
                if response.headers.get("content-type", "").startswith("text/plain")
                else response.json()
            )

        result = await request(*endpoint(args, kwargs))

        async def getter(job_id):
            return await request(
                "POST", "/api/scan-job-get", body={"collection": args.collection, "job_id": job_id}
            )

        if args.command in JOBS and args.wait:
            return await wait_job(args, getter, result)
        if args.command == "scan-job-get" and args.watch:
            return await wait_job(args, getter, result, watch=True)
        return result
