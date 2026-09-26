# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Reproducible local microbenchmarks; deterministic delayed embeddings, not Ollama.

Usage: uv run python tools/benchmark_indexing.py
No fixed speedup is promised: report actual timings on the machine being tested.
"""

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from ragdbman import db
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine


def vocabulary(batched):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE keywords(id TEXT PRIMARY KEY,canonical_form TEXT UNIQUE,display_form TEXT);
        CREATE TABLE chunk_keywords(chunk_id TEXT,keyword_id TEXT,PRIMARY KEY(chunk_id,keyword_id));
    """)
    chunks = [(str(i), [f"word-{(i + j) % 200}" for j in range(40)]) for i in range(500)]
    selects = 0

    def trace(statement):
        nonlocal selects
        if statement.startswith("SELECT"):
            selects += 1

    conn.set_trace_callback(trace)
    start = time.perf_counter()
    conn.execute("BEGIN")
    if batched:
        db.batch_keywords(conn, chunks)
    else:
        for chunk_id, terms in chunks:
            for term in terms:
                row = conn.execute("SELECT id FROM keywords WHERE canonical_form=?", (term,)).fetchone()
                identifier = row[0] if row else db.uid()
                if row is None:
                    db.insert(conn, "keywords", dict(id=identifier, canonical_form=term, display_form=term))
                db.insert(conn, "chunk_keywords", dict(chunk_id=chunk_id, keyword_id=identifier))
    conn.commit()
    elapsed = time.perf_counter() - start
    conn.set_trace_callback(None)
    assert conn.execute("SELECT COUNT(*) FROM chunk_keywords").fetchone()[0] == 20000
    assert conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] == 200
    conn.close()
    return dict(seconds=round(elapsed, 4), vocabulary_selects=selects)


class DelayedEmbedder:
    async def embed(self, texts, *args):
        await asyncio.sleep(0.04)
        return [[1.0, 0.0, 0.5, 0.5] for _ in texts]


async def scan(concurrency):
    with tempfile.TemporaryDirectory(prefix="ragdbman-benchmark-") as directory:
        root = Path(directory)
        sources = root / "sources"
        sources.mkdir()
        for n in range(32):
            (sources / f"file{n}.py").write_text(f"def method{n}():\n    return 'retrieval example'\n")
        cfg = GlobalConfig(
            storage={
                "data_dir": str(root / "data"),
                "registry_path": str(root / "registry.json"),
                "allowed_source_roots": [str(sources)],
            },
            defaults={"allow_approximate_tokenizer": True, "max_concurrent_files": concurrency},
        )
        engine = Engine(cfg, DelayedEmbedder())
        try:
            await engine.create_collection(name="code", kind="source_code")
            start = time.perf_counter()
            job = engine.start_scan("code", str(sources))
            await engine.tasks[job["id"]]
            elapsed = time.perf_counter() - start
            final = engine.get_job("code", job["id"])
            assert final["progress"]["completed"] == 32
            return dict(seconds=round(elapsed, 4), files=32, concurrency=concurrency)
        finally:
            await engine.close()


async def main():
    print(
        json.dumps(
            dict(
                caveat="Local microbenchmarks, warm dependencies, synthetic 40ms embedding latency; not real-model throughput.",
                keywords_per_term=vocabulary(False),
                keywords_batched=vocabulary(True),
                scan_serial=await scan(1),
                scan_parallel=await scan(4),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
