# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Selectable PDF backends; PyMuPDF is imported only after explicit opt-in."""

import logging
import re
import shutil
import zlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..config import MediaConfig
from ..errors import RagError
from ..models import Block, Document
from .media import ocr
from .process import run, scratch
from .text import markdown

log = logging.getLogger(__name__)


def marker_pages(raw: str) -> list[tuple[int, str]]:
    """Accept the original integer + 48-dash markers and brace markers."""
    lines = raw.splitlines()
    pages, content, number = [], [], 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        original = line.isdigit() and i + 1 < len(lines) and lines[i + 1].strip() == "-" * 48
        brace = re.fullmatch(r"\{(\d+)\}-{3,}", line)
        if original or brace:
            if content:
                pages.append((number, "\n".join(content)))
            content = []
            number = int(line if original else brace[1]) + 1
            i += 2 if original else 1
        else:
            content.append(lines[i])
            i += 1
    if content:
        pages.append((number, "\n".join(content)))
    return pages


def relocate_images(text: str, source_dir: Path, dest_dir: Path) -> str:
    """Copy only images inside converter output; never follow escaping symlinks."""
    root = source_dir.resolve()

    def replace(match):
        target = match[2].strip("<>")
        if urlsplit(target).scheme or target.startswith("//"):
            return match[0]
        source = (source_dir / unquote(target)).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            return match[0]
        import hashlib

        name = hashlib.sha256(str(source.relative_to(root)).encode()).hexdigest()[:12] + "-" + source.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest_dir / name)
        return f"![{match[1]}]({dest_dir.name}/{name})"

    return re.sub(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)', replace, text)


async def converted(
    path: Path, cfg: MediaConfig, backend: str, images_dir: Path | None
) -> tuple[Document, str]:
    command = cfg.mineru_command if backend == "mineru" else cfg.marker_command
    if not command:
        raise RagError("CONFIG_INVALID", f"Set media.{backend}_command to use {backend}")
    with scratch(cfg.scratch_dir) as directory:
        output = Path(directory)
        if backend == "mineru":
            if cfg.mineru_cli == "parse":
                args = ["parse", str(path.resolve()), "--pages", "all", "-o", str(output / "document.md")]
            else:
                args = ["-p", str(path.resolve()), "-o", str(output)]
            args += cfg.mineru_extra_args
        else:
            args = [
                str(path.resolve()),
                "--output_dir",
                str(output),
                "--output_format",
                "markdown",
                "--paginate_output",
            ]
        await run(command, args, cfg.subprocess_timeout_seconds, output)
        candidates = sorted(
            p for p in output.rglob("*.md") if p.is_file() and p.resolve().is_relative_to(output)
        )
        if not candidates:
            raise RagError("EXTRACTION_FAILED", f"{backend} did not produce Markdown")
        result = next((p for p in candidates if p.stem == path.stem), candidates[0])
        raw = result.read_text()
        if images_dir:
            raw = relocate_images(raw, result.parent, images_dir)
        if not raw.strip():
            raise RagError("EXTRACTION_FAILED", f"{backend} produced empty Markdown")
        if backend == "marker":
            blocks = []
            pages = marker_pages(raw)
            for page, piece in pages:
                part = markdown(piece)
                for block in part.blocks:
                    block.page = page
                blocks.extend(part.blocks)
            doc = Document(blocks, "pdf_marker", title=path.stem, page_count=len(pages))
        else:
            doc = markdown(raw, path.stem)
            doc.extractor_name = "pdf_mineru"
        return doc, raw


def raw_pdf(data: bytes) -> str:
    """Best-effort xref-independent Flate/uncompressed text-showing operators."""
    recovered = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", data, re.S):
        stream = match[1]
        prefix = data[max(0, match.start() - 300) : match.start()]
        if b"FlateDecode" in prefix:
            try:
                stream = zlib.decompress(stream.strip(b"\r\n"))
            except zlib.error:
                continue
        elif b"/Filter" in prefix:
            continue
        # The pypdf content tokenizer handles nested parentheses, escapes and TJ arrays.
        from pypdf.generic import ContentStream, DecodedStreamObject

        try:
            obj = DecodedStreamObject()
            obj.set_data(stream)
            content = ContentStream(obj, None)
            for args, op in content.operations:
                if op in {b"Tj", b"'", b'"'} and args:
                    recovered.append(str(args[-1]))
                elif op == b"TJ" and args:
                    recovered.append("".join(str(x) for x in args[0] if isinstance(x, str)))
        except Exception:
            continue
    return "\n".join(recovered)


