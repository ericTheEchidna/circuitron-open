"""
Utility functions for the Crawl4AI MCP server.

Patched to support a plain PostgreSQL connection via DATABASE_URL in addition to
the original Supabase (cloud) path. When DATABASE_URL is set, a lightweight
psycopg2 adapter replaces the supabase-py client so no Supabase account is
needed. All public functions have identical signatures and return shapes.
"""
import os
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
import json
from urllib.parse import urlparse
import openai
import re
import time

# Load OpenAI API key (only required when EMBEDDING_PROVIDER=openai)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------------------------------------------------------------------------
# Embedding configuration
# ---------------------------------------------------------------------------
_EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
_EMBEDDING_MODEL: str = os.getenv(
    "EMBEDDING_MODEL",
    "text-embedding-3-small" if _EMBEDDING_PROVIDER == "openai" else "nomic-embed-text",
)
_EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434").rstrip("/")

# Known vector dimensions for common embedding models
_KNOWN_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "nomic-embed-text": 768,
    "nomic-embed-text:latest": 768,
    "mxbai-embed-large": 1024,
    "bge-m3": 1024,
    "snowflake-arctic-embed": 1024,
    "all-minilm": 384,
    "all-minilm:l6-v2": 384,
    "all-minilm:l12-v2": 384,
}

_dims_env = os.getenv("EMBEDDING_DIMENSIONS", "")
EMBEDDING_DIMENSIONS: int = int(_dims_env) if _dims_env else _KNOWN_DIMS.get(_EMBEDDING_MODEL, 1536)

# ---------------------------------------------------------------------------
# Ollama embedding helpers
# ---------------------------------------------------------------------------

def _validate_embedding_dimensions(embedding: List[float]) -> None:
    """Raise ValueError when the returned embedding size doesn't match the schema."""
    actual = len(embedding)
    if actual != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS} "
            f"(EMBEDDING_DIMENSIONS env var / inferred from '{_EMBEDDING_MODEL}') "
            f"but the model returned {actual} dimensions.\n"
            f"Fix: set EMBEDDING_DIMENSIONS={actual} in mcp.env, then re-run "
            f"setup_pgvector_local.sql to recreate the schema with "
            f"vector({actual}) columns, then re-run circuitron setup."
        )


