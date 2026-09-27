# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Bounded read-only traversal and revision-checked chunk citations."""

import json
from contextlib import contextmanager
from typing import Literal

from pydantic import Field, model_validator

from .. import db
from ..models import Request
from .parser import normalize, parser_version

Relation = Literal[
    "contains", "imports", "calls", "inherits", "implements", "type_base", "references", "depends_on"
]
LIMITATION = "Parser-observed syntax with best-effort static resolution; not a compiler-verified or runtime call graph."


class GraphRequest(Request):
    collection: str
    action: Literal["find", "neighbors", "callers", "callees", "dependencies", "inheritance", "impact"] = (
        "neighbors"
    )
    symbol: str | None = None
    entity_id: str | None = None
    source_id: str | None = None
    direction: Literal["outgoing", "incoming", "both"] = "outgoing"
    relationships: list[Relation] | None = None
    depth: int = Field(1, ge=1, le=5, strict=True)
    limit: int = Field(50, ge=1, le=200, strict=True)

    @model_validator(mode="after")
    def selector(self):
        if self.symbol is not None and not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if self.entity_id and self.symbol:
            raise ValueError("Specify entity_id or symbol, not both")
        if self.action != "find" and not (self.entity_id or self.symbol or self.source_id):
            raise ValueError("A symbol, entity_id or source_id is required")
        return self


