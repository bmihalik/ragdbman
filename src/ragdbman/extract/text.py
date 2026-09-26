# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Text, Markdown, HTML, and heuristic source-code structure."""

import csv
import io
import re
from pathlib import Path

from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from markdown_it import MarkdownIt

from ..models import Block, Document

TEXT_EXTENSIONS = set("txt csv tsv json yaml yml xml log ini cfg conf toml".split())
CODE_EXTENSIONS = set(
    "rs py pyi js jsx ts tsx mjs cjs go java kt kts c h cpp hpp hh hxx cc cxx cs php swift scala m mm "
    "rb sh bash zsh fish sql lua r R jl ex exs erl hrl hs clj cljs dart vue svelte "
    "pl pm ps1 bat cmd f f90 f95 asm s vb vbs groovy sc css scss sass less".lower().split()
)


def decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        guess = from_bytes(data).best()
        return str(guess) if guess else data.decode("cp1252", errors="replace")


def plain(text: str, title: str | None = None) -> Document:
    blocks = [
        Block(line, line_start=n, line_end=n) for n, line in enumerate(text.splitlines(), 1) if line.strip()
    ]
    return Document(blocks, "text", title=title)


def delimited(text: str, delimiter: str = ",") -> Document:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers = next(reader, [])
    blocks = []
    for n, row in enumerate(reader, 1):
        content = " | ".join(
            f"{headers[i] if i < len(headers) else f'col{i}'}: {value}" for i, value in enumerate(row)
        )
        if content.strip():
            blocks.append(Block(content, heading=f"row {n}", atomic=True))
    return Document(blocks, "delimited_text")


def markdown(text: str, title: str | None = None) -> Document:
    blocks, stack = [], []
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    heading_level = None
    for token in tokens:
        if token.type == "heading_open":
            heading_level = int(token.tag[1:])
        elif token.type == "inline" and token.content.strip():
            content = token.content.strip()
            is_heading = heading_level is not None
            if is_heading:
                stack = [(level, value) for level, value in stack if level < heading_level]
                stack.append((heading_level, content))
            blocks.append(
                Block(
                    content,
                    is_heading=is_heading,
                    heading=stack[-1][1] if stack else None,
                    section_path=" > ".join(t for _, t in stack) or None,
                )
            )
            heading_level = None
        elif token.type in {"fence", "code_block", "html_block"} and token.content.strip():
            blocks.append(
                Block(
                    token.content.rstrip(),
                    atomic=True,
                    heading=stack[-1][1] if stack else None,
                    section_path=" > ".join(t for _, t in stack) or None,
                )
            )
    return Document(
        blocks, "markdown", title=title or (blocks[0].text if blocks and blocks[0].is_heading else None)
    )


def html(text: str) -> Document:
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for bad in soup(["script", "style", "noscript", "head"]):
        bad.decompose()
    for a in soup.find_all("a", href=True):
        a.replace_with(f"[{a.get_text(' ', strip=True)}]({a['href']})")
    blocks, stack = [], []
    for node in soup.find_all(re.compile(r"^(h[1-6]|p|pre|li|tr)$")):
        if node.find_parent(["p", "pre", "li", "tr"]):
            continue
        text = node.get_text(" " if node.name != "pre" else "", strip=True)
        if not text:
            continue
        is_heading = node.name.startswith("h")
        if is_heading:
            level = int(node.name[1])
            stack = [(n, v) for n, v in stack if n < level] + [(level, text)]
        blocks.append(
            Block(
                text,
                is_heading=is_heading,
                heading=stack[-1][1] if stack else None,
                section_path=" > ".join(v for _, v in stack) or None,
                atomic=node.name in {"pre", "tr"},
            )
        )
    if not blocks:
        content = soup.get_text(" ", strip=True)
        if content:
            blocks.append(Block(content))
    return Document(blocks, "html", title=title)


SYMBOL = re.compile(
    r"^\s*(?:(?:pub(?:\([^)]*\))?|async|export|default|static|public|private|protected|final|abstract)\s+)*"
    r"(?:(?:def|class|fn|func|function|interface|struct|enum|trait|impl|module|namespace|"
    r"type|record|object|fun)\s+([^\s({:<]+)|"
    r"(?:[A-Za-z_][\w:<>,*\[\]]*\s+)+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:\{|$))"
)


def source_code(text: str, path: Path) -> Document:
    lines = text.splitlines()
    boundaries: list[tuple[int, str | None]] = [(0, None)]
    for i, line in enumerate(lines):
        if re.match(
            r"^\s*(?:}\s*)?(?:if|else|for|foreach|while|do|switch|match|try|catch|finally|return|throw)\b",
            line,
        ):
            continue
        match = SYMBOL.match(line)
        if match:
            name = next((g for g in match.groups() if g), line.strip())
            if i == boundaries[-1][0]:
                boundaries[-1] = (i, name)
            else:
                boundaries.append((i, name))
    blocks = []
    if len(boundaries) == 1 and boundaries[0][1] is None:
        # Unknown language shapes fall back to blank-line-delimited blocks.
        start = 0
        for i in range(len(lines) + 1):
            if i == len(lines) or not lines[i].strip():
                content = "\n".join(lines[start:i])
                if content.strip():
                    blocks.append(Block(content, line_start=start + 1, line_end=i, atomic=True))
                start = i + 1
        return Document(blocks, "source_code", title=path.name, language=path.suffix.lstrip("."))
    for n, (start, symbol) in enumerate(boundaries):
        end = boundaries[n + 1][0] if n + 1 < len(boundaries) else len(lines)
        content = "\n".join(lines[start:end])
        if content.strip():
            blocks.append(
                Block(
                    content,
                    heading=symbol,
                    section_path=symbol,
                    line_start=start + 1,
                    line_end=end,
                    atomic=True,
                )
            )
    return Document(blocks, "source_code", title=path.name, language=path.suffix.lstrip("."))


def render_markdown(doc: Document) -> str:
    parts = []
    for b in doc.blocks:
        if b.is_heading:
            depth = min(6, len((b.section_path or b.text).split(" > ")))
            parts.append("#" * depth + " " + b.text)
        elif b.atomic:
            fence = "`" * max(3, max((len(x) for x in re.findall(r"`+", b.text)), default=0) + 1)
            parts.append(f"{fence}\n{b.text}\n{fence}")
        else:
            parts.append(b.text)
    return "\n\n".join(parts) + "\n"