def _ollama_embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts via the Ollama HTTP API.

    Tries the batch endpoint (``/api/embed``, Ollama ≥ 0.3) first; falls back
    to sequential ``/api/embeddings`` calls for older versions.
    """
    import requests as _requests

    # Batch API (Ollama ≥ 0.3)
    try:
        resp = _requests.post(
            f"{_EMBEDDING_BASE_URL}/api/embed",
            json={"model": _EMBEDDING_MODEL, "input": texts},
            timeout=120.0,
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        if embeddings and len(embeddings) == len(texts):
            _validate_embedding_dimensions(embeddings[0])
            return embeddings
    except ValueError:
        # Re-raise dimension errors immediately — they are not retryable
        raise
    except Exception as e:
        print(f"Ollama batch embed failed ({e}), falling back to sequential calls…")

    # Sequential fallback (older Ollama / single-text endpoint)
    results: List[List[float]] = []
    for text in texts:
        try:
            r = _requests.post(
                f"{_EMBEDDING_BASE_URL}/api/embeddings",
                json={"model": _EMBEDDING_MODEL, "prompt": text},
                timeout=60.0,
            )
            r.raise_for_status()
            emb = r.json().get("embedding", [])
            _validate_embedding_dimensions(emb)
            results.append(emb)
        except ValueError:
            raise
        except Exception as ie:
            print(f"Ollama embed error for text snippet: {ie}")
            results.append([0.0] * EMBEDDING_DIMENSIONS)
    return results


# ---------------------------------------------------------------------------
# PostgreSQL adapter (used when DATABASE_URL is set)
# ---------------------------------------------------------------------------

class _Result:
    """Minimal stand-in for supabase APIResponse."""
    __slots__ = ("data",)

    def __init__(self, data: list):
        self.data = data


class _TableQuery:
    """Supabase-style fluent query builder backed by psycopg2."""

    def __init__(self, conn, table: str):
        self._conn = conn
        self._table = table
        self._op: Optional[str] = None
        self._payload: Any = None
        self._conditions: list = []  # (type, col, val)

    # -- builder methods ----------------------------------------------------

    def insert(self, data):
        self._op = "insert"
        self._payload = data
        return self

    def delete(self):
        self._op = "delete"
        return self

    def update(self, data):
        self._op = "update"
        self._payload = data
        return self

    def eq(self, col: str, val):
        self._conditions.append(("eq", col, val))
        return self

    def in_(self, col: str, vals):
        self._conditions.append(("in", col, list(vals)))
        return self

    # -- terminal -----------------------------------------------------------

    def execute(self) -> _Result:
        import psycopg2.extras  # available inside the Docker image

        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if self._op == "insert":
                return self._do_insert(cur)
            elif self._op == "delete":
                return self._do_delete(cur)
            elif self._op == "update":
                return self._do_update(cur)
        return _Result([])

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _pg_val(col: str, val) -> Tuple[Any, str]:
        """Return (adapted_value, placeholder_sql) for a column/value pair."""
        if col == "embedding" and isinstance(val, list):
            # pgvector: pass as '[x,y,...]'::vector
            return "[" + ",".join(str(x) for x in val) + "]", "%s::vector"
        if isinstance(val, dict):
            from psycopg2.extras import Json
            return Json(val), "%s"
        return val, "%s"

    def _do_insert(self, cur) -> _Result:
        rows = self._payload if isinstance(self._payload, list) else [self._payload]
        if not rows:
            return _Result([])
        cols = list(rows[0].keys())

        ph_list = []
        for col in cols:
            sample = rows[0].get(col)
            _, ph = self._pg_val(col, sample)
            ph_list.append(ph)

        col_sql = ", ".join(f'"{c}"' for c in cols)
        val_sql = ", ".join(ph_list)
        sql = f'INSERT INTO "{self._table}" ({col_sql}) VALUES ({val_sql})'

        batch = []
        for row in rows:
            vals = []
            for col in cols:
                v, _ = self._pg_val(col, row.get(col))
                vals.append(v)
            batch.append(vals)

        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, batch)
        self._conn.commit()
        return _Result([])

    def _do_delete(self, cur) -> _Result:
        if not self._conditions:
            return _Result([])
        where_parts: list = []
        vals: list = []
        for ctype, col, val in self._conditions:
            if ctype == "eq":
                where_parts.append(f'"{col}" = %s')
                vals.append(val)
            elif ctype == "in":
                where_parts.append(f'"{col}" = ANY(%s)')
                vals.append(val)
        sql = f'DELETE FROM "{self._table}" WHERE {" AND ".join(where_parts)}'
        cur.execute(sql, vals)
        self._conn.commit()
        return _Result([])

    def _do_update(self, cur) -> _Result:
        if not self._payload or not self._conditions:
            return _Result([])
        set_parts: list = []
        set_vals: list = []
        for col, val in self._payload.items():
            if val == "now()":
                set_parts.append(f'"{col}" = NOW()')
            else:
                adapted, ph = self._pg_val(col, val)
                set_parts.append(f'"{col}" = {ph}')
                set_vals.append(adapted)
        where_parts: list = []
        where_vals: list = []
        for ctype, col, val in self._conditions:
            if ctype == "eq":
                where_parts.append(f'"{col}" = %s')
                where_vals.append(val)
        sql = (
            f'UPDATE "{self._table}" '
            f'SET {", ".join(set_parts)} '
            f'WHERE {" AND ".join(where_parts)} '
            f'RETURNING *'
        )
        cur.execute(sql, set_vals + where_vals)
        import psycopg2.extras
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as rc:
            rc.execute(sql, set_vals + where_vals)
            rows = [dict(r) for r in rc.fetchall()]
        self._conn.commit()
        return _Result(rows)


class _RpcQuery:
    """Supabase-style RPC call backed by a stored SQL function."""

    def __init__(self, conn, fn: str, params: dict):
        self._conn = conn
        self._fn = fn
        self._params = params

    def execute(self) -> _Result:
        import psycopg2.extras

        p = self._params
        embedding: list = p["query_embedding"]
        match_count: int = p.get("match_count", 10)
        filter_val: dict = p.get("filter", {})
        source_filter: Optional[str] = p.get("source_filter", None)

        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {self._fn}(%s::vector, %s, %s::jsonb, %s)",
                [vec_str, match_count, json.dumps(filter_val), source_filter],
            )
            rows = [dict(r) for r in cur.fetchall()]
        return _Result(rows)


class _PostgresClient:
    """Drop-in replacement for supabase.Client using psycopg2.

    Activated automatically when the DATABASE_URL environment variable is set.
    """

    def __init__(self, dsn: str):
        import psycopg2
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False

    def table(self, name: str) -> _TableQuery:
        return _TableQuery(self._conn, name)

    def rpc(self, fn: str, params: dict) -> _RpcQuery:
        return _RpcQuery(self._conn, fn, params)


# ---------------------------------------------------------------------------
# Public: get_supabase_client (now provider-agnostic)
# ---------------------------------------------------------------------------

def get_supabase_client():
    """Return a DB client.

    Priority:
    1. DATABASE_URL env var → psycopg2-backed _PostgresClient (no Supabase needed)
    2. SUPABASE_URL + SUPABASE_SERVICE_KEY → official supabase-py client
    """
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return _PostgresClient(db_url)

    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError(
            "Either DATABASE_URL or (SUPABASE_URL + SUPABASE_SERVICE_KEY) must be set "
            "in environment variables."
        )
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Everything below is unchanged from the original utils.py
# ---------------------------------------------------------------------------

def create_embeddings_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    # Route to Ollama when configured
    if _EMBEDDING_PROVIDER == "ollama":
        return _ollama_embed_batch(texts)

    # OpenAI path
    max_retries = 3
    retry_delay = 1.0

    for retry in range(max_retries):
        try:
            response = openai.embeddings.create(
                model=_EMBEDDING_MODEL,
                input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            if retry < max_retries - 1:
                print(f"Error creating batch embeddings (attempt {retry + 1}/{max_retries}): {e}")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                print(f"Failed to create batch embeddings after {max_retries} attempts: {e}")
                print("Attempting to create embeddings individually...")
                embeddings = []
                successful_count = 0
                for i, text in enumerate(texts):
                    try:
                        individual_response = openai.embeddings.create(
                            model=_EMBEDDING_MODEL,
                            input=[text]
                        )
                        embeddings.append(individual_response.data[0].embedding)
                        successful_count += 1
                    except Exception as individual_error:
                        print(f"Failed to create embedding for text {i}: {individual_error}")
                        embeddings.append([0.0] * EMBEDDING_DIMENSIONS)
                print(f"Successfully created {successful_count}/{len(texts)} embeddings individually")
                return embeddings


def create_embedding(text: str) -> List[float]:
    try:
        embeddings = create_embeddings_batch([text])
        return embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS
    except Exception as e:
        print(f"Error creating embedding: {e}")
        return [0.0] * EMBEDDING_DIMENSIONS


def generate_contextual_embedding(full_document: str, chunk: str) -> Tuple[str, bool]:
    model_choice = os.getenv("MODEL_CHOICE")
    try:
        prompt = f"""<document>
{full_document[:25000]}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else."""

        response = openai.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides concise contextual information."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        context = response.choices[0].message.content.strip()
        contextual_text = f"{context}\n---\n{chunk}"
        return contextual_text, True
    except Exception as e:
        print(f"Error generating contextual embedding: {e}. Using original chunk instead.")
        return chunk, False


def process_chunk_with_context(args):
    url, content, full_document = args
    return generate_contextual_embedding(full_document, content)


def add_documents_to_supabase(
    client,
    urls: List[str],
    chunk_numbers: List[int],
    contents: List[str],
    metadatas: List[Dict[str, Any]],
    url_to_full_document: Dict[str, str],
    batch_size: int = 20
) -> None:
    unique_urls = list(set(urls))

    try:
        if unique_urls:
            client.table("crawled_pages").delete().in_("url", unique_urls).execute()
    except Exception as e:
        print(f"Batch delete failed: {e}. Trying one-by-one deletion as fallback.")
        for url in unique_urls:
            try:
                client.table("crawled_pages").delete().eq("url", url).execute()
            except Exception as inner_e:
                print(f"Error deleting record for URL {url}: {inner_e}")

    use_contextual_embeddings = os.getenv("USE_CONTEXTUAL_EMBEDDINGS", "false") == "true"
    print(f"\n\nUse contextual embeddings: {use_contextual_embeddings}\n\n")

    for i in range(0, len(contents), batch_size):
        batch_end = min(i + batch_size, len(contents))
        batch_urls = urls[i:batch_end]
        batch_chunk_numbers = chunk_numbers[i:batch_end]
        batch_contents = contents[i:batch_end]
        batch_metadatas = metadatas[i:batch_end]

        if use_contextual_embeddings:
            process_args = []
            for j, content in enumerate(batch_contents):
                url = batch_urls[j]
                full_document = url_to_full_document.get(url, "")
                process_args.append((url, content, full_document))

            contextual_contents = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_idx = {executor.submit(process_chunk_with_context, arg): idx
                                for idx, arg in enumerate(process_args)}
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        result, success = future.result()
                        contextual_contents.append(result)
                        if success:
                            batch_metadatas[idx]["contextual_embedding"] = True
                    except Exception as e:
                        print(f"Error processing chunk {idx}: {e}")
                        contextual_contents.append(batch_contents[idx])

            if len(contextual_contents) != len(batch_contents):
                print(f"Warning: Expected {len(batch_contents)} results but got {len(contextual_contents)}")
                contextual_contents = batch_contents
        else:
            contextual_contents = batch_contents

        batch_embeddings = create_embeddings_batch(contextual_contents)

        batch_data = []
        for j in range(len(contextual_contents)):
            chunk_size = len(contextual_contents[j])
            parsed_url = urlparse(batch_urls[j])
            source_id = parsed_url.netloc or parsed_url.path
            data = {
                "url": batch_urls[j],
                "chunk_number": batch_chunk_numbers[j],
                "content": contextual_contents[j],
                "metadata": {
                    "chunk_size": chunk_size,
                    **batch_metadatas[j]
                },
                "source_id": source_id,
                "embedding": batch_embeddings[j]
            }
            batch_data.append(data)

        max_retries = 3
        retry_delay = 1.0
        for retry in range(max_retries):
            try:
                client.table("crawled_pages").insert(batch_data).execute()
                break
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"Error inserting batch (attempt {retry + 1}/{max_retries}): {e}")
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    print(f"Failed to insert batch after {max_retries} attempts: {e}")
                    print("Attempting to insert records individually...")
                    successful_inserts = 0
                    for record in batch_data:
                        try:
                            client.table("crawled_pages").insert(record).execute()
                            successful_inserts += 1
                        except Exception as individual_error:
                            print(f"Failed to insert individual record for URL {record['url']}: {individual_error}")
                    if successful_inserts > 0:
                        print(f"Successfully inserted {successful_inserts}/{len(batch_data)} records individually")


def search_documents(
    client,
    query: str,
    match_count: int = 10,
    filter_metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    query_embedding = create_embedding(query)
    try:
        params = {
            'query_embedding': query_embedding,
            'match_count': match_count
        }
        if filter_metadata:
            params['filter'] = filter_metadata
        result = client.rpc('match_crawled_pages', params).execute()
        return result.data
    except Exception as e:
        print(f"Error searching documents: {e}")
        return []


def extract_code_blocks(markdown_content: str, min_length: int = 1000) -> List[Dict[str, Any]]:
    code_blocks = []
    content = markdown_content.strip()
    start_offset = 0
    if content.startswith('```'):
        start_offset = 3
        print("Skipping initial triple backticks")

    backtick_positions = []
    pos = start_offset
    while True:
        pos = markdown_content.find('```', pos)
        if pos == -1:
            break
        backtick_positions.append(pos)
        pos += 3

    i = 0
    while i < len(backtick_positions) - 1:
        start_pos = backtick_positions[i]
        end_pos = backtick_positions[i + 1]
        code_section = markdown_content[start_pos+3:end_pos]
        lines = code_section.split('\n', 1)
        if len(lines) > 1:
            first_line = lines[0].strip()
            if first_line and not ' ' in first_line and len(first_line) < 20:
                language = first_line
                code_content = lines[1].strip() if len(lines) > 1 else ""
            else:
                language = ""
                code_content = code_section.strip()
        else:
            language = ""
            code_content = code_section.strip()

        if len(code_content) < min_length:
            i += 2
            continue

        context_start = max(0, start_pos - 1000)
        context_before = markdown_content[context_start:start_pos].strip()
        context_end = min(len(markdown_content), end_pos + 3 + 1000)
        context_after = markdown_content[end_pos + 3:context_end].strip()
        code_blocks.append({
            'code': code_content,
            'language': language,
            'context_before': context_before,
            'context_after': context_after,
            'full_context': f"{context_before}\n\n{code_content}\n\n{context_after}"
        })
        i += 2

    return code_blocks


def generate_code_example_summary(code: str, context_before: str, context_after: str) -> str:
    model_choice = os.getenv("MODEL_CHOICE")
    prompt = f"""<context_before>
{context_before[-500:] if len(context_before) > 500 else context_before}
</context_before>

