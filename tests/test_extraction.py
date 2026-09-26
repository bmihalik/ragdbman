# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import json
import sys
import zlib
from pathlib import Path
from zipfile import ZipFile

import pytest
from defusedxml.common import EntitiesForbidden

from ragdbman.config import MediaConfig
from ragdbman.errors import RagError
from ragdbman.extract import SUPPORTED, extract, extract_direct, sidecar_name
from ragdbman.extract.media import legacy, segments, transcribe
from ragdbman.extract.office import azw3, docx, epub, odf, pptx, xlsx
from ragdbman.extract.pdf import builtin, converted, extract_pdf, marker_pages, raw_pdf, relocate_images
from ragdbman.extract.process import run, scratch
from ragdbman.extract.text import decode, delimited, html, markdown, render_markdown, source_code
from ragdbman.models import Block, Document


def archive(path, members):
    with ZipFile(path, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return path


@pytest.fixture
def pdf_file(tmp_path):
    from conftest import text_pdf

    return text_pdf(tmp_path / "book.pdf", ["First page text", "Second page text"])


def test_decoding():
    assert decode("Árvíz".encode()) == "Árvíz"
    assert decode("Wide text".encode("utf-16")) == "Wide text"
    assert isinstance(decode(b"\x93hello\x94"), str)


def test_markdown_structure_and_fences():
    doc = markdown("# Chapter\n\nIntro\n\n## Section\n\n```python\nx = 1\n```\n\nText.")
    assert doc.blocks[-1].section_path == "Chapter > Section"
    assert any(b.atomic and "x = 1" in b.text for b in doc.blocks)


def test_render_markdown():
    doc = Document(
        [
            Block("Heading", is_heading=True, section_path="Chapter > Heading"),
            Block("text"),
            Block("```inner```", atomic=True),
        ],
        "test",
    )
    raw = render_markdown(doc)
    assert "## Heading" in raw
    assert "````\n```inner```\n````" in raw


def test_html_links_and_scripts():
    doc = html(
        "<html><title>Title</title><h1>A</h1><p>Hello <a href='/x'>world</a></p><script>bad()</script></html>"
    )
    assert doc.title == "Title"
    assert "[world](/x)" in doc.full_text and "bad()" not in doc.full_text


@pytest.mark.parametrize(
    "ext", ["rs", "py", "js", "ts", "go", "java", "cpp", "hh", "hxx", "m", "mm", "sql", "rb", "sh"]
)
def test_source_extensions(ext):
    assert ext in SUPPORTED
    doc = source_code("def first():\n    return 1\n\ndef second():\n    return 2", Path("x." + ext))
    assert doc.blocks[0].line_start == 1
    assert doc.blocks[-1].line_end == 5


def test_code_control_flow():
    doc = source_code("fn sample() {\n    if foo() {\n        return foo()\n    }\n}", Path("a.rs"))
    assert len(doc.blocks) == 1
    assert doc.blocks[0].heading == "sample"


def test_delimited_multiline_and_headers():
    doc = delimited('name,price\n"two\nlines",25\nsimple,99\n')
    assert len(doc.blocks) == 2
    assert "price: 25" in doc.blocks[0].text
    assert doc.blocks[0].atomic


@pytest.mark.parametrize(
    "ext,content,expected_path",
    [
        ("md", "# Native\n\nbody", True),
        ("markdown", "# Native", True),
        ("txt", "plain body", False),
        ("log", "plain log", False),
    ],
)
async def test_native_sidecar_links(cfg, source_dir, ext, content, expected_path):
    path = source_dir / f"native.{ext}"
    path.write_text(content)
    doc, markdown_path = await extract(path, cfg, "general")
    assert bool(markdown_path) == expected_path
    assert (source_dir / ".ragdbman" / sidecar_name(path)).is_file()
    assert path.read_text() == content
    assert doc.blocks


@pytest.mark.parametrize(
    "ext,content",
    [
        ("py", "def f():\n    pass"),
        ("txt", "plain"),
        ("md", "# Heading"),
        ("html", "<p>HTML body</p>"),
        ("csv", "name,price\nitem,25"),
    ],
)
async def test_source_code_collection_never_creates_sidecars(cfg, source_dir, ext, content):
    path = source_dir / f"file.{ext}"
    path.write_text(content)
    _, markdown_path = await extract(path, cfg, "source_code")
    assert markdown_path is None
    assert not (source_dir / ".ragdbman").exists()


async def test_general_code_intentionally_markdown(cfg, source_dir):
    path = source_dir / "a.py"
    path.write_text("def function():\n    return 42")
    document, md = await extract(path, cfg, "general")
    assert document.extractor_name == "markdown"
    assert md and Path(md).exists()
    assert all(b.line_start is None for b in document.blocks)


async def test_sidecar_disabled(cfg, source_dir):
    cfg.storage.markdown_sidecar_enabled = False
    path = source_dir / "a.html"
    path.write_text("<p>direct</p>")
    document, md = await extract(path, cfg, "general")
    assert md is None and document.extractor_name == "html"
    assert not (source_dir / ".ragdbman").exists()


async def test_collision_and_symlink_safety(cfg, source_dir):
    files = [source_dir / "A+.html", source_dir / "A?.html", source_dir / "a+.html"]
    assert len({sidecar_name(p) for p in files}) == 3
    for i, p in enumerate(files):
        p.write_text(f"<p>{i}</p>")
        await extract(p, cfg, "general")
    assert len(list((source_dir / ".ragdbman").glob("*.md"))) == 3
    target = source_dir / ".ragdbman" / sidecar_name(files[0])
    target.unlink()
    target.symlink_to(files[1])
    await extract(files[0], cfg, "general")
    assert files[1].read_text() == "<p>1</p>"


async def test_sidecar_directory_symlink_rejected(cfg, source_dir, tmp_path):
    (source_dir / ".ragdbman").symlink_to(tmp_path, target_is_directory=True)
    p = source_dir / "a.html"
    p.write_text("<p>x</p>")
    with pytest.raises(RagError, match="symlink"):
        await extract(p, cfg, "general")


def test_image_relocation(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "img.png").write_bytes(b"image")
    (tmp_path / "secret.png").write_bytes(b"private")
    (output / "escape.png").symlink_to(tmp_path / "secret.png")
    dest = tmp_path / "images"
    raw = "![local](img.png) ![web](https://x/img.png) ![bad](../secret.png) ![sym](escape.png)"
    result = relocate_images(raw, output, dest)
    assert "images/" in result
    assert len(list(dest.iterdir())) == 1
    assert "![bad](../secret.png)" in result and "![sym](escape.png)" in result


def test_docx_generated_fixture(tmp_path):
    path = archive(
        tmp_path / "d.docx",
        {
            "word/document.xml": """<w:document xmlns:w="urn:w"><w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Chapter</w:t></w:r></w:p>
    <w:p><w:r><w:t>Paragraph</w:t></w:r></w:p></w:body></w:document>"""
        },
    )
    doc = docx(path)
    assert doc.blocks[0].is_heading
    assert doc.blocks[1].section_path == "Chapter"


def test_pptx_numeric_slide_order(tmp_path):
    path = archive(
        tmp_path / "slides.pptx",
        {
            f"ppt/slides/slide{i}.xml": f'<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:p><a:r><a:t>Slide {i}</a:t></a:r></a:p></p:sld>'
            for i in [10, 2, 1]
        },
    )
    doc = pptx(path)
    assert [b.text for b in doc.blocks] == ["Slide 1", "Slide 2", "Slide 10"]
    assert doc.blocks[1].slide == 2


def test_xlsx_sheets_rows(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "sheet.xlsx"
    wb = Workbook()
    wb.active.title = "Measurements"
    wb.active.append(["name", "price"])
    wb.active.append(["item", 25])
    wb.save(path)
    doc = xlsx(path)
    assert doc.blocks[1].sheet == "Measurements"
    assert doc.blocks[1].line_start == 2
    assert "25" in doc.blocks[1].text


@pytest.mark.parametrize(
    "ext,body,expected",
    [
        ("odt", "<text:h>Title</text:h><text:p>Paragraph</text:p>", "Paragraph"),
        ("odp", "<draw:page><text:p>Slide text</text:p></draw:page>", "Slide text"),
        (
            "ods",
            '<table:table table:name="Sheet"><table:table-row><table:table-cell><text:p>25</text:p></table:table-cell></table:table-row></table:table>',
            "25",
        ),
    ],
)
def test_odf_formats(tmp_path, ext, body, expected):
    xml = f'<office:document xmlns:office="urn:o" xmlns:text="urn:t" xmlns:draw="urn:d" xmlns:table="urn:tb">{body}</office:document>'
    path = archive(tmp_path / ("document." + ext), {"content.xml": xml})
    assert expected in odf(path).full_text


def test_epub_spine_not_archive_order(tmp_path):
    path = archive(
        tmp_path / "book.epub",
        {
            "META-INF/container.xml": '<container><rootfile full-path="OEBPS/book.opf"/></container>',
            "OEBPS/book.opf": '<package><metadata><title>Book</title></metadata><manifest><item id="a" href="a.html"/><item id="b" href="b.html"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>',
            "OEBPS/a.html": "<h1>Second</h1><p>Later text</p>",
            "OEBPS/b.html": "<h1>First</h1><p>Earlier text</p>",
        },
    )
    doc = epub(path)
    assert doc.title == "Book"
    assert doc.blocks[0].text == "First"


def test_xml_entity_attack_rejected(tmp_path):
    path = archive(
        tmp_path / "bad.docx",
        {"word/document.xml": '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>'},
    )
    with pytest.raises(EntitiesForbidden):
        docx(path)


def test_malformed_kindle_fails_cleanly(tmp_path):
    path = tmp_path / "bad.azw3"
    path.write_bytes(b"not a palm database")
    with pytest.raises(RagError, match="EXTRACTION_FAILED"):
        azw3(path)


async def test_pdf_page_metadata(pdf_file):
    doc = await builtin(pdf_file, MediaConfig())
    assert doc.page_count == 2
    assert doc.blocks[0].page == 1 and doc.blocks[-1].page == 2


@pytest.mark.parametrize("password", ["", "secret"])
async def test_pdf_encryption(tmp_path, pdf_file, password):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(pdf_file))
    writer.encrypt(user_password=password, owner_password="owner", algorithm="AES-256")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    if password:
        with pytest.raises(RagError, match="password"):
            await builtin(path, MediaConfig())
    else:
        assert "First page" in (await builtin(path, MediaConfig())).full_text


@pytest.mark.parametrize("compressed", [False, True])
def test_raw_pdf_fallback(compressed):
    stream = b"BT /F1 12 Tf (Hello world) Tj [(With) -20 (kerning)] TJ ET"
    data = b"%PDF-1.4\n1 0 obj << "
    if compressed:
        data += b"/Filter /FlateDecode "
        stream = zlib.compress(stream)
    data += b">>\nstream\n" + stream + b"\nendstream\nendobj"
    text = raw_pdf(data)
    assert "Hello world" in text and "Withkerning" in text


async def test_broken_pdf_full_chain(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4\n1 0 obj << >>\nstream\nBT (Recovered text) Tj ET\nendstream\nendobj")
    doc = await builtin(p, MediaConfig())
    assert "Recovered text" in doc.full_text
    p.write_bytes(b"garbage")
    with pytest.raises(RagError, match="No extractable"):
        await builtin(p, MediaConfig())


def test_raw_no_text_and_garbage():
    assert raw_pdf(b"not a pdf") == ""
    assert raw_pdf(b"<< /Filter /FlateDecode >>\nstream\nbad\nendstream") == ""
    assert raw_pdf(b"<< >>\nstream\n0 0 m 10 10 l S\nendstream") == ""


def test_marker_pagination():
    raw = "0\n" + "-" * 48 + "\nFirst\n1\n" + "-" * 48 + "\nSecond"
    assert marker_pages(raw) == [(1, "First"), (2, "Second")]
    assert marker_pages("No markers") == [(1, "No markers")]
    assert marker_pages("42\nnot a marker") == [(1, "42\nnot a marker")]


@pytest.fixture
def fake_converter(tmp_path):
    script = tmp_path / "converter"
    script.write_text(
        f"#!{sys.executable}\n"
        + """
import sys
from pathlib import Path
args=sys.argv[1:]
out=Path(args[args.index("-o")+1] if "-o" in args else args[args.index("--output_dir")+1])
out=out/"nested";out.mkdir()
(out/"img.png").write_bytes(b"image")
(out/"result.md").write_text("# Converted\\n\\nContent ![img](img.png)\\n")
"""
    )
    script.chmod(0o755)
    return script


@pytest.mark.parametrize("backend", ["mineru", "marker"])
async def test_converter_actual_subprocess(tmp_path, pdf_file, fake_converter, backend):
    cfg = MediaConfig(**{backend + "_command": str(fake_converter)})
    doc, raw = await converted(pdf_file, cfg, backend, tmp_path / "images")
    assert doc.extractor_name == "pdf_" + backend
    assert "images/" in raw
    assert len(list((tmp_path / "images").iterdir())) == 1


async def test_converter_fallback(pdf_file, fake_converter):
    cfg = MediaConfig(mineru_command="/definitely/missing", marker_command=str(fake_converter))
    doc, _ = await extract_pdf(pdf_file, cfg)
    assert doc.extractor_name == "pdf_marker"
    assert doc.warnings
    cfg.marker_command = "/also/missing"
    doc, _ = await extract_pdf(pdf_file, cfg)
    assert "First page" in doc.full_text


async def test_converter_empty_output_reports_error(tmp_path, pdf_file):
    script = tmp_path / "empty"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    with pytest.raises(RagError, match="did not produce"):
        await converted(pdf_file, MediaConfig(mineru_command=str(script)), "mineru", None)


def test_transcript_schemas():
    blocks = segments(
        {
            "transcription": [
                {"text": "hello", "offsets": {"from": 0, "to": 1500}},
                {"text": "no offset"},
                {"text": " "},
            ]
        },
        "whisper_cpp",
    )
    assert len(blocks) == 1 and blocks[0].time_end_ms == 1500
    blocks = segments(
        {"segments": [{"text": "hello", "start": 0.1, "end": 1.6}, {"text": " "}]}, "faster_whisper"
    )
    assert len(blocks) == 1 and blocks[0].time_start_ms == 100
    assert blocks[0].time_end_ms == 1600
    with pytest.raises(RagError):
        segments({"segments": [{"text": "bad", "start": 2, "end": 1}]}, "external_command")


@pytest.mark.parametrize("backend", ["whisper_cpp", "faster_whisper", "external_command"])
async def test_transcriber_commands_end_to_end(tmp_path, backend):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_bytes(b'wav')\n"
    )
    ffmpeg.chmod(0o755)
    whisper = tmp_path / "whisper"
    whisper.write_text(
        f"#!{sys.executable}\n"
        + """
import sys,json
from pathlib import Path
a=sys.argv[1:]
if "--output-json" in a:
 result={"transcription":[{"text":"hello","offsets":{"from":0,"to":1500}}]}
 Path(a[a.index("--output-file")+1]+".json").write_text(json.dumps(result))
else:
 result={"segments":[{"text":"hello","start":0,"end":1.5}]}
 if "--output_dir" in a:
  (Path(a[a.index("--output_dir")+1])/"audio.json").write_text(json.dumps(result))
 else: print(json.dumps(result))
"""
    )
    whisper.chmod(0o755)
    source = tmp_path / "record.mp3"
    source.write_bytes(b"fake audio")
    cfg = MediaConfig(
        ffmpeg_path=str(ffmpeg),
        whisper_command=str(whisper),
        whisper_backend=backend,
        keep_extracted_audio=True,
    )
    doc = await transcribe(source, cfg)
    assert doc.duration_seconds == 1.5 and doc.full_text == "hello"
    assert source.with_suffix(".extracted.wav").exists()


async def test_subprocess_timeout_failure_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/example/runtime")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/example/bus")
    output = await run(
        sys.executable, ["-c", "import os,json;print(json.dumps(dict(os.environ)))"], cwd=tmp_path
    )
    env = json.loads(output)
    assert env["XDG_RUNTIME_DIR"] == "/example/runtime"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/example/bus"
    assert env["GIO_USE_VFS"] == "local"
    with pytest.raises(RagError, match="exited 7"):
        await run(sys.executable, ["-c", "raise SystemExit(7)"])
    with pytest.raises(RagError, match="timed out"):
        await run(sys.executable, ["-c", "import time;time.sleep(5)"], timeout=0.05)
    with pytest.raises(RagError, match="Cannot execute"):
        await run("/missing/program", [])