class Reader:
    def __init__(self, primary, graph, budget=5000):
        self.primary, self.graph = primary, graph
        self.sources, self.entities, self.resolutions = {}, {}, {}
        self.budget, self.inspected, self.truncated = budget, 0, False

    def source(self, source_id):
        if source_id not in self.sources:
            row = self.graph.execute("SELECT * FROM graph_sources WHERE source_id=?", (source_id,)).fetchone()
            source = self.primary.execute(
                "SELECT status,content_hash_sha256,deleted_at FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            valid = bool(
                row
                and source
                and source["status"] == "indexed"
                and source["deleted_at"] is None
                and source["content_hash_sha256"] == row["content_hash"]
                and parser_version(row["language"]) == row["parser_version"]
            )
            self.sources[source_id] = dict(row) if valid else None
        return self.sources[source_id]

    def candidates(self, sql, args=(), limit=101):
        result = []
        rows = self.graph.execute(sql + " LIMIT ?", (*args, limit + 1)).fetchall()
        if len(rows) > limit:
            self.truncated = True
        for row in rows[:limit]:
            self.inspected += 1
            if self.inspected > self.budget:
                self.truncated = True
                break
            item = dict(row)
            if self.source(item["source_id"]):
                result.append(item)
        return result

    def entity(self, identifier):
        if identifier not in self.entities:
            row = self.graph.execute("SELECT * FROM graph_entities WHERE id=?", (identifier,)).fetchone()
            self.entities[identifier] = dict(row) if row and self.source(row["source_id"]) else None
        return self.entities[identifier]

    def qualified(self, root, key, source_id=None, language=None):
        # Match declared module boundaries exactly, rather than fuzzy suffix matches.
        args = [root, key, key]
        sql = """SELECT e.* FROM graph_entities e JOIN graph_sources s ON s.source_id=e.source_id
                 WHERE s.root_key=? AND
                 ((e.qualified_name='' AND s.module_key=?) OR
                  (CASE WHEN s.module_key='' THEN e.qualified_name
                        ELSE s.module_key||'.'||e.qualified_name END)=?)"""
        if source_id:
            sql += " AND e.source_id=?"
            args.append(source_id)
        if language:
            family = (
                ["javascript", "typescript", "tsx"]
                if language in {"javascript", "typescript", "tsx"}
                else [language]
            )
            sql += " AND s.language IN (" + ",".join("?" for _ in family) + ")"
            args.extend(family)
        return self.candidates(sql + " ORDER BY e.id", args)

    def resolve(self, edge):
        if edge["id"] in self.resolutions:
            return self.resolutions[edge["id"]]
        source = self.source(edge["source_id"])
        owner = self.entity(edge["from_id"])
        candidates, method = [], "unresolved"
        if not source or not owner:
            return [], "stale"
        if edge["target_hint"]:
            item = self.entity(edge["target_hint"])
            candidates = [item] if item and item["source_id"] == owner["source_id"] else []
            method = "syntax"
        elif edge["target_mode"] == "file":
            candidates = self.candidates(
                """SELECT e.* FROM graph_entities e JOIN graph_sources s ON s.source_id=e.source_id
                WHERE s.root_key=? AND s.path=? AND e.kind='module' AND e.qualified_name='' ORDER BY e.id""",
                (source["root_key"], edge["target_key"]),
            )
            method = "include_static"
        elif edge["target_mode"] == "qualified":
            candidates = self.qualified(source["root_key"], edge["target_key"], language=source["language"])
            method = "import_static"
        elif edge["target_mode"] == "lexical":
            key = edge["target_key"]
            scope = owner["qualified_name"]
            # Search nested lexical declarations before outer scopes, and never
            # bypass a shadowing variable/parameter to invent a function target.
            while True:
                prefix = ".".join(filter(None, (scope, key.split(".")[0])))
                if "." in key:
                    shadow = self.candidates(
                        "SELECT * FROM graph_entities WHERE source_id=? AND qualified_name=? "
                        "AND kind IN ('variable','parameter') ORDER BY id",
                        (owner["source_id"], prefix),
                    )
                    if shadow:
                        break
                class_scope = False
                if source["language"] == "python" and owner["kind"] in {"method", "function"} and scope:
                    class_scope = bool(
                        self.graph.execute(
                            "SELECT 1 FROM graph_entities WHERE source_id=? AND qualified_name=? AND kind='class'",
                            (owner["source_id"], scope),
                        ).fetchone()
                    )
                qualified = ".".join(filter(None, (scope, key)))
                candidates = (
                    []
                    if class_scope
                    else self.candidates(
                        "SELECT * FROM graph_entities WHERE source_id=? AND qualified_name=? AND kind!='implementation' ORDER BY id",
                        (owner["source_id"], qualified),
                    )
                )
                if candidates or not scope:
                    break
                scope = scope.rsplit(".", 1)[0] if "." in scope else ""
            method = "local_static"
            if not candidates and source["language"] == "go":
                candidates = self.qualified(
                    source["root_key"], source["module_key"] + "." + key, language=source["language"]
                )
                method = "package_static"
        candidates = [e for e in candidates if e["kind"] != "implementation"]
        if (
            edge["kind"] == "calls"
            and candidates
            and all(e["kind"] in {"variable", "parameter"} for e in candidates)
        ):
            candidates, method = [], "unresolved_binding"
        if edge["kind"] == "depends_on" and candidates:
            modules = [
                self.graph.execute(
                    "SELECT * FROM graph_entities WHERE source_id=? AND kind='module' AND qualified_name=''",
                    (e["source_id"],),
                ).fetchone()
                for e in candidates
            ]
            candidates = list({r["id"]: dict(r) for r in modules if r}.values())
        result = (candidates, "ambiguous" if len(candidates) > 1 else method if candidates else "unresolved")
        self.resolutions[edge["id"]] = result
        return result

    def citation(self, source_id, start, end):
        source = self.source(source_id)
        if not source:
            return None
        chunks = db.rows(
            self.primary,
            """SELECT id,chunk_index,line_start,line_end FROM chunks
            WHERE source_id=? AND line_start<=? AND line_end>=?
            ORDER BY chunk_index LIMIT 9""",
            (source_id, end, start),
        )
        return dict(
            source_id=source_id,
            source_path=source["path"],
            content_hash=source["content_hash"],
            line_start=start,
            line_end=end,
            chunks=[
                dict(
                    chunk_id=c["id"],
                    chunk_index=c["chunk_index"],
                    line_start=c["line_start"],
                    line_end=c["line_end"],
                )
                for c in chunks[:8]
            ],
            chunks_truncated=len(chunks) > 8,
        )

    def public_entity(self, entity):
        return dict(
            entity_id=entity["id"],
            kind=entity["kind"],
            name=entity["name"],
            qualified_name=entity["qualified_name"],
            signature=entity["signature"],
            language=self.source(entity["source_id"])["language"],
            provenance=self.citation(entity["source_id"], entity["line_start"], entity["line_end"]),
        )

    def public_edge(self, edge):
        candidates, resolution = self.resolve(edge)
        target = candidates[0] if len(candidates) == 1 else None
        kind = edge["kind"]
        if kind == "type_base" and target:
            owner = self.entity(edge["from_id"])
            kind = "implements" if owner["kind"] == "class" and target["kind"] == "interface" else "inherits"
        return dict(
            relationship_id=edge["id"],
            kind=kind,
            from_entity_id=edge["from_id"],
            from_name=self.entity(edge["from_id"])["qualified_name"],
            target_name=edge["target_name"],
            target_entity_id=target["id"] if target else None,
            resolved_target_name=target["qualified_name"] if target else None,
            resolution=resolution,
            observed="syntax",
            evidence=edge["evidence"],
            candidate_entity_ids=[e["id"] for e in candidates[:10]] if len(candidates) > 1 else [],
            candidates_truncated=len(candidates) > 10,
            provenance=self.citation(edge["source_id"], edge["line_start"], edge["line_end"]),
        )

    def neighbors(self, entity, direction, kinds, limit):
        result, seen = [], set()
        if direction in {"outgoing", "both"}:
            for row in self.graph.execute(
                "SELECT * FROM graph_relationships WHERE from_id=? ORDER BY line_start,id LIMIT ?",
                (entity["id"], min(self.budget, 5000)),
            ):
                self.inspected += 1
                if self.inspected > self.budget:
                    self.truncated = True
                    break
                edge = dict(row)
                if kinds and edge["kind"] not in kinds:
                    continue
                result.append((edge, "outgoing"))
                seen.add(edge["id"])
                if len(result) >= limit:
                    return result
        if direction in {"incoming", "both"} and not self.truncated:
            # Explicit bindings use the imported symbol's leaf, so aliases such as
            # `from x import parse as load` remain discoverable as incoming calls.
            target = entity["name"]
            sql = """SELECT * FROM graph_relationships WHERE
                (target_leaf=? OR target_hint=? OR (? AND kind='depends_on'))
                ORDER BY source_id,line_start,id LIMIT ?"""
            for row in self.graph.execute(
                sql, (target, entity["id"], entity["kind"] == "module", min(self.budget, 5000))
            ):
                self.inspected += 1
                if self.inspected > self.budget:
                    self.truncated = True
                    break
                edge = dict(row)
                if (
                    edge["id"] in seen
                    or (kinds and edge["kind"] not in kinds)
                    or not self.source(edge["source_id"])
                ):
                    continue
                targets, _ = self.resolve(edge)
                if len(targets) != 1 or targets[0]["id"] != entity["id"]:
                    continue
                result.append((edge, "incoming"))
                if len(result) >= limit:
                    return result
        return result


