# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Validate and index an explicitly supplied ZIP in temporary, isolated storage.

Usage: uv run python tools/check_card_corpus.py path/to/cards.zip
The archive is not redistributed. Deterministic vectors test plumbing, not quality.
"""

import asyncio
import hashlib
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml

from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.knowledge_cards import dump_cards, fields, parse


class TestEmbedder:
    async def embed(self, texts, model, expected_dimensions=None, keep_alive=None):
        return [[v / 255 for v in hashlib.sha256(text.encode()).digest()[:8]] for text in texts]


async def check(archive):
    with tempfile.TemporaryDirectory(prefix="ragdbman-card-corpus-") as directory:
        root = Path(directory)
        sources = root / "sources"
        sources.mkdir()
        cards, expected_vectors = {}, 0
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if not member.filename.lower().endswith((".yaml", ".yml")):
                    continue
                raw = bundle.read(member).decode("utf-8-sig")
                card = parse(raw)
                assert card is not None, f"Non-card YAML: {member.filename}"
                assert card["id"] not in cards, f"Duplicate ID: {card['id']}"
                cards[card["id"]] = card
                expected_vectors += len(fields(card))
                # Never trust archive paths or IDs as output filenames.
                (sources / f"{len(cards):06d}.yaml").write_text(raw)
        cfg = GlobalConfig(
            storage={
                "data_dir": str(root / "data"),
                "registry_path": str(root / "registry.json"),
                "allowed_source_roots": [str(sources)],
            }
        )
        engine = Engine(cfg, TestEmbedder())
        try:
            await engine.collection_create(name="corpus", kind="knowledge_cards", source_roots=[str(sources)])
            for unchanged in (False, True):
                job = engine.scan_start("corpus", str(sources))
                await asyncio.wait_for(engine.tasks[job["id"]], 300)
                result = engine.scan_job_get("corpus", job["id"])
                assert result["status"] == "completed", result
                assert result["progress"]["unchanged" if unchanged else "completed"] == len(cards)
            with engine.connection("corpus") as conn:
                assert conn.execute("SELECT COUNT(*) FROM kc_cards").fetchone()[0] == len(cards)
                assert conn.execute("SELECT COUNT(*) FROM kc_fts").fetchone()[0] == len(cards)
                assert conn.execute("SELECT COUNT(*) FROM kc_embeddings").fetchone()[0] == expected_vectors
                for row in conn.execute("SELECT id,raw_yaml FROM kc_cards"):
                    payload = parse(row["raw_yaml"])
                    expected = {k: v for k, v in cards[row["id"]].items() if k != "id"}
                    assert yaml.safe_load(dump_cards([payload])) == expected
            for mode in ("keyword", "vector", "hybrid"):
                for query_type in ("general", "expert"):
                    matches = await engine._query_cards(
                        collection="corpus",
                        query="breadth first search graph queue",
                        mode=mode,
                        query_type=query_type,
                        minimum_similarity=0,
                    )
                    assert matches and len(matches) <= 3
            assert not list(sources.rglob(".ragdbman"))
            print(
                f"{len(cards)} cards; {expected_vectors} field embeddings; "
                "scan, unchanged rescan, six retrieval combinations and all YAML roundtrips passed."
            )
        finally:
            await engine.close()


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1]))
