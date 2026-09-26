# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Extractor dispatch and collection-aware Markdown materialization."""

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from ..config import GlobalConfig
from ..errors import RagError
from ..models import Block, Document
from . import office
from .media import AUDIO_VIDEO, IMAGES, LEGACY, legacy, ocr, transcribe
from .pdf import extract_pdf
from .sniff import text_content
from .text import (
    CODE_EXTENSIONS,
    TEXT_EXTENSIONS,
    decode,
    delimited,
    html,
    markdown,
    plain,
    render_markdown,
    source_code,
)

SUPPORTED = (
    TEXT_EXTENSIONS
    | CODE_EXTENSIONS
    | AUDIO_VIDEO
    | IMAGES
    | set(LEGACY)
    | {
        "md",
        "markdown",
        "html",
        "htm",
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "odt",
        "odp",
        "ods",
        "epub",
        "azw",
        "azw3",
        "mobi",
    }
)


def extension(path: Path) -> str:
    if path.name.lower() in {"makefile", "dockerfile", "cmakelists.txt"}:
        return "sh"
    return path.suffix.lower().lstrip(".")


async def extract_direct(
    path: Path, cfg: GlobalConfig, images_dir: Path | None = None
) -> tuple[Document, str | None]:
    ext = extension(path)
    try:
        if ext in {"md", "markdown"}:
            return markdown(decode(path.read_bytes()), path.stem), None
        if ext in CODE_EXTENSIONS:
            data = path.read_bytes()
            document = source_code(decode(data), path)
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                document.warnings.append("Non-UTF-8 source decoded using a legacy encoding fallback")
            return document, None
        if ext in {"csv", "tsv"}:
            return delimited(decode(path.read_bytes()), "\t" if ext == "tsv" else ","), None
        if ext in TEXT_EXTENSIONS:
            return plain(decode(path.read_bytes()), path.stem), None
        if ext in {"html", "htm"}:
            return html(decode(path.read_bytes())), None
        if ext == "pdf":
            return await extract_pdf(path, cfg.media, images_dir)
        if ext in {"docx", "pptx", "xlsx", "epub"}:
            return await asyncio.to_thread(getattr(office, ext), path), None
        if ext in {"odt", "odp", "ods"}:
            return await asyncio.to_thread(office.odf, path), None
        if ext in {"azw", "azw3", "mobi"}:
            return await asyncio.to_thread(office.azw3, path), None
        if ext in LEGACY:
            return await legacy(path, cfg.media), None
        if ext in AUDIO_VIDEO:
            return await transcribe(path, cfg.media), None
        if ext in IMAGES:
            return Document([Block(await ocr(path, cfg.media))], "image_ocr", title=path.stem), None
        raise RagError("UNSUPPORTED_MEDIA_TYPE", f"Unsupported extension: {ext or '(none)'}")
    except RagError:
        raise
    except Exception as exc:
        raise RagError("EXTRACTION_FAILED", f"{path.name}: {exc}") from exc


def sidecar_name(path: Path) -> str:
    stem = re.sub("[^a-z0-9_-]", "_", path.stem.lower()) or "file"
    # Full filename hash prevents a.py/a.pdf and punctuation/case collisions.
    suffix = hashlib.sha256(path.name.encode()).hexdigest()[:12]
    return f"{stem}-{suffix}.md"


def atomic_write(path: Path, text: str):
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)  # Replaces a symlink, never follows its target.
    finally:
        Path(temporary).unlink(missing_ok=True)


async def extract(path: Path, cfg: GlobalConfig, kind: str) -> tuple[Document, str | None]:
    if kind == "source_code" and extension(path) not in SUPPORTED:
        # Check the complete file again: a printable prefix cannot admit a binary tail.
        text = text_content(path.read_bytes())
        if text is None:
            raise RagError("UNSUPPORTED_MEDIA_TYPE", "Unrecognized file is not supported Unicode text")
        document = source_code(text, path)
        document.extractor_name = "source_code_text_sniff"
        document.warnings.append("Unrecognized filename indexed as detected Unicode source text")
        return document, None
    # This guard precedes ALL mkdir/image relocation, for all file types.
    if kind == "source_code" or not cfg.storage.markdown_sidecar_enabled:
        document, _ = await extract_direct(path, cfg)
        return document, None
    sidecar = path.parent / cfg.storage.markdown_sidecar_dir_name
    if sidecar.is_symlink():
        raise RagError("PATH_NOT_ALLOWED", "Sidecar directory must not be a symlink")
    sidecar.mkdir(exist_ok=True)
    target = sidecar / sidecar_name(path)
    ext = extension(path)
    if ext in {"md", "markdown", "txt", "log"}:
        target.unlink(missing_ok=True)
        try:
            target.symlink_to(path.resolve())
        except OSError:
            shutil.copy2(path, target)
        document, _ = await extract_direct(path, cfg)
        return document, str(path) if ext in {"md", "markdown"} else None
    images = sidecar / f"images-{target.stem}"
    if images.is_symlink():
        raise RagError("PATH_NOT_ALLOWED", "Sidecar images directory must not be a symlink")
    document, raw = await extract_direct(path, cfg, images)
    atomic_write(target, raw if raw is not None else render_markdown(document))
    reparsed = markdown(target.read_text(), document.title)
    reparsed.warnings = document.warnings
    reparsed.page_count, reparsed.duration_seconds = document.page_count, document.duration_seconds
    return reparsed, str(target)
