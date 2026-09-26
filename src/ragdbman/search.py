# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""FTS5/BM25, sqlite-vec, structured filters and rank fusion."""

import json
import operator
from pathlib import Path

import sqlite_vec

from . import db
from .config import GlobalConfig
from .models import SearchRequest
from .ollama import Embedder

OPS = {
    "equal": operator.eq,
    "not_equal": operator.ne,
    "less_than": operator.lt,
    "less_than_or_equal": operator.le,
    "greater_than": operator.gt,
    "greater_than_or_equal": operator.ge,
}


def filter_ids(conn, filters) -> tuple[set[str] | None, list[str], list[dict]]:
    allowed = None
    applied, skipped = [], []

    def intersect(ids):
        nonlocal allowed
        allowed = ids if allowed is None else allowed & ids

    for nf in filters.numeric:
        field = next(
            (
                f
                for f in db.rows(conn, "SELECT * FROM metadata_fields")
                if nf.field.lower() == f["canonical_name"]
                or nf.field.lower() in json.loads(f["aliases_json"])
            ),
            None,
        )
        if field is None:
            skipped.append({"field": nf.field, "reason": "field not found in metadata_fields"})
            continue
        is_date = field["value_type"] == "date"

        def normalized(value, is_date=is_date):
            if value is None:
                return None
            if is_date:
                value = str(value)
                return value + "T00:00:00Z" if len(value) == 10 else value
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        matches = set()
        for row in db.rows(conn, "SELECT * FROM chunk_numeric_values WHERE field_id=?", (field["id"],)):
            value = row["normalized_date_utc" if is_date else "normalized_number"]
            if value is None or (nf.currency and row["currency_code"] != nf.currency.upper()):
                continue
            if nf.op == "exists":
                match = True
            elif nf.op == "between":
                low, high = normalized(nf.from_), normalized(nf.to)
                match = low is not None and high is not None and low <= value <= high
            else:
                target = normalized(nf.value)
                match = target is not None and OPS[nf.op](value, target)
            if match:
                matches.add(row["chunk_id"])
        intersect(matches)
        applied.append(f"{nf.field} {nf.op}")
    for term in filters.keywords:
        intersect(
            {
                row[0]
                for row in conn.execute(
                    """SELECT ck.chunk_id FROM chunk_keywords ck
            JOIN keywords k ON k.id=ck.keyword_id WHERE k.canonical_form=?""",
                    (term.strip().lower(),),
                )
            }
        )
        applied.append(f"keyword:{term}")
    return allowed, applied, skipped


def citation(result: dict) -> str:
    label = result["source_filename"]
    for field, prefix in [("page", "p."), ("slide", "slide "), ("line", "lines ")]:
        start, end = result.get(field + "_start"), result.get(field + "_end")
        if start is not None:
            return f"{label}, {prefix}{start}" + (f"-{end}" if end is not None and end != start else "")
    if result.get("time_start_ms") is not None:
        start = result["time_start_ms"] // 1000
        return f"{label}, {start // 60}:{start % 60:02}"
    if result.get("percent_position") is not None:
        return f"{label}, ~{result['percent_position']:.0f}% through"
    return label


