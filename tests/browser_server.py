# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Disposable browser-QA server. Never use this test embedder for real data.

Run from the checkout: uv run python tests/browser_server.py
Data is temporary and deleted when the process exits normally.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from conftest import FakeEmbedder

from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.web import create_app

if __name__ == "__main__":
    with TemporaryDirectory(prefix="ragdbman-browser-") as directory:
        root = Path(directory)
        sources = root / "sources"
        sources.mkdir()
        (sources / "reference.txt").write_text("Embedding retrieval reference. Price: EUR 25. Rating: 4.8.")
        config = GlobalConfig(
            storage={
                "data_dir": str(root / "data"),
                "registry_path": str(root / "registry.json"),
                "allowed_source_roots": [str(sources)],
            },
            defaults={"allow_approximate_tokenizer": True},
        )
        print(f"QA source root: {sources}", flush=True)
        uvicorn.run(create_app(Engine(config, FakeEmbedder())), host="127.0.0.1", port=8766)
