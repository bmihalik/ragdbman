# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Async Ollama /api/embed client with bounded concurrency and dimensional checks."""

import asyncio
import math
from typing import Protocol

import httpx

from .config import OllamaConfig
from .errors import RagError


class Embedder(Protocol):
    async def embed(
        self,
        texts: list[str],
        model: str,
        expected_dimensions: int | None = None,
        keep_alive: str | None = None,
    ) -> list[list[float]]: ...


class Ollama:
    def __init__(self, config: OllamaConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), timeout=config.request_timeout_seconds, transport=transport
        )
        self.semaphore = asyncio.Semaphore(config.max_concurrent_embedding_requests)

    async def close(self):
        await self.client.aclose()

    async def embed(
        self,
        texts: list[str],
        model: str,
        expected_dimensions: int | None = None,
        keep_alive: str | None = None,
    ) -> list[list[float]]:
        vectors = []
        for offset in range(0, len(texts), self.config.embedding_batch_size):
            batch = texts[offset : offset + self.config.embedding_batch_size]
            payload = {
                "model": model,
                "input": batch,
                "keep_alive": keep_alive or self.config.keep_alive,
                "truncate": False,
            }
            if model.startswith("bge-m3") and self.config.bge_m3_options:
                payload["options"] = self.config.bge_m3_options
            try:
                async with self.semaphore:
                    response = await self.client.post("/api/embed", json=payload)
                response.raise_for_status()
                data = response.json()["embeddings"]
                if not isinstance(data, list) or len(data) != len(batch):
                    raise ValueError("Embedding count does not match input count")
                for vector in data:
                    if (
                        not isinstance(vector, list)
                        or not vector
                        or not all(
                            isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                            for n in vector
                        )
                    ):
                        raise ValueError("Embedding must be a non-empty finite numeric vector")
                    expected_dimensions = expected_dimensions or len(vector)
                    if len(vector) != expected_dimensions:
                        raise RagError(
                            "VECTOR_SCHEMA_MISMATCH",
                            f"Expected {expected_dimensions} dimensions, received {len(vector)}",
                        )
                vectors.extend(data)
            except httpx.RequestError as exc:
                raise RagError("OLLAMA_UNAVAILABLE", f"Cannot reach Ollama: {exc}") from exc
            except (httpx.HTTPStatusError, ValueError, KeyError, TypeError) as exc:
                raise RagError("EMBEDDING_FAILED", f"Invalid Ollama embedding response: {exc}") from exc
        return vectors