@contextmanager
def read_snapshot(primary_factory, store):
    with primary_factory() as primary, store.pool.connection() as graph:
        primary.execute("BEGIN")
        primary.execute("SELECT id FROM collection_meta").fetchone()
        graph.execute("BEGIN")
        yield Reader(primary, graph)


def traverse(primary_factory, store, request):
    response = dict(
        collection=request.collection,
        action=request.action,
        limitation=LIMITATION,
        candidates=[],
        entities=[],
        relationships=[],
        chains=[],
        truncated=False,
    )
    if not store.path.is_file():
        return {
            **response,
            "status": "not_indexed",
            "message": "Scan this source-code collection to build its graph.",
        }
    with read_snapshot(primary_factory, store) as reader:
        args, conditions = [], []
        if request.entity_id:
            conditions.append("e.id=?")
            args.append(request.entity_id)
        if request.source_id:
            conditions.append("e.source_id=?")
            args.append(request.source_id)
        if request.symbol:
            symbol = normalize(request.symbol)
            if request.action == "find":
                conditions.append(
                    "(instr(lower(e.name),lower(?))>0 OR instr(lower(e.qualified_name),lower(?))>0)"
                )
                args.extend([symbol, symbol])
            else:
                conditions.append("(e.name=? OR e.qualified_name=? OR s.module_key||'.'||e.qualified_name=?)")
                args.extend([symbol, symbol, symbol])
        elif request.source_id and request.action != "find" and not request.entity_id:
            conditions.append("e.kind='module' AND e.qualified_name=''")
        matches = reader.candidates(
            "SELECT e.* FROM graph_entities e JOIN graph_sources s ON s.source_id=e.source_id"
            + (" WHERE " + " AND ".join(conditions) if conditions else "")
            + " ORDER BY s.path,e.line_start,e.id",
            args,
            request.limit + 1,
        )
        response["candidates"] = [reader.public_entity(e) for e in matches[: request.limit]]
        if request.action == "find":
            return {**response, "status": "ok", "truncated": len(matches) > request.limit or reader.truncated}
        if len(matches) != 1:
            return {
                **response,
                "status": "ambiguous" if matches else "not_found",
                "truncated": reader.truncated or len(matches) > request.limit,
                "message": "Select one candidate entity_id."
                if matches
                else "No current graph entity matched.",
            }
        presets = {
            "callers": ("incoming", ["calls"]),
            "callees": ("outgoing", ["calls"]),
            "dependencies": ("outgoing", ["depends_on"]),
            "inheritance": ("outgoing", ["inherits", "implements", "type_base"]),
            "impact": (
                "incoming",
                ["calls", "references", "inherits", "implements", "type_base", "depends_on"],
            ),
        }
        direction, kinds = presets.get(request.action, (request.direction, request.relationships))
        if request.relationships is not None:
            kinds = request.relationships
        seed = matches[0]
        entities = {seed["id"]: seed}
        edges, chains, visited = {}, [], {seed["id"]}
        frontier = [(seed, [])]
        for _ in range(request.depth):
            following = []
            for current, chain in frontier:
                for raw, orientation in reader.neighbors(current, direction, kinds, request.limit + 1):
                    if len(edges) >= request.limit or reader.truncated:
                        response["truncated"] = True
                        break
                    edge = reader.public_edge(raw)
                    if edge["relationship_id"] in edges:
                        continue
                    edges[edge["relationship_id"]] = edge
                    step = dict(relationship_id=edge["relationship_id"], direction=orientation)
                    new_chain = chain + [step]
                    chains.append(new_chain)
                    next_id = (
                        edge["target_entity_id"] if orientation == "outgoing" else edge["from_entity_id"]
                    )
                    neighbor = reader.entity(next_id) if next_id else None
                    if neighbor:
                        entities[neighbor["id"]] = neighbor
                        if neighbor["id"] not in visited:
                            visited.add(neighbor["id"])
                            following.append((neighbor, new_chain))
                if response["truncated"]:
                    break
            frontier = following
            if not frontier or response["truncated"]:
                break
        return {
            **response,
            "status": "ok",
            "entities": [reader.public_entity(e) for e in entities.values()],
            "relationships": list(edges.values()),
            "chains": chains,
            "truncated": response["truncated"] or reader.truncated,
            "effective_options": dict(
                direction=direction, relationships=kinds, depth=request.depth, limit=request.limit
            ),
        }


