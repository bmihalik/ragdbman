# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Public request types and internal extraction/chunking records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateCollection(Request):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    description: str | None = None
    source_roots: list[str] = Field(default_factory=list)
    kind: Literal["general", "source_code", "knowledge_cards"] = "general"
    embedding_model: str | None = None
    chunk_size_tokens: int | None = Field(None, ge=1)
    chunk_overlap_tokens: int | None = Field(None, ge=0)


class NumericFilter(Request):
    field: str
    op: Literal[
        "equal",
        "not_equal",
        "less_than",
        "less_than_or_equal",
        "greater_than",
        "greater_than_or_equal",
        "between",
        "exists",
    ]
    value: float | str | None = None
    from_: float | str | None = Field(None, alias="from")
    to: float | str | None = None
    currency: str | None = None

    @model_validator(mode="after")
    def operands(self):
        if self.op == "between" and (self.from_ is None or self.to is None):
            raise ValueError("between requires from and to")
        if self.op not in {"between", "exists"} and self.value is None:
            raise ValueError(f"{self.op} requires value")
        return self


class SearchFilters(Request):
    source_extensions: list[str] = Field(default_factory=list)
    numeric: list[NumericFilter] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    path_prefix: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class SearchRequest(Request):
    include_graph_context: bool | None = None
    collection: str
    query: str
    mode: Literal["vector", "keyword", "hybrid", "structured"] = "hybrid"
    top_k: int | None = Field(None, ge=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    include_text: bool = True
    include_links: bool = True


class MultiSearchRequest(Request):
    include_graph_context: bool | None = None
    collections: list[str]
    query: str
    mode: Literal["vector", "keyword", "hybrid", "structured"] = "hybrid"
    top_k: int | None = Field(None, ge=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    include_text: bool = True
    include_links: bool = True


class KnowledgeCard(BaseModel):
    """Validate known fields without discarding domain-specific additions."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    subcategory: str = ""
    positive_text: str = ""
    negative_text: str = ""
    method_texts: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    costs: dict = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list)
    source: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonblank(self):
        for field_name in ("id", "category", "title", "description"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        return self


class KnowledgeCardSearchRequest(Request):
    collection: str
    query: str = Field(min_length=1)
    query_type: Literal["general", "expert"] = "expert"
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    top_k: int | None = Field(None, ge=1, strict=True)
    minimum_similarity: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def nonblank_query(self):
        if not self.query.strip():
            raise ValueError("query must not be blank")
        return self


@dataclass
class Block:
    text: str
    is_heading: bool = False
    heading: str | None = None
    section_path: str | None = None
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    atomic: bool = False


@dataclass
class Document:
    blocks: list[Block]
    extractor_name: str
    title: str | None = None
    language: str | None = None
    page_count: int | None = None
    duration_seconds: float | None = None
    extractor_version: str = "python-1"
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


@dataclass
class Chunk:
    chunk_index: int
    text: str
    normalized_text: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    token_count: int
    page_start: int | None = None
    page_end: int | None = None
    slide_start: int | None = None
    slide_end: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    percent_position: float | None = None
    section_path: str | None = None
    heading: str | None = None