def test_scratch_cleanup(tmp_path):
    with scratch(str(tmp_path / "scratch")) as directory:
        p = Path(directory)
        assert p.parent == tmp_path / "scratch"
        assert p.exists()
    assert not p.exists()
    with scratch() as directory:
        assert Path(directory).is_dir()


async def test_optional_extractors_disabled(tmp_path):
    p = tmp_path / "file.doc"
    p.write_bytes(b"legacy")
    with pytest.raises(RagError, match="libreoffice_path"):
        await legacy(p, MediaConfig())
    with pytest.raises(RagError, match="whisper_command"):
        await transcribe(p, MediaConfig())


async def test_office_command_profile_and_shared_scratch(tmp_path):
    tool = tmp_path / "soffice"
    tool.write_text(
        f"#!{sys.executable}\n"
        + """
import sys,zipfile
from pathlib import Path
args=sys.argv[1:]
assert any(a.startswith("-env:UserInstallation=file://") for a in args)
source=Path(args[-1])
assert source.exists()
out=Path(args[args.index("--outdir")+1])
with zipfile.ZipFile(out/(source.stem+".docx"),"w") as z:
 z.writestr("word/document.xml",'<w:document xmlns:w="urn:w"><w:p><w:r><w:t>Legacy converted</w:t></w:r></w:p></w:document>')
"""
    )
    tool.chmod(0o755)
    source = tmp_path / "file.doc"
    source.write_bytes(b"source")
    result = await legacy(
        source, MediaConfig(libreoffice_path=str(tool), scratch_dir=str(tmp_path / "scratch"))
    )
    assert "Legacy converted" in result.full_text


async def test_unknown_extension(cfg, tmp_path):
    p = tmp_path / "a.unsupported"
    p.write_bytes(b"x")
    with pytest.raises(RagError, match="UNSUPPORTED_MEDIA_TYPE"):
        await extract_direct(p, cfg)