def enrich(primary_factory, store, results, context_limit):
    if not store.path.is_file():
        for result in results:
            result["graph_context"] = dict(available=False, status="not_indexed", limitation=LIMITATION)
        return
    with read_snapshot(primary_factory, store) as reader:
        for result in results:
            source = reader.source(result["source_id"])
            chunk = reader.primary.execute(
                "SELECT 1 FROM chunks WHERE id=? AND source_id=?", (result["chunk_id"], result["source_id"])
            ).fetchone()
            if not source or not chunk:
                result["graph_context"] = dict(
                    available=False, status="pending_or_stale", limitation=LIMITATION
                )
                continue
            context = dict(
                available=source["status"] in {"parsed", "truncated"},
                status=source["status"],
                language=source["language"],
                parser_version=source["parser_version"],
                limitation=LIMITATION,
                entities=[],
                relationships=[],
                imports=json.loads(source["imports_json"])[:context_limit],
                warnings=json.loads(source["warnings_json"]),
                truncated=source["status"] == "truncated",
            )
            start, end = result.get("line_start"), result.get("line_end")
            if start is not None and end is not None:
                entities = reader.candidates(
                    """SELECT * FROM graph_entities WHERE source_id=? AND kind NOT IN ('variable','parameter')
                    AND line_start<=? AND line_end>=?
                    ORDER BY (line_end-line_start),line_start,id""",
                    (result["source_id"], end, start),
                    context_limit + 1,
                )
                context["entities"] = [reader.public_entity(e) for e in entities[:context_limit]]
                edges = {}
                for entity in entities[:context_limit]:
                    for raw, _ in reader.neighbors(
                        entity, "both", ["calls", "inherits", "implements", "references"], context_limit + 1
                    ):
                        if len(edges) >= context_limit:
                            context["truncated"] = True
                            break
                        edge = reader.public_edge(raw)
                        edges[edge["relationship_id"]] = edge
                    if len(edges) >= context_limit:
                        break
                context["relationships"] = list(edges.values())
                context["truncated"] |= len(entities) > context_limit or reader.truncated
            result["graph_context"] = context
