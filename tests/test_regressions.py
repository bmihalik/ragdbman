# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import asyncio
import logging
import sys
from pathlib import Path

import httpx
import pytest
from tokenizers import Tokenizer as HFTokenizer
from tokenizers.models import WordLevel

from ragdbman import db
from ragdbman.chunking import Tokenizer, chunk_document, fetch_tokenizer
from ragdbman.diagnostics import DependencySummary, dependency_counts, is_quiet_target
from ragdbman.errors import RagError
from ragdbman.extract import extract_direct
from ragdbman.extract.pdf import relocate_images
from ragdbman.extract.process import detect_shebang, run
from ragdbman.extract.text import markdown, render_markdown, source_code
from ragdbman.models import Block, Document


def test_adjacent_repeated_headers_deduplicated():
    doc = Document([Block("Running header"), Block("Running header"), Block("Body text")], "pdf")
    chunks = chunk_document(doc, Tokenizer(allow_approximate=True), 200, 10)
    assert sum(c.text.count("Running header") for c in chunks) == 1
    assert all(doc.full_text[c.char_start : c.char_end] == c.text for c in chunks)


def test_markup_roundtrip_sections():
    doc = markdown("# Chapter\n\nText\n\n## Section\n\nMore")
    result = markdown(render_markdown(doc))
    assert result.blocks[-1].section_path == "Chapter > Section"


def test_source_fallback_paragraphs():
    doc = source_code("SELECT a\nFROM table;\n\nSELECT b;", Path("query.sql"))
    assert len(doc.blocks) == 2
    assert doc.blocks[0].line_start == 1 and doc.blocks[0].line_end == 2
    assert doc.blocks[1].line_start == 4


@pytest.mark.parametrize(
    "filename,code,starts",
    [
        (
            "module.rs",
            'use std::fmt;\n\nfn one() {\n    println!("one");\n}\n\nfn two(x: i32) -> i32 {\n    x + 1\n}\n',
            [3, 7],
        ),
        (
            "module.py",
            "import os\n\ndef one():\n    return 1\n\n\ndef two(x):\n    if x:\n        return x\n    return 0\n",
            [3, 7],
        ),
    ],
)
def test_function_boundaries_and_lines(filename, code, starts):
    doc = source_code(code, Path(filename))
    functions = [block for block in doc.blocks if block.heading]
    assert [block.heading for block in functions] == ["one", "two"]
    assert [block.line_start for block in functions] == starts
    assert functions[0].line_end < functions[1].line_start
    assert functions[-1].line_end == len(code.splitlines())


async def test_legacy_encoding_warning(cfg, source_dir):
    path = source_dir / "a.py"
    path.write_bytes(b"# comment \x93quoted\x94\nx=1")
    doc, _ = await extract_direct(path, cfg)
    assert doc.warnings and doc.full_text


async def test_fetch_tokenizer_success_atomic_failures(tmp_path):
    path = tmp_path / "cache" / "tokenizer.json"
    valid = HFTokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]")).to_str()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=valid))
    await fetch_tokenizer("http://local", "org/model", "main", path, transport)
    assert path.read_text() == valid
    for status, text in [(404, "missing"), (200, "<html>not JSON</html>")]:
        with pytest.raises(RagError):
            await fetch_tokenizer(
                "http://local",
                "org/model",
                "main",
                path,
                httpx.MockTransport(lambda r, status=status, text=text: httpx.Response(status, text=text)),
            )
        assert path.read_text() == valid
    assert not list(path.parent.glob(".write-*"))
    with pytest.raises(RagError, match="org/repo"):
        await fetch_tokenizer("http://must-not-be-contacted", "bge-m3:567m", "main", path)


def test_fresh_database_has_complete_schema(tmp_path):
    conn = db.connect(tmp_path / "fresh.sqlite")
    db.initialize_schema(conn)
    db.initialize_schema(conn)
    assert {"line_start", "line_end", "percent_position"} <= {
        r["name"] for r in conn.execute("PRAGMA table_info(chunks)")
    }
    assert "kind" in {r["name"] for r in conn.execute("PRAGMA table_info(collection_meta)")}
    assert "markdown_path" in {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    fts_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='chunks_fts'").fetchone()[0]
    assert "content=" not in fts_sql.replace(" ", "").lower()
    conn.close()


def test_image_nested_empty_alt_missing_and_external(tmp_path):
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "i.png").write_bytes(b"image")
    raw = "![](nested/i.png) ![missing](missing.png) ![url](https://example.com/x.png)"
    result = relocate_images(raw, root, tmp_path / "images")
    assert "![](images/" in result
    assert "![missing](missing.png)" in result
    assert "![url](https://example.com/x.png)" in result


def test_shebang_detection(tmp_path):
    p = tmp_path / "wrapper"
    p.write_text("#!/bin/sh\nexec something")
    assert detect_shebang(p) == "#!/bin/sh"
    p.write_bytes(b"\x00binary")
    assert detect_shebang(p) is None
    assert detect_shebang(tmp_path / "missing") is None


