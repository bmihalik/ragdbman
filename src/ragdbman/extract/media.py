# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""OCR, legacy Office conversion, and three Whisper command contracts."""

import json
import shutil
from pathlib import Path

from ..config import MediaConfig
from ..errors import RagError
from ..models import Block, Document
from . import office
from .process import run, scratch

AUDIO_VIDEO = set("wav mp3 m4a flac ogg opus aac wma mp4 mkv mov avi webm mpeg mpg m4v".split())
IMAGES = set("png jpg jpeg tif tiff bmp webp gif".split())
LEGACY = {"doc": "docx", "ppt": "pptx", "xls": "xlsx", "rtf": "docx"}


def segments(data: dict, backend: str) -> list[Block]:
    if not isinstance(data, dict):
        raise RagError("TRANSCRIPTION_FAILED", "Whisper JSON must be an object")
    result = []
    records = data.get("transcription" if backend == "whisper_cpp" else "segments", [])
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise RagError("TRANSCRIPTION_FAILED", "Whisper segments must be an array of objects")
    for segment in records:
        if not isinstance(segment.get("text", ""), str):
            raise RagError("TRANSCRIPTION_FAILED", "Whisper segment text must be a string")
        text = segment.get("text", "").strip()
        if not text:
            continue
        if backend == "whisper_cpp":
            offsets = segment.get("offsets")
            if offsets is None:
                continue
            start, end = offsets["from"], offsets["to"]
        else:
            start, end = round(segment["start"] * 1000), round(segment["end"] * 1000)
        if start < 0 or end < start:
            raise RagError("TRANSCRIPTION_FAILED", "Invalid transcript timestamps")
        result.append(Block(text, time_start_ms=start, time_end_ms=end, atomic=True))
    return result


async def transcribe(path: Path, cfg: MediaConfig) -> Document:
    if not cfg.whisper_command:
        raise RagError("UNSUPPORTED_MEDIA_TYPE", "Set media.whisper_command to enable transcription")
    with scratch(cfg.scratch_dir) as directory:
        tmp = Path(directory)
        wav = tmp / "audio.wav"
        await run(
            cfg.ffmpeg_path,
            ["-y", "-i", str(path), "-ar", "16000", "-ac", "1", "-vn", str(wav)],
            cfg.subprocess_timeout_seconds,
            tmp,
        )
        lang = cfg.transcription_language
        if cfg.whisper_backend == "whisper_cpp":
            args = ["-f", str(wav), "--output-json", "--output-file", str(wav.with_suffix("")), "-l", lang]
            if cfg.whisper_model_path:
                args += ["-m", str(Path(cfg.whisper_model_path).expanduser())]
            await run(cfg.whisper_command, args, cfg.subprocess_timeout_seconds, tmp)
            raw = wav.with_suffix(".json").read_text()
        elif cfg.whisper_backend == "faster_whisper":
            args = [str(wav), "--output_format", "json", "--output_dir", str(tmp), "--language", lang]
            if cfg.whisper_model_path:
                args += ["--model", cfg.whisper_model_path]
            await run(cfg.whisper_command, args, cfg.subprocess_timeout_seconds, tmp)
            raw = wav.with_suffix(".json").read_text()
        else:
            raw = await run(cfg.whisper_command, [str(wav), lang], cfg.subprocess_timeout_seconds, tmp)
        try:
            blocks = segments(json.loads(raw), cfg.whisper_backend)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            raise RagError("TRANSCRIPTION_FAILED", f"Invalid Whisper JSON: {exc}") from exc
        if cfg.keep_extracted_audio:
            shutil.copy2(wav, path.with_suffix(".extracted.wav"))
    return Document(
        blocks,
        f"media_ffmpeg_{cfg.whisper_backend}",
        title=path.stem,
        language=lang,
        duration_seconds=max((b.time_end_ms for b in blocks), default=0) / 1000,
    )


async def ocr(path: Path, cfg: MediaConfig) -> str:
    if not cfg.tesseract_path:
        raise RagError("OCR_FAILED", "Set media.tesseract_path to enable OCR")
    return await run(cfg.tesseract_path, [str(path), "stdout"], cfg.subprocess_timeout_seconds)


async def legacy(path: Path, cfg: MediaConfig) -> Document:
    if not cfg.libreoffice_path:
        raise RagError(
            "UNSUPPORTED_MEDIA_TYPE", "Set media.libreoffice_path to enable legacy Office extraction"
        )
    with scratch(cfg.scratch_dir) as directory:
        tmp = Path(directory)
        # Copy into the same scratch tree, needed for containerized office installations.
        source = tmp / path.name
        shutil.copy2(path, source)
        dest = tmp / "out"
        dest.mkdir()
        suffix = LEGACY[path.suffix.lower().lstrip(".")]
        await run(
            cfg.libreoffice_path,
            [
                f"-env:UserInstallation={(tmp / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                suffix,
                "--outdir",
                str(dest),
                str(source),
            ],
            cfg.subprocess_timeout_seconds,
            tmp,
        )
        converted = dest / f"{path.stem}.{suffix}"
        if not converted.is_file():
            raise RagError("EXTRACTION_FAILED", "LibreOffice returned without producing the converted file")
        doc = getattr(office, suffix)(converted)
        doc.extractor_name = "legacy_office"
        return doc
