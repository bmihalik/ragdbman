# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import builtins
import os
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import text_pdf
from pydantic import ValidationError

from ragdbman.config import GlobalConfig, MediaConfig
from ragdbman.errors import RagError
from ragdbman.extract import extract
from ragdbman.extract.pdf import extract_pdf


@pytest.fixture
def small_pdf(tmp_path):
    return text_pdf(tmp_path / "Scientific material.pdf", ["Scientific text", "Second page"])


def block_pymupdf(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"pymupdf", "fitz"} or name.startswith(("pymupdf.", "fitz.")):
            raise ImportError("PyMuPDF intentionally absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("backend", ["pypdf", "auto"])
async def test_permissive_pdf_never_imports_pymupdf(small_pdf, monkeypatch, backend):
    block_pymupdf(monkeypatch)
    doc, raw = await extract_pdf(small_pdf, MediaConfig(pdf_backend=backend))
    assert doc.extractor_name == "pdf_pypdf" and doc.page_count == 2
    assert [b.page for b in doc.blocks] == [1, 2]
    assert raw is None and "Scientific text" in doc.full_text


async def test_explicit_pypdf_ignores_external_commands(small_pdf, monkeypatch):
    from ragdbman.extract import pdf

    async def forbidden(*args, **kwargs):
        raise AssertionError("No external command should run in pypdf mode")

    monkeypatch.setattr(pdf, "converted", forbidden)
    block_pymupdf(monkeypatch)
    doc, _ = await extract_pdf(
        small_pdf,
        MediaConfig(pdf_backend="pypdf", mineru_command="/do/not/run", marker_command="/do/not/run"),
    )
    assert doc.extractor_name == "pdf_pypdf"


async def test_missing_optional_pymupdf_has_install_guidance(small_pdf, monkeypatch):
    block_pymupdf(monkeypatch)
    with pytest.raises(RagError, match=r"ragdbman\[pymupdf\]") as error:
        await extract_pdf(small_pdf, MediaConfig(pdf_backend="pymupdf"))
    assert error.value.code == "CONFIG_INVALID"


async def test_real_optional_pymupdf(small_pdf):
    pytest.importorskip("pymupdf")
    doc, _ = await extract_pdf(small_pdf, MediaConfig(pdf_backend="pymupdf"))
    assert doc.extractor_name == "pdf_pymupdf"
    assert doc.page_count == 2 and "Second page" in doc.full_text


async def test_pypdf_scanned_pdf_never_silently_loads_native_renderer(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "scan.pdf"
    writer.write(path)
    block_pymupdf(monkeypatch)
    with pytest.raises(RagError, match="pypdf does not perform OCR"):
        await extract_pdf(path, MediaConfig(pdf_backend="pypdf", tesseract_path="/do/not/run"))


@pytest.fixture
def fake_mineru(tmp_path):
    tool = tmp_path / "mineru"
    tool.write_text(
        f"#!{sys.executable}\n"
        + """
import sys
from pathlib import Path
a=sys.argv[1:]
if a[0] == "parse":
    assert a[2:4] == ["--pages", "all"]
    assert Path(a[1]).is_file()
    dest=Path(a[a.index("-o")+1])
else:
    assert Path(a[a.index("-p")+1]).is_file()
    dest=Path(a[a.index("-o")+1])/"paper"/"auto"/"paper.md"
assert a[-2:] == ["--scientific-option", "value with spaces;not a shell"]
dest.parent.mkdir(parents=True, exist_ok=True)
(dest.parent/"fig.png").write_bytes(b"test image")
dest.write_text("# Scientific conversion\\n\\nEquation $$E=mc^2$$\\n\\n![Figure](fig.png)")
"""
    )
    tool.chmod(0o755)
    return str(tool)


@pytest.mark.parametrize("interface", ["legacy", "parse"])
@pytest.mark.parametrize("kind", ["general", "source_code"])
async def test_mineru_external_conversion_and_sidecar_policy(small_pdf, fake_mineru, interface, kind):
    cfg = GlobalConfig(
        media={
            "pdf_backend": "mineru",
            "mineru_command": fake_mineru,
            "mineru_cli": interface,
            "mineru_extra_args": ["--scientific-option", "value with spaces;not a shell"],
            "pdf_fallback": False,
        }
    )
    doc, markdown_path = await extract(small_pdf, cfg, kind)
    assert "E=mc^2" in doc.full_text
    if kind == "general":
        assert markdown_path and Path(markdown_path).exists()
        assert list((small_pdf.parent / ".ragdbman").rglob("*.png"))
    else:
        assert markdown_path is None and not (small_pdf.parent / ".ragdbman").exists()
        assert doc.extractor_name == "pdf_mineru"


async def test_mineru_command_resolves_from_path(small_pdf, fake_mineru, monkeypatch):
    monkeypatch.setenv("PATH", str(Path(fake_mineru).parent) + os.pathsep + os.environ.get("PATH", ""))
    cfg = MediaConfig(
        pdf_backend="mineru",
        mineru_command="mineru",
        mineru_extra_args=["--scientific-option", "value with spaces;not a shell"],
        pdf_fallback=False,
    )
    doc, _ = await extract_pdf(small_pdf, cfg)
    assert doc.extractor_name == "pdf_mineru"
    assert "E=mc^2" in doc.full_text


async def test_mineru_fallback_is_explicit_and_can_be_disabled(small_pdf):
    cfg = MediaConfig(pdf_backend="mineru", mineru_command="/not-installed/mineru")
    doc, _ = await extract_pdf(small_pdf, cfg)
    assert doc.extractor_name == "pdf_pypdf"
    assert doc.warnings and "Cannot execute" in doc.warnings[0]
    cfg.pdf_fallback = False
    with pytest.raises(RagError, match="Cannot execute"):
        await extract_pdf(small_pdf, cfg)


@pytest.mark.parametrize("backend", ["mineru", "marker"])
async def test_selected_external_backend_requires_command(small_pdf, backend):
    with pytest.raises(RagError, match=f"media.{backend}_command"):
        await extract_pdf(small_pdf, MediaConfig(pdf_backend=backend))


@pytest.mark.parametrize(
    "data",
    [
        {"pdf_backend": "unknown"},
        {"mineru_cli": "unknown"},
        {"mineru_extra_args": "--shell-string"},
        {"mineru_extra_args": ["-p", "/somewhere"]},
        {"mineru_extra_args": ["--output=/outside"]},
        {"mineru_extra_args": ["--pages", "1-10"]},
    ],
)
def test_pdf_config_validation(data):
    with pytest.raises(ValidationError):
        MediaConfig(**data)


async def test_disabled_raw_fallback(tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj << >>\nstream\nBT (Recovered) Tj ET\nendstream\nendobj")
    doc, _ = await extract_pdf(path, MediaConfig(pdf_backend="pypdf"))
    assert doc.extractor_name == "pdf_raw"
    with pytest.raises(RagError, match="No extractable"):
        await extract_pdf(path, MediaConfig(pdf_backend="pypdf", pdf_fallback=False))


def test_license_and_optional_dependency_metadata():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert metadata["license"] == "Apache-2.0"
    assert metadata["license-files"] == ["LICENSE", "NOTICE"]
    assert any(dep.startswith("pypdf[") for dep in metadata["dependencies"])
    assert not any(dep.lower().startswith(("pymupdf", "mineru")) for dep in metadata["dependencies"])
    assert metadata["optional-dependencies"]["pymupdf"] == ["pymupdf>=1.25,<2"]
    assert "Version 2.0, January 2004" in (root / "LICENSE").read_text()
    assert "Copyright 2026 Bela Istvan MIHALIK" in (root / "NOTICE").read_text()
    for path in (root / "src").rglob("*"):
        if path.suffix in {".py", ".js", ".css", ".html", ".sql"}:
            content = path.read_text()
            assert "SPDX-License-Identifier: Apache-2.0" in content[:500], path
            assert "2026 Bela Istvan MIHALIK" in content[:500], path
