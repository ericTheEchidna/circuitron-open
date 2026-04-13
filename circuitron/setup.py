"""Setup command: crawl SKiDL docs and populate the local pgvector knowledge base.

Replaces the old Supabase/Neo4j MCP-agent flow with a direct pipeline:
  1. Crawl  — fetch pages from the SKiDL docs site
  2. Chunk  — split each page into ~500-token chunks with overlap
  3. Embed  — call Ollama's HTTP API for each chunk
  4. Insert — upsert into pgvector crawled_pages (idempotent via ON CONFLICT DO NOTHING)
  5. Verify — confirm the static KG index (skidl_kg.json) is present

Environment variables (read from .env or shell):
  POSTGRES_URL  - pgvector DSN         (default: postgresql://captain:memex2026@localhost:5434/circuitron)
  SETUP_OLLAMA_URL - Ollama base URL   (default: http://localhost:11434)
  EMBED_MODEL   - Ollama embed model   (default: nomic-embed-text)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import psycopg2
import psycopg2.extras

from .models import SetupOutput
from .ui.app import TerminalUI

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (host-side defaults — not the in-Docker defaults)
# ---------------------------------------------------------------------------

_POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://captain:memex2026@localhost:5434/circuitron",
)
_OLLAMA_URL = os.getenv("SETUP_OLLAMA_URL", os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
_EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ~500 tokens at ~4 chars/token; 200-char overlap keeps context across boundaries
_CHUNK_SIZE = 2000
_CHUNK_OVERLAP = 200

_KG_INDEX_PATH = Path(__file__).parent.parent / "mcp_server" / "data" / "skidl_kg.json"

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text."""

    _SKIP_TAGS = {"script", "style", "head", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self.parts)


class _LinkExtractor(HTMLParser):
    """Collect all href values from anchor tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            for attr, val in attrs:
                if attr == "href" and val:
                    self.links.append(val)


def _extract_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return re.sub(r"\s{2,}", " ", p.get_text()).strip()


def _extract_links(html: str, base_url: str) -> list[str]:
    p = _LinkExtractor()
    p.feed(html)
    base = urlparse(base_url)
    result = []
    for href in p.links:
        # Skip anchors, mailto, javascript, external domains
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(base_url, href).split("#")[0]  # strip fragment
        parsed = urlparse(full)
        if parsed.netloc == base.netloc and parsed.scheme in ("http", "https"):
            result.append(full)
    return result


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, url: str) -> list[dict]:
    """Split text into overlapping chunks. Returns list of {chunk_number, content}."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"chunk_number": idx, "content": chunk, "url": url})
            idx += 1
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


# ---------------------------------------------------------------------------
# Ollama embedding
# ---------------------------------------------------------------------------