async def builtin(path: Path, cfg: MediaConfig) -> Document:
    """pypdf by default; optional PyMuPDF followed by pypdf only when selected."""
    warnings = []
    if cfg.pdf_backend == "pymupdf":
        try:
            return await pymupdf_document(path, cfg)
        except RagError as exc:
            if exc.code == "CONFIG_INVALID" or not cfg.pdf_fallback:
                raise
            warnings.append(str(exc))
    try:
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise RagError(
                "EXTRACTION_FAILED",
                "PDF requires a non-empty password; password-protected files are unsupported",
            )
        blocks = []
        for n, page in enumerate(reader.pages, 1):
            text = page.extract_text().strip()
            if text:
                blocks.append(Block(text, page=n))
            else:
                warnings.append(f"Page {n} contains no extractable text; pypdf does not render or OCR pages")
        if blocks:
            return Document(
                blocks, "pdf_pypdf", title=path.stem, page_count=len(reader.pages), warnings=warnings
            )
    except RagError:
        raise
    except Exception as exc:
        warnings.append(str(exc))
    if cfg.pdf_fallback:
        text = raw_pdf(path.read_bytes())
        if text.strip():
            return Document([Block(text)], "pdf_raw", title=path.stem, warnings=warnings)
    raise RagError(
        "EXTRACTION_FAILED",
        "No extractable PDF text. pypdf does not perform OCR; select MinerU or explicitly enable PyMuPDF with Tesseract for scanned PDFs",
        {"attempts": warnings},
    )


async def pymupdf_document(path: Path, cfg: MediaConfig) -> Document:
    """Optional AGPL/commercial backend. Never called by auto or pypdf mode."""
    try:
        import pymupdf
    except ImportError as exc:
        raise RagError(
            "CONFIG_INVALID",
            "PyMuPDF is optional: install ragdbman[pymupdf] (uv sync --extra pymupdf) after reviewing its license, or select media.pdf_backend='pypdf'",
        ) from exc
    warnings, blocks = [], []
    try:
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass and not pdf.authenticate(""):
                raise RagError("EXTRACTION_FAILED", "PDF requires a non-empty password")
            count = len(pdf)
            with scratch(cfg.scratch_dir) as directory:
                for n, page in enumerate(pdf, 1):
                    text = page.get_text(sort=True)
                    if not text.strip() and cfg.tesseract_path:
                        image = Path(directory) / f"page-{n}.png"
                        page.get_pixmap(dpi=200).save(image)
                        text = await ocr(image, cfg)
                    if text.strip():
                        blocks.append(Block(text.strip(), page=n))
                    else:
                        warnings.append(f"Page {n} contains no extractable text; OCR may be needed")
            if blocks:
                return Document(blocks, "pdf_pymupdf", title=path.stem, page_count=count, warnings=warnings)
    except RagError:
        raise
    except Exception as exc:
        raise RagError("EXTRACTION_FAILED", f"PyMuPDF extraction failed: {exc}") from exc
    raise RagError(
        "EXTRACTION_FAILED",
        "PyMuPDF found no extractable PDF text; enable OCR for scanned documents",
        {"attempts": warnings},
    )


async def extract_pdf(
    path: Path, cfg: MediaConfig, images_dir: Path | None = None
) -> tuple[Document, str | None]:
    warnings = []
    if cfg.pdf_backend in {"pypdf", "pymupdf"}:
        return await builtin(path, cfg), None
    backends = ["mineru", "marker"] if cfg.pdf_backend == "auto" else [cfg.pdf_backend]
    if cfg.pdf_backend != "auto" and not getattr(cfg, f"{cfg.pdf_backend}_command"):
        raise RagError("CONFIG_INVALID", f"Set media.{cfg.pdf_backend}_command to use {cfg.pdf_backend}")
    for name in backends:
        command = getattr(cfg, f"{name}_command")
        if command:
            try:
                doc, raw = await converted(path, cfg, name, images_dir)
                doc.warnings[:0] = warnings
                return doc, raw
            except (RagError, OSError, ValueError) as exc:
                if not cfg.pdf_fallback:
                    raise
                log.warning("%s conversion failed; trying next PDF backend: %s", name, exc)
                warnings.append(str(exc))
    try:
        doc = await builtin(path, cfg)
    except RagError as exc:
        if warnings:
            raise RagError(exc.code, str(exc), {"attempts": warnings + [str(exc)]}) from exc
        raise
    doc.warnings[:0] = warnings
    return doc, None