async def search(
    conn, collection: dict, request: SearchRequest, cfg: GlobalConfig, embedder: Embedder
) -> dict:
    allowed, applied, skipped = filter_ids(conn, request.filters)
    filters = request.filters
    candidates = {}
    for row in db.rows(
        conn,
        """SELECT c.*,s.original_filename,s.canonical_path,s.source_url,s.markdown_path,s.extension
        FROM chunks c JOIN sources s ON s.id=c.source_id WHERE s.deleted_at IS NULL AND s.status='indexed'""",
    ):
        if allowed is not None and row["id"] not in allowed:
            continue
        if filters.source_extensions and row["extension"] not in [
            x.lower().lstrip(".") for x in filters.source_extensions
        ]:
            continue
        if filters.source_ids and row["source_id"] not in filters.source_ids:
            continue
        if filters.path_prefix and not (row["canonical_path"] or "").startswith(filters.path_prefix):
            continue
        candidates[row["seq"]] = row
    for field in ("source_extensions", "source_ids", "path_prefix"):
        if getattr(filters, field):
            applied.append(field)
    vec_scores, kw_scores = {}, {}
    if candidates and request.mode in {"vector", "hybrid"}:
        embedding = collection["embedding"]
        query = (
            await embedder.embed(
                [request.query], embedding["model"], embedding["dimensions"], embedding["keep_alive"]
            )
        )[0]
        # Exact distance against all stored vectors: no post-filter candidate starvation.
        for row in conn.execute(
            """SELECT rowid, vec_distance_L2(embedding,?) AS distance FROM chunks_vec0
            ORDER BY distance,rowid""",
            (sqlite_vec.serialize_float32(query),),
        ):
            if row[0] in candidates:
                vec_scores[row[0]] = 1 / (1 + row[1])
    if candidates and request.mode in {"keyword", "hybrid"} and request.query.strip():
        # Literal user terms rather than accepting executable FTS query syntax.
        import re

        terms = re.findall(r"\w+", request.query, re.UNICODE)
        query = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        if query:
            for row in conn.execute(
                """SELECT rowid,bm25(chunks_fts) AS score FROM chunks_fts
                WHERE chunks_fts MATCH ? ORDER BY score,rowid""",
                (query,),
            ):
                if row[0] in candidates:
                    kw_scores[row[0]] = -row[1]
    if request.mode == "structured":
        ranked = [(seq, 1.0) for seq in candidates]
    elif request.mode == "vector":
        ranked = list(vec_scores.items())
    elif request.mode == "keyword":
        ranked = list(kw_scores.items())
    else:
        fused = {}
        for scores, weight in [
            (vec_scores, cfg.search.vector_weight),
            (kw_scores, cfg.search.keyword_weight),
        ]:
            for rank, seq in enumerate(scores, 1):
                fused[seq] = fused.get(seq, 0) + weight / (cfg.search.rrf_k + rank)
        ranked = sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
    limit = min(request.top_k or cfg.search.default_top_k, cfg.search.max_top_k)
    results = []
    for seq, score in ranked[:limit]:
        chunk = candidates[seq]
        facts = db.rows(
            conn,
            """SELECT f.canonical_name AS field,n.raw_value,n.normalized_number,
            n.normalized_date_utc,n.currency_code,n.unit,n.confidence FROM chunk_numeric_values n
            JOIN metadata_fields f ON f.id=n.field_id WHERE n.chunk_id=?""",
            (chunk["id"],),
        )
        words = [
            r[0]
            for r in conn.execute(
                """SELECT k.canonical_form FROM keywords k JOIN chunk_keywords ck
            ON ck.keyword_id=k.id WHERE ck.chunk_id=? ORDER BY k.canonical_form""",
                (chunk["id"],),
            )
        ]
        text = chunk["text"]
        max_chars = cfg.search.return_context_chars_per_chunk
        path = chunk["canonical_path"]
        link = (
            Path(path).as_uri()
            if path and Path(path).is_absolute() and cfg.security.allow_file_uri_links
            else None
        )
        result = dict(
            collection_id=collection["id"],
            chunk_id=chunk["id"],
            score=score,
            vector_score=vec_scores.get(seq),
            keyword_score=kw_scores.get(seq),
            text=text[:max_chars] if request.include_text else None,
            truncated=request.include_text and len(text) > max_chars,
            heading=chunk["heading"],
            source_id=chunk["source_id"],
            source_filename=chunk["original_filename"],
            source_path=path,
            source_link=link if request.include_links else None,
            original_url=chunk["source_url"]
            if cfg.security.allow_http_source_urls and request.include_links
            else None,
            markdown_path=chunk["markdown_path"],
            metadata_facts=facts,
            matched_keywords=words,
            section_path=chunk["section_path"],
        )
        for field in (
            "page_start",
            "page_end",
            "slide_start",
            "slide_end",
            "time_start_ms",
            "time_end_ms",
            "line_start",
            "line_end",
            "percent_position",
        ):
            result[field] = chunk[field]
        result["citation_label"] = citation(result)
        results.append(result)
    return dict(results=results, applied_filters=applied, skipped_filters=skipped, exhaustive=True)
