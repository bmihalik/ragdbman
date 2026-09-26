# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Read-only corpus discovery and unified retrieval, independent of MCP transport."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .errors import RagError
from .knowledge_cards import dump_cards
from .models import Request, SearchFilters, SearchRequest


class CorpusQuery(Request):
    query: str = Field(min_length=1)
    collections: list[str] | None = None
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    perspective: Literal["general", "expert"] = "general"
    limit: int = Field(5, ge=1, strict=True)
    minimum_score: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.query.strip() or self.collections == []:
            raise ValueError("query and explicit collections must not be empty")
        return self


def scope(engine, requested, admin=False, catalog=False):
    allowed = None if admin else engine.config.server.mcp_allowed_collections
    names = (
        requested
        if requested is not None
        else sorted(engine.registry)
        if catalog
        else engine.config.server.mcp_default_collections
    )
    names = list(dict.fromkeys(names))
    if requested is None and catalog and allowed is not None:
        names = [name for name in names if name in allowed]
    if allowed is not None and any(name not in allowed for name in names):
        raise RagError("PATH_NOT_ALLOWED", "One or more collections are outside this MCP profile's scope")
    if not names and not catalog:
        raise RagError("CONFIG_INVALID", "Specify collections or configure server.mcp_default_collections")
    return names


def describe(engine, collections=None, admin=False):
    catalog = collections is None
    records = []
    for name in scope(engine, collections, admin, catalog=True):
        meta = engine.get_collection(name)
        is_card = meta["kind"] == "knowledge_cards"
        item = dict(
            name=name,
            description=meta["description"],
            kind=meta["kind"],
            counts=meta["counts"],
            capabilities=dict(
                modes=["keyword", "semantic", "hybrid"],
                perspectives=["general", "expert"] if is_card else ["general"],
                filters=[] if is_card else list(SearchFilters.model_fields),
            ),
        )
        if not catalog:
            item["embedding"] = meta["embedding"]
            item["defaults"] = dict(
                mode="hybrid",
                perspective="general",
                limit=5,
                minimum_score=engine.kc_settings.min_similarity if is_card else None,
            )
            item["fields"] = (
                [
                    "category",
                    "subcategory",
                    "title",
                    "description",
                    "positive_text",
                    "negative_text",
                    "method_texts",
                    "inputs",
                    "outputs",
                    "costs",
                    "codes",
                    "confidence",
                    "source",
                ]
                if is_card
                else [
                    {k: f[k] for k in ("canonical_name", "value_type")}
                    for f in engine.list_metadata_fields(name)
                ]
            )
        records.append(item)
    return dict(
        collections=records,
        default_collections=engine.config.server.mcp_default_collections,
        max_limit=engine.config.search.max_top_k,
    )


