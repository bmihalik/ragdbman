# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import codecs

import pytest
from conftest import finish

from ragdbman.extract import extract
from ragdbman.extract.sniff import SAMPLE_BYTES, is_text_file, text_content


@pytest.mark.parametrize(
    "name", ["Kconfig", "LICENSE", "sdkconfig.defaults", "config.board", "README", "script"]
)
async def test_unrecognized_source_names_index_as_text(engine, source_dir, name):
    await engine.create_collection(name="code", kind="source_code")
    path = source_dir / name
    path.write_text("# Build configuration\nCONFIG_BOARD=example\n# Copyright © 2026\n")
    result = await engine.add_file("code", str(path))
    assert result["chunks"] > 0 and not result["skipped"]
    source = engine.get_source("code", result["source_id"])
    assert source["status"] == "indexed" and source["markdown_path"] is None
    assert not list(source_dir.rglob(".ragdbman"))
    same = await engine.add_file("code", str(path))
    assert same["classification"] == "unchanged"


@pytest.mark.parametrize(
    "data",
    [
        b"\x7fELFbinary",
        b"MZexecutable",
        b"PK\x03\x04zip",
        b"\x89PNGimage",
        b"\0\1\2data",
        b"some text\0binary",
        b"text\x1bescape",
        b"%PDF-1.7 unrecognized.pdf",
        b"",
        b" \n\t",
        b"\xffgarbage",
    ],
)
def test_binary_and_empty_inputs_rejected(data):
    assert text_content(data) is None


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_supported_unicode_encodings(encoding):
    text = "# Text\nCONFIG_名=érték\n"
    assert text_content(text.encode(encoding)) == text


def test_probe_handles_split_multibyte_boundary(tmp_path):
    path = tmp_path / "LICENSE"
    path.write_bytes(b"a" * (SAMPLE_BYTES - 1) + "é\n".encode())
    assert is_text_file(path)
    assert text_content(path.read_bytes()).endswith("é\n")


async def test_binary_tail_is_skipped_not_embedded(engine, source_dir):
    await engine.create_collection(name="code", kind="source_code")
    path = source_dir / "misleading"
    path.write_bytes(b"A" * SAMPLE_BYTES + b"\0\1binary tail")
    assert is_text_file(path)  # The complete extraction validation must still reject it.
    before = len(engine.embedder.calls)
    result = await engine.add_file("code", str(path))
    assert result["skipped"]
    assert len(engine.embedder.calls) == before
    assert engine.get_source("code", result["source_id"])["status"] == "unsupported"
    assert engine.get_collection("code")["counts"]["chunks"] == 0


async def test_general_collection_policy_unchanged(engine, source_dir):
    await engine.create_collection(name="general")
    path = source_dir / "Kconfig"
    path.write_text("CONFIG_FEATURE=y\n")
    assert (await engine.add_file("general", str(path)))["skipped"]


async def test_rescan_retries_previously_skipped_sources(engine, source_dir):
    await engine.create_collection(name="code", kind="source_code")
    path = source_dir / "LICENSE"
    path.write_bytes(b"\0binary")
    first = await finish(engine, "code", engine.start_scan("code", str(source_dir)))
    assert first["progress"]["skipped"] == 1
    path.write_text("Permission is hereby granted.\n")
    second = await finish(engine, "code", engine.start_scan("code", str(source_dir)))
    assert second["progress"]["completed"] == 1
    assert second["progress"]["skipped"] == 0


async def test_sniffed_file_keeps_line_provenance(cfg, tmp_path):
    path = tmp_path / "sdkconfig.defaults"
    path.write_bytes(codecs.BOM_UTF16_LE + "CONFIG_A=y\nCONFIG_B=n\n".encode("utf-16-le"))
    doc, sidecar = await extract(path, cfg, "source_code")
    assert doc.extractor_name == "source_code_text_sniff"
    assert doc.blocks[0].line_start == 1
    assert sidecar is None


async def test_sniffed_long_lines_use_code_chunking(cfg, tmp_path):
    from ragdbman.chunking import Tokenizer, chunk_document

    path = tmp_path / "sdkconfig.defaults"
    long_line = "CONFIG_FLAGS=" + " ".join(["feature"] * 100)
    path.write_text(long_line + "\nCONFIG_OTHER=y\n")
    doc, _ = await extract(path, cfg, "source_code")
    chunks = chunk_document(doc, Tokenizer(allow_approximate=True), 20, 0)
    assert chunks[0].text == long_line
    assert chunks[0].line_start == chunks[0].line_end == 1
    assert chunks[1].line_start == chunks[1].line_end == 2