async def _embed(client: httpx.AsyncClient, text: str) -> list[float]:
    resp = await client.post(
        f"{_OLLAMA_URL}/api/embeddings",
        json={"model": _EMBED_MODEL, "prompt": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


async def _check_ollama(client: httpx.AsyncClient) -> None:
    try:
        resp = await client.get(f"{_OLLAMA_URL}/api/tags", timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {_OLLAMA_URL}. "
            "Make sure Ollama is running (docker compose up ollama)."
        ) from exc
    pulled = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
    if _EMBED_MODEL.split(":")[0] not in pulled:
        raise RuntimeError(
            f"Embedding model '{_EMBED_MODEL}' not found in Ollama. "
            f"Run: ollama pull {_EMBED_MODEL}"
        )


# ---------------------------------------------------------------------------
# pgvector insertion (sync, run in executor)
# ---------------------------------------------------------------------------

def _ensure_source(conn: psycopg2.extensions.connection, source_id: str, docs_url: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (source_id, summary)
            VALUES (%s, %s)
            ON CONFLICT (source_id) DO NOTHING
            """,
            (source_id, f"SKiDL documentation crawled from {docs_url}"),
        )
    conn.commit()


def _insert_chunk(
    conn: psycopg2.extensions.connection,
    url: str,
    chunk_number: int,
    content: str,
    embedding: list[float],
    source_id: str,
) -> bool:
    """Insert a single chunk. Returns True if inserted, False if already existed."""
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawled_pages (url, chunk_number, content, source_id, embedding)
            VALUES (%s, %s, %s, %s, %s::vector)
            ON CONFLICT (url, chunk_number) DO NOTHING
            """,
            (url, chunk_number, content, source_id, vec_str),
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

async def _crawl_and_ingest(
    docs_url: str,
    *,
    ui: TerminalUI | None,
    operations: list[str],
    warnings: list[str],
) -> str:
    """Crawl docs_url, embed all chunks, insert into pgvector.

    Returns a status string: 'created', 'updated', or 'error'.
    """
    source_id = urlparse(docs_url).netloc  # e.g. "devbisme.github.io"

    try:
        conn = psycopg2.connect(_POSTGRES_URL)
    except Exception as exc:
        warnings.append(f"Cannot connect to pgvector: {exc}")
        return "error"

    visited: set[str] = set()
    queue: list[str] = [docs_url]
    total_inserted = 0

    try:
        _ensure_source(conn, source_id, docs_url)

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            await _check_ollama(client)

            while queue:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception as exc:
                    warnings.append(f"Skipped {url}: {exc}")
                    continue

                html = resp.text
                # Discover links and queue new ones
                for link in _extract_links(html, url):
                    if link not in visited:
                        queue.append(link)

                text = _extract_text(html)
                if not text:
                    continue

                chunks = _chunk_text(text, url)
                msg = f"  {url} — {len(chunks)} chunk(s)"
                if ui:
                    ui.display_info(msg)
                else:
                    log.info(msg)

                for chunk in chunks:
                    embedding = await _embed(client, chunk["content"])
                    loop = asyncio.get_running_loop()
                    inserted = await loop.run_in_executor(
                        None,
                        _insert_chunk,
                        conn,
                        chunk["url"],
                        chunk["chunk_number"],
                        chunk["content"],
                        embedding,
                        source_id,
                    )
                    if inserted:
                        total_inserted += 1

        operations.append(
            f"Crawled {len(visited)} page(s), inserted {total_inserted} new chunk(s) into pgvector"
        )
        return "created" if total_inserted > 0 else "updated"

    except Exception as exc:
        warnings.append(f"Ingest error: {exc}")
        return "error"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# KG index check
# ---------------------------------------------------------------------------

def _check_kg_index() -> str:
    """Return 'present' or 'missing'."""
    if _KG_INDEX_PATH.exists():
        try:
            data = json.loads(_KG_INDEX_PATH.read_text())
            return "present" if data else "missing"
        except Exception:
            return "missing"
    return "missing"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_setup(
    docs_url: str,
    repo_url: str,
    *,
    ui: TerminalUI | None = None,
    timeout: float | None = None,
) -> SetupOutput:
    """Crawl SKiDL docs and populate the local pgvector knowledge base.

    Args:
        docs_url: Root URL of the SKiDL documentation site to crawl.
        repo_url: SKiDL Git repository URL (stored as metadata, not crawled).
        ui: Optional TerminalUI for progress display.
        timeout: Unused (kept for API compatibility); HTTP timeouts are per-request.

    Returns:
        SetupOutput summarising what was done.
    """
    started = time.perf_counter()
    operations: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    if ui:
        ui.start_stage("Setup")
        ui.display_info(f"Crawling SKiDL docs from {docs_url} ...")

    pgvector_status = await _crawl_and_ingest(
        docs_url, ui=ui, operations=operations, warnings=warnings
    )

    kg_status = _check_kg_index()
    if kg_status == "missing":
        warnings.append(
            f"KG index not found at {_KG_INDEX_PATH}. "
            "query_knowledge_graph will return empty results until it is generated."
        )
    else:
        operations.append(f"KG index present ({_KG_INDEX_PATH.name})")

    elapsed = time.perf_counter() - started

    out = SetupOutput(
        docs_url=docs_url,
        repo_url=repo_url,
        pgvector_status=pgvector_status,  # type: ignore[arg-type]
        kg_status=kg_status,  # type: ignore[arg-type]
        operations=operations,
        warnings=warnings,
        errors=errors,
        elapsed_seconds=elapsed,
    )

    if ui:
        from .ui.components import panel
        summary_lines = [
            f"Docs:  {out.docs_url} — {out.pgvector_status}",
            f"Graph: {out.kg_status}",
        ]
        if out.warnings:
            summary_lines.append("Warnings:\n- " + "\n- ".join(out.warnings))
        if out.errors:
            summary_lines.append("Errors:\n- " + "\n- ".join(out.errors))
        panel.show_panel(ui.console, "Setup Summary", "\n".join(summary_lines))
        ui.finish_stage("Setup")

    return out


__all__ = ["run_setup"]