async def query(engine, request: CorpusQuery, admin=False):
    names = scope(engine, request.collections, admin)
    limit = min(request.limit, engine.config.search.max_top_k)
    mode = "vector" if request.mode == "semantic" else request.mode
    results, warnings, searched, effective = [], [], [], []
    for name in names:
        try:
            meta = engine.get_collection(name)
            is_card = meta["kind"] == "knowledge_cards"
            applied_perspective = request.perspective if is_card else "general"
            if request.perspective == "expert" and not is_card:
                warnings.append(
                    dict(
                        collection=name,
                        code="PERSPECTIVE_NOT_APPLICABLE",
                        message="Expert card weighting does not apply; using ordinary retrieval.",
                    )
                )
            if is_card:
                if any(request.filters.model_dump().values()):
                    raise RagError("CONFIG_INVALID", "Knowledge Cards do not support document filters")
                minimum = (
                    engine.kc_settings.min_similarity
                    if request.minimum_score is None
                    else request.minimum_score
                )
                diagnostics = {}
                matches = await engine.search_knowledge_cards(
                    collection=name,
                    query=request.query,
                    mode=mode,
                    query_type=request.perspective,
                    top_k=limit,
                    minimum_similarity=minimum,
                    diagnostics=diagnostics,
                )
                converted = [
                    dict(
                        kind="knowledge_card",
                        collection=name,
                        title=m["card"]["title"],
                        relevance=dict(
                            score=m["score"],
                            policy="confidence_weighted",
                            vector=m["vector_score"],
                            keyword=m["keyword_score"],
                        ),
                        provenance=dict(
                            filename=Path(m["source_path"]).name, references=m["card"].get("source", [])
                        ),
                        content={k: v for k, v in m["card"].items() if k != "id"},
                    )
                    for m in matches
                ]
                if diagnostics["keyword_fallback"]:
                    warnings.append(
                        dict(
                            collection=name,
                            code="KEYWORD_FALLBACK",
                            message="Ollama unavailable; used keyword retrieval.",
                        )
                    )
                score_policy = "confidence_weighted"
            else:
                # Fail closed rather than letting the document engine ignore unknown numeric fields.
                fields = engine.list_metadata_fields(name)
                available = {f["canonical_name"].lower() for f in fields}
                import json

                available.update(a.lower() for f in fields for a in json.loads(f["aliases_json"]))
                if any(f.field.lower() not in available for f in request.filters.numeric):
                    raise RagError(
                        "CONFIG_INVALID", "A numeric filter field is unsupported by this collection"
                    )
                response = await engine.search(
                    SearchRequest(
                        collection=name,
                        query=request.query,
                        mode=mode,
                        top_k=engine.config.search.max_top_k,
                        filters=request.filters,
                    )
                )
                if response["skipped_filters"]:
                    raise RagError("CONFIG_INVALID", "Some filters could not be applied")
                minimum = request.minimum_score
                score_policy = {
                    "keyword": "bm25_strength",
                    "semantic": "inverse_l2",
                    "hybrid": "weighted_rrf",
                }[request.mode]
                converted = []
                for m in response["results"]:
                    if minimum is not None and m["score"] < minimum:
                        continue
                    converted.append(
                        dict(
                            kind="source_code" if meta["kind"] == "source_code" else "document",
                            collection=name,
                            title=m["heading"] or m["source_filename"],
                            relevance=dict(
                                score=m["score"],
                                policy=score_policy,
                                vector=m["vector_score"],
                                keyword=m["keyword_score"],
                            ),
                            provenance={
                                k: m[k]
                                for k in (
                                    "source_filename",
                                    "citation_label",
                                    "original_url",
                                    "section_path",
                                    "page_start",
                                    "page_end",
                                    "line_start",
                                    "line_end",
                                    "slide_start",
                                    "slide_end",
                                    "time_start_ms",
                                    "time_end_ms",
                                )
                            },
                            content=m["text"],
                            truncated=m["truncated"],
                        )
                    )
            searched.append(name)
            effective.append(
                dict(
                    collection=name,
                    mode=request.mode,
                    perspective=applied_perspective,
                    minimum_score=minimum,
                    score_policy=score_policy,
                    filters=request.filters.model_dump(),
                )
            )
            for rank, result in enumerate(converted[:limit], 1):
                result["relevance"]["collection_rank"] = rank
                result["relevance"]["fusion_score"] = 1 / (engine.config.search.rrf_k + rank)
                results.append(result)
        except RagError as exc:
            warnings.append(dict(collection=name, code=exc.code, message=str(exc)))
    # Collection ranks avoid comparing unrelated metrics. No cross-corpus deduplication:
    # indexing the same source by different strategies is intentionally supported.
    results.sort(
        key=lambda r: (-r["relevance"]["fusion_score"], r["collection"], r["relevance"]["collection_rank"])
    )
    results = results[:limit]
    for rank, result in enumerate(results, 1):
        result["rank"] = rank
    return dict(
        query=request.query,
        effective_options=dict(
            limit=limit,
            ranking="reciprocal_collection_rank",
            collections=effective,
        ),
        collections_searched=searched,
        warnings=warnings,
        results=results,
    )


def fence(text, language):
    import re

    length = max([3, *[len(m) + 1 for m in re.findall(r"`+", text)]])
    marker = "`" * length
    separator = "" if text.endswith("\n") else "\n"
    return f"{marker}{language}\n{text}{separator}{marker}"


def render(response):
    """Fixed labels distinguish untrusted retrieved content from navigation."""
    import json

    parts = ["# Corpus query results", f"{len(response['results'])} results."]
    for item in response["results"]:
        label = {
            "knowledge_card": "Knowledge Card",
            "source_code": "Source code",
            "document": "Document excerpt",
        }[item["kind"]]
        # Titles and collection names are JSON-quoted inside a fence, never interpolated as instructions.
        parts.append(f"## Result {item['rank']} · {label}")
        parts.append(
            fence(
                json.dumps(
                    dict(title=item["title"], collection=item["collection"], provenance=item["provenance"]),
                    ensure_ascii=False,
                    indent=2,
                ),
                "json",
            )
        )
        parts.append(
            fence(dump_cards([item["content"]]), "yaml")
            if item["kind"] == "knowledge_card"
            else fence(item["content"] or "", "text")
        )
    if not response["results"]:
        parts.append("No results met the requested scope, filters and relevance thresholds.")
    if response["warnings"]:
        parts.extend(["## Diagnostics", fence(json.dumps(response["warnings"], indent=2), "json")])
    return "\n\n".join(parts)
