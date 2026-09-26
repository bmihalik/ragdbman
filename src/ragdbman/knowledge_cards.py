# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Whole-card YAML ingestion, field vectors, confidence scores and serialization."""

from __future__ import annotations

import math
import os
import re
from contextlib import closing
from importlib.resources import files

import sqlite_vec
import yaml
from pydantic import BaseModel, Field, ValidationError

from . import db
from .errors import RagError
from .models import KnowledgeCard

EMPTY_RESULT = "No Knowledge Cards met the required relevance and confidence thresholds."
REQUIRED = {"id", "category", "title", "description", "confidence"}


class Settings(BaseModel):
    default_top_k: int = Field(3, ge=1)
    min_similarity: float = Field(0.65, ge=0, le=1, allow_inf_nan=False)
    alpha_negative: float = Field(0.30, ge=0, le=1, allow_inf_nan=False)
    beta_description: float = Field(0.20, ge=0, le=1, allow_inf_nan=False)

    @classmethod
    def from_env(cls):
        try:
            return cls(
                **{
                    name: os.environ["RAGDBMAN_KC_" + name.upper()]
                    for name in cls.model_fields
                    if "RAGDBMAN_KC_" + name.upper() in os.environ
                }
            )
        except ValidationError as exc:
            raise RagError("CONFIG_INVALID", f"Invalid Knowledge Cards environment: {exc}") from exc