async def test_subprocess_failure_both_streams_and_signal():
    with pytest.raises(RagError) as caught:
        await run(sys.executable, ["-c", "import sys;print('OUT');print('ERR',file=sys.stderr);sys.exit(2)"])
    assert "OUT" in str(caught.value) and "ERR" in str(caught.value)
    with pytest.raises(RagError, match="no output"):
        await run(sys.executable, ["-c", "raise SystemExit(1)"])
    with pytest.raises(RagError, match="signal"):
        await run(sys.executable, ["-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"])


def test_dependency_log_summary():
    assert is_quiet_target("pypdf") and is_quiet_target("pypdf.reader")
    assert not is_quiet_target("pypdfx") and not is_quiet_target("ragdbman.engine")
    filt = DependencySummary()
    with dependency_counts() as counts:
        assert not filt.filter(logging.LogRecord("pypdf", logging.WARNING, "", 0, "w", (), None))
        assert not filt.filter(logging.LogRecord("pypdf.reader", logging.ERROR, "", 0, "e", (), None))
        assert filt.filter(logging.LogRecord("ragdbman", logging.ERROR, "", 0, "e", (), None))
    assert counts == [1, 1]
    with dependency_counts() as counts:
        assert counts == [0, 0]


async def test_dependency_counts_isolated():
    async def task(n):
        with dependency_counts() as counts:
            for _ in range(n):
                DependencySummary().filter(logging.LogRecord("pypdf", logging.WARNING, "", 0, "w", (), None))
                await asyncio.sleep(0)
            return counts[:]

    assert await asyncio.gather(task(2), task(3)) == [[2, 0], [3, 0]]


async def test_external_tools_do_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "do-not-leak")
    output = await run(sys.executable, ["-c", "import os;print(os.getenv('RAGDBMAN_AUTH_TOKEN','absent'))"])
    assert output.strip() == "absent"


@pytest.mark.parametrize("backend", ["whisper_cpp", "faster_whisper", "external_command"])
async def test_malformed_whisper_json(tmp_path, monkeypatch, backend):
    from ragdbman.config import MediaConfig
    from ragdbman.extract import media

    async def invalid_output(command, args, timeout, cwd):
        (cwd / "audio.json").write_text("not json")
        return "not json"

    monkeypatch.setattr(media, "run", invalid_output)
    with pytest.raises(RagError, match="Invalid Whisper JSON"):
        await media.transcribe(
            tmp_path / "audio.mp3", MediaConfig(whisper_command="fake", whisper_backend=backend)
        )


@pytest.mark.parametrize("data", [[], {"segments": None}, {"segments": [0]}, {"segments": [{"text": 3}]}])
def test_bad_transcript_structure(data):
    from ragdbman.extract.media import segments

    with pytest.raises(RagError, match="Whisper"):
        segments(data, "external_command")


async def test_image_and_scanned_pdf_ocr_without_sidecars(tmp_path, cfg):
    pymupdf = pytest.importorskip("pymupdf", reason="Explicit optional PDF OCR backend")

    from ragdbman.extract import extract
    from ragdbman.extract.media import ocr

    tool = tmp_path / "tesseract"
    tool.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        "assert sys.argv[2] == 'stdout'\n"
        "assert Path(sys.argv[1]).is_file()\nprint('Scanned document text')\n"
    )
    tool.chmod(0o755)
    cfg.media.tesseract_path = str(tool)
    cfg.media.pdf_backend = "pymupdf"
    image = tmp_path / "image.png"
    image.write_bytes(b"test image")
    assert "Scanned" in await ocr(image, cfg.media)
    doc, _ = await extract_direct(image, cfg)
    assert doc.extractor_name == "image_ocr"
    pdf_path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(pdf_path)
    doc, markdown_path = await extract(pdf_path, cfg, "source_code")
    assert "Scanned document text" in doc.full_text and doc.blocks[0].page == 1
    assert markdown_path is None
    assert not (tmp_path / ".ragdbman").exists()


async def test_real_logging_pipeline_in_subprocess():
    output = await run(
        sys.executable,
        [
            "-c",
            (
                "import logging; from ragdbman.diagnostics import configure_logging, dependency_counts;"
                "configure_logging('debug');\n"
                "with dependency_counts() as counts:\n"
                " logging.getLogger('pypdf.reader').warning('counted warning')\n"
                " print(counts, logging.getLogger().level)\n"
            ),
        ],
    )
    assert "[1, 0] 10" in output


async def test_unicode_auth_and_malformed_host(engine, monkeypatch):
    import base64

    from ragdbman.web import create_app

    engine.config.server.web_auth_mode = "password"
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "tükör")
    auth = base64.b64encode("user:tükör".encode()).decode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(engine, False)), base_url="http://localhost"
    ) as client:
        assert (
            await client.get("/api/collections", headers={"Authorization": f"Basic {auth}"})
        ).status_code == 200
        assert (await client.get("/api/collections", headers={"Host": "["})).status_code == 403
