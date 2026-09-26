# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Exact/opt-in approximate tokenization and structure-preserving chunking.

Offsets are Unicode character offsets into Document.full_text (not UTF-8 bytes).
Code chunks never split a physical line, even if that line exceeds the budget.
Atomic table/transcript blocks may also exceed the budget by design.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from tokenizers import Tokenizer as HFTokenizer

from .errors import RagError
from .models import Block, Chunk, Document


class Tokenizer:
    def __init__(self, path: Path | None = None, allow_approximate: bool = False):
        self.backend = None
        if path and path.is_file():
            try:
                self.backend = HFTokenizer.from_file(str(path))
            except Exception as exc:
                raise RagError("CONFIG_INVALID", f"Invalid tokenizer {path}: {exc}") from exc
        elif not allow_approximate:
            raise RagError(
                "CONFIG_INVALID",
                "Exact tokenizer missing. Run ragdbman fetch-tokenizer or explicitly "
                "set defaults.allow_approximate_tokenizer=true",
            )
        self.mode = "exact" if self.backend else "approximate"

    def count(self, text: str) -> int:
        return (
            len(self.backend.encode(text, add_special_tokens=False).ids)
            if self.backend
            else math.ceil(len(text) / 4)
        )

    def boundaries(self, text: str) -> list[tuple[int, int]]:
        if self.backend:
            return [(a, b) for a, b in self.backend.encode(text, add_special_tokens=False).offsets if b > a]
        return [(i, min(i + 4, len(text))) for i in range(0, len(text), 4)]


def tokenizer_path(data_dir: str | Path, model: str) -> Path:
    if (
        not model
        or model.startswith(("/", "\\"))
        or any(p in {".", ".."} for p in model.replace("\\", "/").split("/"))
    ):
        raise RagError("CONFIG_INVALID", "Unsafe embedding model name")
    return Path(data_dir).expanduser() / "tokenizer" / f"{model}.json"


async def fetch_tokenizer(
    hub_base_url: str,
    hf_repo: str,
    revision: str,
    dest: Path,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    from .extract import atomic_write

    if ":" in hf_repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", hf_repo) or ".." in hf_repo.split("/"):
        raise RagError("CONFIG_INVALID", "Pass a Hugging Face org/repo id, not an Ollama :tag")
    url = f"{hub_base_url.rstrip('/')}/{quote(hf_repo, safe='/')}/resolve/{quote(revision, safe='')}/tokenizer.json"
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True, transport=transport) as client:
            response = await client.get(url)
            response.raise_for_status()
        HFTokenizer.from_str(response.text)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(dest, response.text)
        return dest
    except Exception as exc:
        raise RagError("CONFIG_INVALID", f"Cannot fetch valid tokenizer.json: {exc}") from exc


@dataclass
class Unit:
    start: int
    end: int
    block: Block
    line: int | None = None


def chunk_document(doc: Document, tokenizer: Tokenizer, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise RagError("CONFIG_INVALID", "Chunk size must be positive and overlap must be smaller than size")
    full = doc.full_text
    code = doc.extractor_name == "source_code"
    groups: list[list[Unit]] = []
    units: list[Unit] = []
    cursor = 0
    previous_section = None
    previous_text = None
    for block in doc.blocks:
        normalized = " ".join(block.text.split())
        if not code and normalized and normalized == previous_text:
            # Flush across the skipped range so offsets still address the
            # original reconstructed document, not a silently shortened copy.
            if units:
                groups.append(units)
                units = []
            cursor += len(block.text) + 2
            continue
        previous_text = normalized
        if units and (block.is_heading or block.section_path != previous_section):
            groups.append(units)
            units = []
        previous_section = block.section_path
        if code:
            line_cursor = cursor
            for i, line in enumerate(block.text.splitlines(keepends=True)):
                length = len(line.rstrip("\r\n"))
                units.append(Unit(line_cursor, line_cursor + length, block, (block.line_start or 1) + i))
                line_cursor += len(line)
        elif block.atomic or tokenizer.count(block.text) <= size:
            units.append(Unit(cursor, cursor + len(block.text), block))
        else:
            # Prefer sentence cuts, then token windows for a long individual sentence.
            for match in re.finditer(r".+?(?:[.!?](?=\s|$)|\n|$)", block.text, re.S):
                text = match[0]
                if tokenizer.count(text) <= size:
                    units.append(Unit(cursor + match.start(), cursor + match.end(), block))
                else:
                    offsets = tokenizer.boundaries(text)
                    for start in range(0, len(offsets), size):
                        end = min(start + size, len(offsets))
                        a = 0 if start == 0 else offsets[start][0]
                        b = len(text) if end == len(offsets) else offsets[end][0]
                        units.append(Unit(cursor + match.start() + a, cursor + match.start() + b, block))
        cursor += len(block.text) + 2
    if units:
        groups.append(units)
    chunks: list[Chunk] = []
    for group in groups:
        start = 0
        while start < len(group):
            end = start + 1
            while end < len(group) and tokenizer.count(full[group[start].start : group[end].end]) <= size:
                end += 1
            selected = group[start:end]
            a, b = selected[0].start, selected[-1].end
            text = full[a:b]
            if text.strip():
                first, last = selected[0].block, selected[-1].block
                pages = [u.block.page for u in selected if u.block.page is not None]
                slides = [u.block.slide for u in selected if u.block.slide is not None]
                token_start = tokenizer.count(full[:a])
                count = tokenizer.count(text)
                chunks.append(
                    Chunk(
                        len(chunks),
                        text,
                        " ".join(text.split()),
                        a,
                        b,
                        token_start,
                        token_start + count,
                        count,
                        min(pages) if pages else None,
                        max(pages) if pages else None,
                        min(slides) if slides else None,
                        max(slides) if slides else None,
                        first.time_start_ms,
                        last.time_end_ms,
                        selected[0].line if code else first.line_start,
                        selected[-1].line if code else last.line_end,
                        100 * a / len(full) if full else 0,
                        first.section_path,
                        first.heading,
                    )
                )
            if end == len(group):
                break
            next_start = end
            if overlap:
                while (
                    next_start > start + 1
                    and tokenizer.count(full[group[next_start - 1].start : group[end - 1].end]) <= overlap
                ):
                    next_start -= 1
            start = max(start + 1, next_start)
    return chunks
