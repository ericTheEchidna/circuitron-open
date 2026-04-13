"""Ollama embedding backend for the local MCP server.

All embedding calls (query-time and ingestion-time) go through this module.
No OpenAI SDK is imported anywhere here.

Environment variables:
  OLLAMA_URL   - Base URL of the Ollama HTTP API  (default: http://ollama:11434)
  EMBED_MODEL  - Ollama model name for embeddings (default: nomic-embed-text)
  LLM_MAX_CONCURRENCY - Max parallel embed calls during batch ingestion (default: 2)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Sequence

import httpx

log = logging.getLogger(__name__)

OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")
_MAX_CONCURRENCY: int = int(os.getenv("LLM_MAX_CONCURRENCY", "2"))

# Shared semaphore — created lazily so it lives inside a running event loop.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    return _semaphore


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_ollama() -> None:
    """Verify Ollama is reachable and EMBED_MODEL is pulled.

    Raises RuntimeError with an actionable message if either check fails.
    Called once at server startup from main.py.
    """
    tags_url = f"{OLLAMA_URL}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(tags_url)
            resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_URL}. "
            "Make sure the ollama service is running (`docker compose up ollama`). "
            f"Detail: {exc}"
        ) from exc

    data = resp.json()
    pulled = {m.get("name", "").split(":")[0] for m in data.get("models", [])}
    base_model = EMBED_MODEL.split(":")[0]
    if base_model not in pulled:
        raise RuntimeError(
            f"Embedding model '{EMBED_MODEL}' is not pulled in Ollama. "
            f"Run: ollama pull {EMBED_MODEL}"
        )

    log.info("Ollama OK — embedding model '%s' is available at %s", EMBED_MODEL, OLLAMA_URL)


async def embed(text: str) -> list[float]:
    """Return the embedding vector for a single text string."""
    async with _get_semaphore():
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            resp.raise_for_status()

    result: list[float] = resp.json()["embedding"]
    return result


async def embed_batch(texts: Sequence[str]) -> list[list[float]]:
    """Return embedding vectors for a list of strings.

    Concurrency is capped by LLM_MAX_CONCURRENCY to avoid overwhelming Ollama
    during bulk ingestion.
    """
    tasks = [embed(t) for t in texts]
    return await asyncio.gather(*tasks)