class CardLoader(yaml.SafeLoader):
    """No unsafe constructors, aliases or silently overwritten mapping keys."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not supported in cards")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            # Deep construction is required here because the duplicate-key guard
            # replaces SafeLoader's deferred mapping constructor.
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str) or key in result:
                raise ValueError("Mapping keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=True)
        return result


class CardDumper(yaml.SafeDumper):
    pass


def _string(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


CardDumper.add_representer(str, _string)


def initialize_schema(conn):
    conn.executescript(files(__package__).joinpath("kc_schema.sql").read_text(encoding="utf-8"))


def parse(raw):
    try:
        payload = yaml.load(raw, Loader=CardLoader)
        if not isinstance(payload, dict) or not REQUIRED.issubset(payload):
            return None
        # Validate, but retain the original mapping: optional absent keys stay absent.
        KnowledgeCard.model_validate(payload)
        return payload
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
        raise RagError("KNOWLEDGE_CARD_INVALID", f"Invalid card YAML: {exc}") from exc


def read_card(path):
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise RagError("KNOWLEDGE_CARD_INVALID", "Card must be UTF-8 YAML") from exc
    return raw, parse(raw)


def dump_cards(cards):
    clean = [{key: value for key, value in card.items() if key != "id"} for card in cards]
    return (
        yaml.dump_all(clean, Dumper=CardDumper, sort_keys=False, allow_unicode=True, explicit_start=True)
        if clean
        else EMPTY_RESULT
    )


def fields(card):
    result = {"description": card["description"]}
    for name, field in (("positive", "positive_text"), ("negative", "negative_text")):
        if card.get(field, "").strip():
            result[name] = card[field]
    if any(code.strip() for code in card.get("codes", [])):
        result["code"] = "\n\n".join(card["codes"])
    return result


def validate_vectors(vectors, count, dimensions):
    if len(vectors) != count or any(
        len(vector) != dimensions
        or not all(math.isfinite(n) and abs(n) <= 3.4e38 for n in vector)
        or not any(abs(n) >= 1e-30 for n in vector)
        for vector in vectors
    ):
        raise RagError(
            "VECTOR_SCHEMA_MISMATCH", "Card embeddings must be finite, nonzero and match dimensions"
        )


def persist(
    path, source_id, source_path, root_id, digest, stat, raw, card, vectors, stop, connection_factory=None
):
    def check():
        if stop.is_set():
            raise RagError("JOB_CANCELLED", "Card index write cancelled")

    check()
    with (
        connection_factory() if connection_factory else closing(db.connect(path)) as conn,
        db.transaction(conn),
    ):
        if card is not None:
            duplicate = conn.execute("SELECT source_id FROM kc_cards WHERE id=?", (card["id"],)).fetchone()
            if duplicate and duplicate[0] != source_id:
                raise RagError(
                    "KNOWLEDGE_CARD_DUPLICATE", f"Card ID already belongs to another file: {card['id']}"
                )
        db.delete_chunks(conn, source_id)
        if card is None:
            conn.execute(
                "UPDATE sources SET status='unsupported',status_detail=?,updated_at=? WHERE id=?",
                ("YAML does not contain all required card keys", db.now(), source_id),
            )
            check()
            return
        db.insert(
            conn,
            "kc_cards",
            dict(
                id=card["id"],
                source_id=source_id,
                source_path=str(source_path),
                **{
                    key: card.get(key, "")
                    for key in (
                        "category",
                        "subcategory",
                        "title",
                        "description",
                        "positive_text",
                        "negative_text",
                    )
                },
                confidence=card["confidence"],
                raw_yaml=raw,
                updated_at=db.now(),
            ),
        )
        conn.execute(
            "INSERT INTO kc_fts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [card["id"]]
            + [
                card.get(k, "")
                for k in ("title", "category", "subcategory", "description", "positive_text", "negative_text")
            ]
            + ["\n".join(card.get(k, [])) for k in ("method_texts", "inputs", "outputs", "codes")],
        )
        for field, vector in zip(fields(card), vectors, strict=True):
            check()
            conn.execute(
                "INSERT INTO kc_embeddings(card_id,field_type,embedding) VALUES (?,?,?)",
                (card["id"], field, sqlite_vec.serialize_float32(vector)),
            )
        stamp = db.now()
        conn.execute(
            """UPDATE sources SET status='indexed',status_detail=NULL,content_hash_sha256=?,
            extraction_hash=?,size_bytes=?,root_id=COALESCE(?,root_id),markdown_path=NULL,
            indexed_at=?,updated_at=? WHERE id=?""",
            (digest, digest, stat.st_size, root_id, stamp, stamp, source_id),
        )
        db.insert(
            conn,
            "source_versions",
            dict(
                id=db.uid(),
                source_id=source_id,
                content_hash_sha256=digest,
                indexed_at=stamp,
                created_at=stamp,
            ),
        )
        db.audit(conn, "index_knowledge_card", source_id=source_id)
        check()


def retrieve(path, req, vector, settings, minimum, limit, rrf_k, connection_factory=None):
    """Confidence threshold per channel; hybrid fuses surviving ranks, not raw scores."""
    with connection_factory() if connection_factory else closing(db.connect(path)) as conn:
        # One snapshot prevents a concurrent card replacement mixing metadata and vectors.
        conn.execute("BEGIN")
        cards = {
            r["id"]: dict(r)
            for r in conn.execute(
                """SELECT c.* FROM kc_cards c JOIN sources s ON s.id=c.source_id
            WHERE s.status='indexed' AND s.deleted_at IS NULL"""
            )
        }
        semantic, lexical = {}, {}
        if vector is not None:
            sims = {}
            for row in conn.execute(
                "SELECT card_id,field_type,1-vec_distance_cosine(embedding,?) AS similarity FROM kc_embeddings",
                (sqlite_vec.serialize_float32(vector),),
            ):
                sims.setdefault(row["card_id"], {})[row["field_type"]] = row["similarity"]
            for card_id, card in cards.items():
                parts = sims.get(card_id, {})
                if parts.get("description") is None:
                    continue
                raw = parts["description"]
                if req.query_type == "expert" and all(
                    parts.get(k) is not None for k in ("positive", "negative")
                ):
                    raw = (
                        parts["positive"]
                        - settings.alpha_negative * parts["negative"]
                        + settings.beta_description * raw
                    )
                score = raw * card["confidence"]
                if math.isfinite(score) and score >= minimum:
                    semantic[card_id] = score
        if req.mode != "vector":
            terms = re.findall(r"\w+", req.query, flags=re.UNICODE)
            if terms:
                match = " OR ".join('"' + term + '"' for term in terms)
                matches = [
                    (r[0], max(0, -r[1]))
                    for r in conn.execute(
                        """SELECT card_id,bm25(kc_fts) FROM kc_fts
                    WHERE kc_fts MATCH ? AND card_id IN (
                        SELECT c.id FROM kc_cards c JOIN sources s ON s.id=c.source_id
                        WHERE s.status='indexed' AND s.deleted_at IS NULL)""",
                        (match,),
                    )
                ]
                strongest = max((strength for _, strength in matches), default=0)
                for card_id, strength in matches:
                    score = (strength / strongest if strongest else 0) * cards[card_id]["confidence"]
                    if score >= minimum:
                        lexical[card_id] = score
        ranks = {}
        for channel in (semantic, lexical):
            for rank, card_id in enumerate(sorted(channel, key=lambda k: (-channel[k], k)), 1):
                ranks[card_id] = ranks.get(card_id, 0) + 1 / (rrf_k + rank)
        scores = {k: max(semantic.get(k, -math.inf), lexical.get(k, -math.inf)) for k in ranks}
        ordered = sorted(
            ranks, key=lambda k: (-(ranks[k] if req.mode == "hybrid" else scores[k]), -scores[k], k)
        )[:limit]
        return [
            dict(
                card=parse(cards[k]["raw_yaml"]),
                score=scores[k],
                rank_score=ranks[k],
                vector_score=semantic.get(k),
                keyword_score=lexical.get(k),
                source_id=cards[k]["source_id"],
                source_path=cards[k]["source_path"],
            )
            for k in ordered
        ]