<code_example>
{code[:1500] if len(code) > 1500 else code}
</code_example>

<context_after>
{context_after[:500] if len(context_after) > 500 else context_after}
</context_after>

Based on the code example and its surrounding context, provide a concise summary (2-3 sentences) that describes what this code example demonstrates and its purpose. Focus on the practical application and key concepts illustrated.
"""
    try:
        response = openai.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides concise code example summaries."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating code example summary: {e}")
        return "Code example for demonstration purposes."


def add_code_examples_to_supabase(
    client,
    urls: List[str],
    chunk_numbers: List[int],
    code_examples: List[str],
    summaries: List[str],
    metadatas: List[Dict[str, Any]],
    batch_size: int = 20
):
    if not urls:
        return

    unique_urls = list(set(urls))
    for url in unique_urls:
        try:
            client.table('code_examples').delete().eq('url', url).execute()
        except Exception as e:
            print(f"Error deleting existing code examples for {url}: {e}")

    total_items = len(urls)
    for i in range(0, total_items, batch_size):
        batch_end = min(i + batch_size, total_items)
        batch_texts = []
        for j in range(i, batch_end):
            combined_text = f"{code_examples[j]}\n\nSummary: {summaries[j]}"
            batch_texts.append(combined_text)

        embeddings = create_embeddings_batch(batch_texts)

        valid_embeddings = []
        for embedding in embeddings:
            if embedding and not all(v == 0.0 for v in embedding):
                valid_embeddings.append(embedding)
            else:
                print(f"Warning: Zero or invalid embedding detected, creating new one...")
                single_embedding = create_embedding(batch_texts[len(valid_embeddings)])
                valid_embeddings.append(single_embedding)

        batch_data = []
        for j, embedding in enumerate(valid_embeddings):
            idx = i + j
            parsed_url = urlparse(urls[idx])
            source_id = parsed_url.netloc or parsed_url.path
            batch_data.append({
                'url': urls[idx],
                'chunk_number': chunk_numbers[idx],
                'content': code_examples[idx],
                'summary': summaries[idx],
                'metadata': metadatas[idx],
                'source_id': source_id,
                'embedding': embedding
            })

        max_retries = 3
        retry_delay = 1.0
        for retry in range(max_retries):
            try:
                client.table('code_examples').insert(batch_data).execute()
                break
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"Error inserting batch (attempt {retry + 1}/{max_retries}): {e}")
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    print(f"Failed to insert batch after {max_retries} attempts: {e}")
                    print("Attempting to insert records individually...")
                    successful_inserts = 0
                    for record in batch_data:
                        try:
                            client.table('code_examples').insert(record).execute()
                            successful_inserts += 1
                        except Exception as individual_error:
                            print(f"Failed to insert individual record for URL {record['url']}: {individual_error}")
                    if successful_inserts > 0:
                        print(f"Successfully inserted {successful_inserts}/{len(batch_data)} records individually")
        print(f"Inserted batch {i//batch_size + 1} of {(total_items + batch_size - 1)//batch_size} code examples")


def update_source_info(client, source_id: str, summary: str, word_count: int):
    try:
        result = client.table('sources').update({
            'summary': summary,
            'total_word_count': word_count,
            'updated_at': 'now()'
        }).eq('source_id', source_id).execute()

        if not result.data:
            client.table('sources').insert({
                'source_id': source_id,
                'summary': summary,
                'total_word_count': word_count
            }).execute()
            print(f"Created new source: {source_id}")
        else:
            print(f"Updated source: {source_id}")
    except Exception as e:
        print(f"Error updating source {source_id}: {e}")


def extract_source_summary(source_id: str, content: str, max_length: int = 500) -> str:
    default_summary = f"Content from {source_id}"
    if not content or len(content.strip()) == 0:
        return default_summary

    model_choice = os.getenv("MODEL_CHOICE")
    truncated_content = content[:25000] if len(content) > 25000 else content
    prompt = f"""<source_content>
{truncated_content}
</source_content>

The above content is from the documentation for '{source_id}'. Please provide a concise summary (3-5 sentences) that describes what this library/tool/framework is about. The summary should help understand what the library/tool/framework accomplishes and the purpose.
"""
    try:
        response = openai.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides concise library/tool/framework summaries."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=150
        )
        summary = response.choices[0].message.content.strip()
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
        return summary
    except Exception as e:
        print(f"Error generating summary with LLM for {source_id}: {e}. Using default summary.")
        return default_summary


def search_code_examples(
    client,
    query: str,
    match_count: int = 10,
    filter_metadata: Optional[Dict[str, Any]] = None,
    source_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    enhanced_query = f"Code example for {query}\n\nSummary: Example code showing {query}"
    query_embedding = create_embedding(enhanced_query)
    try:
        params = {
            'query_embedding': query_embedding,
            'match_count': match_count
        }
        if filter_metadata:
            params['filter'] = filter_metadata
        if source_id:
            params['source_filter'] = source_id
        result = client.rpc('match_code_examples', params).execute()
        return result.data
    except Exception as e:
        print(f"Error searching code examples: {e}")
        return []
