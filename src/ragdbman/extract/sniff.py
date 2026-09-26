# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Conservative, bounded text detection for unrecognized source-code filenames."""

import codecs

SAMPLE_BYTES = 65536
BINARY_SIGNATURES = (
    b"\x7fELF",
    b"MZ",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"\x89PNG",
    b"GIF87a",
    b"GIF89a",
    b"\xff\xd8\xff",
    b"%PDF-",
    b"SQLite format 3\x00",
    b"RIFF",
    b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa",
    b"\xcf\xfa\xed\xfe",
)


def text_content(data: bytes, complete: bool = True) -> str | None:
    """Strict Unicode only; reject binary signatures, NUL/control bytes and empty text."""
    if not data or data.startswith(BINARY_SIGNATURES):
        return None
    encoding = "utf-8-sig"
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    try:
        text = codecs.getincrementaldecoder(encoding)(errors="strict").decode(data, final=complete)
    except UnicodeError:
        return None
    if not text.strip() or any((ord(c) < 32 and c not in "\t\n\r\f") or 127 <= ord(c) <= 159 for c in text):
        return None
    return text


def is_text_file(path) -> bool:
    with path.open("rb") as stream:
        sample = stream.read(SAMPLE_BYTES)
    return text_content(sample, complete=len(sample) < SAMPLE_BYTES) is not None
