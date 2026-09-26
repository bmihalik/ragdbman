# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import asyncio
import hashlib

import pytest

from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.errors import RagError


def text_pdf(path, texts):
    """Build PDF fixtures using pypdf only; no optional native PDF dependency."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    return path


class FakeEmbedder:
    """Deterministic test double only. Production never synthesizes embeddings."""

    def __init__(self):
        self.calls = []
        self.failure = False
        self.dimensions = 8
        self.delay = 0
        self.entered = asyncio.Event()
        self.gate = None

    async def embed(self, texts, model, expected_dimensions=None, keep_alive=None):
        self.calls.append((texts, model, expected_dimensions, keep_alive))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise RagError("OLLAMA_UNAVAILABLE", "test outage")
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append([digest[i] / 255 for i in range(self.dimensions)])
        return vectors


@pytest.fixture
def cfg(tmp_path):
    return GlobalConfig(
        storage={
            "data_dir": str(tmp_path / "data"),
            "registry_path": str(tmp_path / "registry.json"),
            "allowed_source_roots": [str(tmp_path / "sources")],
        },
        defaults={"allow_approximate_tokenizer": True},
    )


@pytest.fixture
def source_dir(tmp_path):
    root = tmp_path / "sources"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture
def fake():
    return FakeEmbedder()


@pytest.fixture
async def engine(cfg, fake, source_dir):
    engine = Engine(cfg, fake)
    yield engine
    await engine.close()


async def finish(engine, name, job):
    await asyncio.wait_for(engine.tasks[job["id"]], 15)
    return engine.get_job(name, job["id"])
