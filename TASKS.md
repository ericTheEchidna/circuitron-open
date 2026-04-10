# TASKS.md — Circuitron

Generated from MEMEX task database. **Do not hand-edit** — changes will be overwritten.
Update tasks via API: `http://miso:8002/tasks/{task_code}`

---

## How to work tasks

1. **Pick a task** — only work the task(s) explicitly stated at session start.
2. **Mark it active** — `PATCH http://miso:8002/tasks/{code}` with `{"status": "in_progress"}`.
3. **Implement it** — stay focused on the task scope. Do not go on extended research tangents,
   refactor unrelated code, or explore topics beyond what's needed to complete the task.
   If something is unclear or under-specified, **ask for clarification** rather than guessing.
4. **Mark it done** — `PATCH` with `{"status": "done"}` when all done-when criteria are met.
5. **New work discovered?** — Create a new task via `POST http://miso:8002/tasks`.
   Do not expand the current task's scope.

**Key rules:**
- The `body` field contains the full scope, subtasks, and done-when criteria. Read it carefully.
- Do not do extensive research or go far afield from the implementation unless the task explicitly asks for it.
- If the task description is ambiguous or missing context, stop and ask — do not assume.
- One task at a time. Finish or pause before starting another.

---

## Open

### CIRCUITRON-016 — Rewrite README and SETUP.md for fully local setup

**Priority:** low

## Goal
A new user should be able to read SETUP.md and get a running Circuitron instance using only Docker, Ollama, and an Anthropic API key — no sign-ups for Supabase, Neo4j, or OpenAI.

## Subtasks
- [ ] Rewrite SETUP.md prerequisites section: Docker + Ollama + Anthropic key only
- [ ] Replace MCP server setup steps (create Supabase account, Neo4j account, etc.) with:
  1. `docker compose up -d` (starts pgvector, Ollama, local MCP server)
  2. `circuitron setup` (crawls docs, populates local DB)
  3. `circuitron "Design a voltage divider"` (run it)
- [ ] Remove all references to `setup_supabase.sql` from the setup guide (keep the file for reference but note it's legacy)
- [ ] Update README Supported Providers table — MCP server row now shows "pgvector + Ollama" as current
- [ ] Update README Prerequisites section
- [ ] Update the Architecture Diagram description to reflect local backends
- [ ] Remove "until MCP server provider abstraction is implemented" disclaimer text throughout
- [ ] Add a note on Ollama model size requirements (nomic-embed-text is ~274MB)
- [ ] Add GPU tip (optional, for faster embedding)

## Done when
SETUP.md can be followed start-to-finish by someone with Docker and an Anthropic key, with no external service sign-ups required.

### CIRCUITRON-015 — Update mcp.env.example and strip all external credential requirements


## Goal
The new `mcp.env.example` should have zero credentials that require external accounts.

## New mcp.env.example content
```env
# Local MCP server config
TRANSPORT=sse
HOST=0.0.0.0
PORT=8051

# Ollama (local LLM + embeddings)
OLLAMA_URL=http://ollama:11434
EMBED_MODEL=nomic-embed-text
LLM_MODEL=qwen2.5-coder:7b

# RAG settings
USE_RERANKING=false
LLM_MAX_CONCURRENCY=2

# PostgreSQL + pgvector
POSTGRES_URL=postgresql://captain:memex2026@pgvector:5432/circuitron
```

## Subtasks
- [ ] Rewrite `mcp.env.example` with the above content
- [ ] Search codebase for any hardcoded `SUPABASE_*`, `NEO4J_*`, `OPENAI_API_KEY` references in the main app (not mcp_server/) and confirm none remain
- [ ] Update `.env.example` — confirm `OPENAI_API_KEY` is not required when `CIRCUITRON_PROVIDER=anthropic` (it should already be optional; verify and document clearly)
- [ ] Update README env var table to remove the removed vars and add the new ones
- [ ] Confirm `checks.json` (if it validates env vars) is updated to match

## Done when
A user can copy `mcp.env.example` → `mcp.env` and run the stack with zero external API keys, assuming Anthropic key for the main app.

### CIRCUITRON-014 — Update docker-compose.yml and remove upstream image dependency


## Goal
A single `docker compose up` starts everything needed: pgvector, Ollama, and the local MCP server. The upstream container is no longer referenced anywhere.

## Subtasks
- [ ] Add `ollama` service to `docker-compose.yml`:
  ```yaml
  ollama:
    image: ollama/ollama
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
  ```
- [ ] Add `mcp-local` service that builds from `./mcp_server/Dockerfile`:
  ```yaml
  mcp-local:
    build: ./mcp_server
    ports:
      - "8051:8051"
    depends_on: [pgvector, ollama]
    env_file: mcp.env
  ```
- [ ] Add named volumes: `ollama_data`
- [ ] Add a one-shot `model-pull` init container or entrypoint script that runs `ollama pull nomic-embed-text` on first startup
- [ ] Remove any lingering references to `ghcr.io/shaurya-sethi/circuitron-mcp` from compose file
- [ ] Test `docker compose up --build` brings all services healthy

## Done when
`docker compose up` starts pgvector, Ollama, and the local MCP server with no errors. `curl http://localhost:8051/sse` returns a valid SSE stream.

## Notes
- GPU passthrough for Ollama is optional but speeds up embedding significantly — document the nvidia-container-toolkit setup as a tip, not a requirement
- The `pgvector` service is already defined in docker-compose.yml; just ensure port/credential alignment with `mcp.env.example`

### CIRCUITRON-013 — Rework circuitron setup to populate local backends


## Goal
`circuitron setup` must work end-to-end with only Docker + Ollama. No Supabase, no Neo4j, no OpenAI.

## Subtasks
- [ ] Update the setup flow in `circuitron/setup.py` (or equivalent) to:
  - Check pgvector is reachable (via MCP server health endpoint or direct DB ping)
  - Check Ollama is reachable and `nomic-embed-text` is available
  - If either is missing, print a clear actionable error and exit
- [ ] Crawl SKiDL documentation: `https://devbisme.github.io/skidl/`
  - Fetch pages, chunk text (e.g. 500-token chunks with 50-token overlap)
  - Embed each chunk via Ollama
  - Insert into `crawled_pages` table in pgvector
  - This currently goes through the MCP `smart_crawl_url` tool — either replicate that logic locally or call the new MCP server's internal ingest endpoint
- [ ] Parse SKiDL source → generate `skidl_kg.json` (calls `scripts/build_kg_index.py`)
  - Insert skidl_kg.json into the mcp_server/data/ path (mounted volume in Docker)
- [ ] Parse SKiDL GitHub repo for code examples → embed → insert into `code_examples` table
- [ ] Make setup idempotent: skip chunks already in DB (check by source URL hash)
- [ ] Update `/setup` interactive command to call the new flow

## Done when
Running `circuitron setup` from scratch on a clean environment populates pgvector with SKiDL docs and code examples, and writes `skidl_kg.json`, with no external API keys required.

## Notes
- Crawling + embedding ~200 SKiDL doc pages locally will take longer than with OpenAI — set user expectations in output
- The `smart_crawl_url` MCP tool from upstream did recursive crawling with JS rendering; a simpler `requests` + `BeautifulSoup` crawler is sufficient for the static SKiDL docs site

### CIRCUITRON-012 — Replace Neo4j knowledge graph with static JSON index


## Goal
Eliminate the Neo4j dependency entirely. The knowledge graph is queried for SKiDL API structure (class names, method signatures, attributes). A static JSON index built from the SKiDL source at setup time covers all these queries without a graph database.

## Subtasks
- [ ] Write `scripts/build_kg_index.py`: parse SKiDL source tree (clone or use installed package) using `ast` module
  - Extract: module → class → methods/attributes with signatures and docstrings
  - Output: `mcp_server/data/skidl_kg.json`
- [ ] Implement `query_knowledge_graph(query: str) -> dict` in `mcp_server/tools/kg.py`
  - Load `skidl_kg.json` into memory on first call (singleton)
  - Simple keyword + fuzzy search over class/method names (use `difflib` or `rapidfuzz`)
  - Return matching class/method entries with signatures and docstrings
- [ ] Fallback: if the index is missing, return an empty result with a warning (don't crash)
- [ ] Wire tool into MCP JSON-RPC dispatcher
- [ ] Add index generation to `circuitron setup` flow
- [ ] Remove all `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` references from `mcp.env.example`, README, SETUP.md

## Done when
`query_knowledge_graph("Net")` returns the `Net` class definition, constructor signature, and key methods from the index without any network calls.

## Notes
- The JSON index will be small (~1-2 MB for SKiDL) and can be bundled with the repo as a pre-built artifact, so users don't need to regenerate it unless SKiDL is updated
- If fuzzy keyword search proves insufficient, fall through to `perform_rag_query` as a secondary lookup
- The upstream Neo4j graph also stored repository/file structure — that metadata can live in the JSON index too

### CIRCUITRON-011 — Implement perform_rag_query and search_code_examples tools

**Priority:** high

## Goal
The two most critical MCP tools the agents call. Both follow the same pattern: embed the query → vector search pgvector → return ranked chunks.

## Subtasks
- [ ] Implement `perform_rag_query(query: str, top_k: int = 5) -> list[dict]` in `mcp_server/tools/rag.py`
  - Embed query with Ollama
  - Call `match_crawled_pages()` in pgvector
  - Return `[{content, url, similarity}, ...]`
- [ ] Implement `search_code_examples(query: str, top_k: int = 5) -> list[dict]`
  - Embed query with Ollama
  - Call `match_code_examples()` in pgvector
  - Return `[{code, description, similarity}, ...]`
- [ ] Optional: add Ollama LLM reranking pass (controlled by `USE_RERANKING=true` env var)
  - If enabled: send top-k chunks + query to `LLM_MODEL` with a reranking prompt, return reordered list
  - If disabled: return vector similarity order as-is
- [ ] Wire both tools into the MCP JSON-RPC dispatcher
- [ ] Write unit tests with a mock pgvector connection

## Done when
Calling `perform_rag_query` via the MCP protocol returns relevant SKiDL doc chunks after the knowledge base has been populated. `search_code_examples` returns working SKiDL snippets.

## Notes
- Reranking with a local LLM is optional but improves quality significantly — worth implementing behind a flag
- Match the exact JSON response shape the agents expect (check `circuitron/prompts.py` for how results are used)

### CIRCUITRON-010 — Implement Ollama embedding backend

**Priority:** high

## Goal
All embedding calls (both at ingestion time and at query time) must go through Ollama's local HTTP API. No OpenAI SDK import anywhere in `mcp_server/`.

## Subtasks
- [ ] Create `mcp_server/embeddings.py` with `embed(text: str) -> list[float]`
- [ ] Call `POST http://{OLLAMA_URL}/api/embeddings` with `{"model": EMBED_MODEL, "prompt": text}`
- [ ] Add `OLLAMA_URL` (default: `http://ollama:11434`) and `EMBED_MODEL` (default: `nomic-embed-text`) env vars
- [ ] Handle batch embedding for ingestion: loop with optional concurrency limit
- [ ] Add model availability check on startup: if model not pulled, log a clear error and exit
- [ ] Add `ollama` service to `docker-compose.yml` (image: `ollama/ollama`) with a volume for model storage
- [ ] Add model pull step to setup docs: `ollama pull nomic-embed-text`
- [ ] Remove `OPENAI_API_KEY` from `mcp.env.example` entirely

## Done when
Embedding a short string returns a 768-element float list with no external API calls. Confirmed with a quick `curl` test against the local MCP server's internal embed route.

## Notes
- `nomic-embed-text` outputs 768 dims — matches `setup_pgvector_local.sql` vector column size
- If Ollama is running on the host (not in Docker), use `host.docker.internal` for the URL inside Docker
- Consider `mxbai-embed-large` (1024d) as a higher-quality alternative — requires schema change

---

## Completed

### CIRCUITRON-00F — Integrate pgvector as the vector store backend

**Priority:** high

## Goal
Replace Supabase as the vector/document store. The pgvector container and SQL schema already exist — this task connects the new MCP server to them.

## Subtasks
- [ ] Add `psycopg2-binary` to `mcp_server/requirements.txt`
- [ ] Create `mcp_server/db.py`: connection pool using `POSTGRES_URL` env var, lazy init
- [ ] Run `setup_pgvector_local.sql` on startup if tables don't exist (idempotent)
- [ ] Implement `insert_document(chunk_text, embedding, metadata)` for ingestion
- [ ] Implement `search_documents(query_embedding, top_k, table)` using `match_crawled_pages()` and `match_code_examples()` SQL functions from the schema
- [ ] Confirm 768-dim vector column matches `nomic-embed-text` output (see comment in `setup_pgvector_local.sql`)
- [ ] Add `POSTGRES_URL` to `mcp.env.example` (e.g. `postgresql://captain:memex2026@pgvector:5432/circuitron`)
- [ ] Remove `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from `mcp.env.example`

## Done when
MCP server starts, connects to pgvector, and `search_documents()` returns results from previously ingested chunks.

## Notes
- pgvector service in `docker-compose.yml` is named `pgvector`, so within Docker the host is `pgvector` (port 5432); from the host machine it's `localhost:5434`
- The `setup_pgvector_local.sql` schema already has `ivfflat` indexes — run `ANALYZE` after bulk inserts for index to kick in

**Completed:** 2026-04-09

### CIRCUITRON-00E — Build local MCP server skeleton (SSE transport)

**Priority:** high

## Goal
Create `mcp_server/` as a self-contained Python package in this repo. It must speak the same SSE-based MCP protocol as the upstream container so the main app requires zero changes.

## Subtasks
- [ ] Create `mcp_server/` directory with `__init__.py`, `main.py`, `requirements.txt`
- [ ] Add FastAPI + `sse-starlette` dependencies
- [ ] Implement SSE endpoint at `/sse` (matches upstream path)
- [ ] Implement MCP handshake: `initialize` → `initialized` → tool listing
- [ ] Register the three tool stubs: `perform_rag_query`, `search_code_examples`, `query_knowledge_graph`
- [ ] Add a `Dockerfile` for the new server (base: `python:3.12-slim`)
- [ ] Wire the new service into `docker-compose.yml` as `mcp-local`, dependent on `pgvector`
- [ ] Confirm the main app connects and the tool list is returned correctly

## Done when
`circuitron --dev "test"` connects to the local MCP server, receives the three tools in the handshake, and proceeds without errors (even if tool results are empty stubs).

## Notes
- Upstream uses SSE transport with JSON-RPC 2.0 envelope — match exactly
- Port stays 8051 so `MCP_URL=http://localhost:8051` in `.env` needs no change
- The upstream `ghcr.io/shaurya-sethi/circuitron-mcp:latest` pull can be dropped from SETUP.md once this is working

**Completed:** 2026-04-09

### CIRCUITRON-00D — Patch MCP server to use DATABASE_URL (local Postgres)

**Priority:** high

## Goal
Wire the local pgvector Postgres (circuitron-pgvector on port 5434, from CIRCUITRON-00C)
into the MCP server so `circuitron setup` can populate the RAG store without a Supabase account.

## Context
The upstream image `ghcr.io/shaurya-sethi/circuitron-mcp:latest` uses `supabase-py` exclusively.
CIRCUITRON-007 designed a shim approach: `mcp/utils_local.py` replaces `src/utils.py` at image
build time, activating a `_PostgresClient` adapter when `DATABASE_URL` is set and falling back
to the Supabase client otherwise.

Repo: `/home/eric/circuitron-open`

## Files to create

### `mcp/utils_local.py`
Patched version of the upstream `/app/src/utils.py` (inspected from the Docker image).
Key changes:
- Add `_PostgresClient` / `_TableQuery` / `_RpcQuery` adapter classes (psycopg2-backed)
  that implement the same chainable API as `supabase-py` (`table()`, `insert()`, `delete()`,
  `eq()`, `in_()`, `execute()`, `rpc()`)
- `get_supabase_client()` — when `DATABASE_URL` is set, return a `_PostgresClient` instead
  of the real Supabase client
- `create_embeddings_batch()` — route to Ollama when `EMBEDDING_PROVIDER=ollama`
  (768-dim; use `/api/embed` batch endpoint, fall back to sequential `/api/embeddings`)
- All `[0.0] * 1536` fallbacks → `[0.0] * EMBEDDING_DIMENSIONS`
- `EMBEDDING_DIMENSIONS` inferred from known-model table, overridable via env
- `_validate_embedding_dimensions()` — raises ValueError with actionable message on mismatch

### `mcp/Dockerfile`
```dockerfile
FROM ghcr.io/shaurya-sethi/circuitron-mcp:latest
RUN pip install psycopg2-binary requests
COPY utils_local.py /app/src/utils.py
```
Extends the upstream image — no need to rebuild crawl4ai or sentence-transformers.

## mcp.env changes
Add clearly labelled sections (one to uncomment):
```
# --- Local path (pgvector on miso) ---
DATABASE_URL=postgresql://captain:memex2026@host.docker.internal:5434/circuitron
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://172.30.0.1:11434

# --- Cloud path (Supabase) ---
# SUPABASE_URL=...
# SUPABASE_SERVICE_KEY=...
```

## docker-compose.yml additions
Add `mcp-server` service (after pgvector from CIRCUITRON-00C):
```yaml
  mcp-server:
    image: ${MCP_IMAGE:-ghcr.io/shaurya-sethi/circuitron-mcp:latest}
    env_file: mcp.env
    ports:
      - "8051:8051"
    restart: unless-stopped
```
Set `MCP_IMAGE=circuitron-mcp-local` in `.env.local` to use the patched build.

## Done when
1. `docker build -t circuitron-mcp-local ./mcp` succeeds
2. `docker compose up -d` starts pgvector + mcp-server
3. `circuitron setup` completes without error (SKiDL docs crawled, rows in crawled_pages)
4. `SELECT count(*) FROM crawled_pages;` returns > 0

**Completed:** 2026-04-09

### CIRCUITRON-00C — Set up pgvector-enabled Postgres for MCP server

**Priority:** high

## Problem
The `postgres` container on miso runs `postgres:16-alpine` which does not include the pgvector extension. `CREATE EXTENSION vector` fails with "Could not open extension control file".

## Options

### Option A: Add pgvector service to docker-compose.yml (recommended)
Add a dedicated `pgvector/pgvector:pg16` container to Circuitron's `docker-compose.yml`:
```yaml
  pgvector:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: captain
      POSTGRES_PASSWORD: memex2026
      POSTGRES_DB: circuitron
    ports:
      - "5433:5432"   # different port to avoid conflict with existing postgres
    volumes:
      - pgvector_data:/var/lib/postgresql/data
    restart: unless-stopped
```
Then update `mcp.env` `DATABASE_URL` to point at this container.

### Option B: Install pgvector into the existing miso postgres container
```bash
# On miso:
docker exec postgres apt-get install -y postgresql-16-pgvector
# or build a custom image based on postgres:16-alpine + pgvector
```
Risk: modifies shared infrastructure used by other services.

### Option C: Migrate miso's main postgres to pgvector/pgvector:pg16 image
Swap the image in memex's docker-compose. Requires memex data migration.

## After choosing an option
Once pgvector Postgres is running, apply the schema:
```bash
# From circuitron repo root:
PGPASSWORD=memex2026 psql -h <host> -p <port> -U captain -d circuitron -f /tmp/setup_pgvector_768.sql
```
The 768-dim version of the schema is at `/tmp/setup_pgvector_768.sql` (generated during setup attempt on 2026-04-08).
Alternatively regenerate it: `sed 's/VECTOR(1536)/VECTOR(768)/g' setup_pgvector_local.sql > /tmp/setup_pgvector_768.sql`

Then update `mcp.env` `DATABASE_URL` accordingly and rebuild the MCP image:
```bash
docker build -t circuitron-mcp-local ./mcp
docker compose up -d
circuitron setup
```

## Done when
1. `CREATE EXTENSION IF NOT EXISTS vector` succeeds in the circuitron DB
2. Schema applies cleanly (all tables created, no type errors)
3. `docker compose up -d` starts all services
4. `circuitron setup` completes without error

**Completed:** 2026-04-09

### CIRCUITRON-00B — Memex knowledge retrieval MCP tool for Circuitron


## Goal
Give Circuitron agents access to the electronics knowledge base in memex via a retrieval tool.

## Status: Complete ✅

## Files delivered

| File | Changes |
|------|---------|
| `circuitron/tools.py` | New `retrieve_electronics_knowledge(query, project="kicad")` — GET `{MEMEX_API_URL}/search`, formats top 5 results as markdown (title, source, page, score, 400-char excerpt), returns `""` silently on any error or when `MEMEX_API_URL` unset |
| `circuitron/settings.py` | `memex_api_url: str` field (env `MEMEX_API_URL`, default `""`) |
| `circuitron/agents.py` | Tool wrapped and injected into planner, part-finder, and code-generation agents only when `settings.memex_api_url` is non-empty (zero overhead when not configured) |
| `circuitron/prompts.py` | One-line guidance added to `PLAN_PROMPT`, `PARTFINDER_PROMPT`, `CODE_GENERATION_PROMPT` |
| `.env.example` | Commented `MEMEX_API_URL=http://miso:8002` with description |
| `SETUP.md` | New "Memex electronics knowledge base" opt-in section |

## Note
memex-api on miso was already serving the `/search` endpoint — no changes needed on the memex side.

**Completed:** 2026-04-08

### CIRCUITRON-00A — Local embeddings provider for MCP server

**Priority:** high

## Goal
Allow the MCP server to generate embeddings locally via Ollama instead of calling the OpenAI API, completing the fully air-gapped setup.

## Status: Complete ✅

## Files delivered

| File | Changes |
|------|---------|
| `mcp/utils_local.py` | Module-level config block: `_EMBEDDING_PROVIDER`, `_EMBEDDING_MODEL`, `_EMBEDDING_BASE_URL`, `EMBEDDING_DIMENSIONS` (inferred from known-model table, overridable via env); `_validate_embedding_dimensions()` — raises ValueError with actionable fix message on mismatch; `_ollama_embed_batch()` — tries Ollama ≥0.3 batch `/api/embed`, falls back to sequential `/api/embeddings` for older versions; re-raises dimension errors immediately; `create_embeddings_batch()` routes to Ollama when `EMBEDDING_PROVIDER=ollama`, replaces hardcoded model name, all `[0.0]*1536` fallbacks → `[0.0]*EMBEDDING_DIMENSIONS` |
| `mcp/Dockerfile` | Added `requests` to pip install line (used by Ollama HTTP path) |
| `setup_pgvector_local.sql` | Dimension reference table in header with migration warning |
| `mcp.env.local.example` | Option A (Ollama, fully local) and Option B (OpenAI) embedding blocks, clearly separated |
| `SETUP.md` | Dimension table + migration note under local Postgres section |

**Completed:** 2026-04-08

### CIRCUITRON-009 — Docker Compose full stack


## Goal
One command (`docker compose up -d`) starts all Circuitron services. Combined with Ollama + miso pgvector, the full pipeline runs with zero cloud dependencies.

## Status: Complete ✅

## Files delivered

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Added `mcp-server` service with `${MCP_IMAGE:-ghcr.io/...}` so the local patched image swaps in via a single env var; `depends_on: neo4j: condition: service_healthy` so MCP waits for Neo4j. KiCad intentionally excluded (SDK-managed per-run). |
| `.env.local.example` | Sets `CIRCUITRON_PROVIDER=ollama`, `MCP_IMAGE=circuitron-mcp-local`, `NEO4J_URI=bolt://localhost:7687`. Only required value: `OLLAMA_BASE_URL` if Ollama is remote. Explains OpenAI embeddings caveat. |
| `mcp.env.local.example` | `DATABASE_URL` for miso Postgres, `NEO4J_URI=bolt://neo4j:7687` (compose-internal hostname), Neo4j credentials matching compose defaults. |
| `README.md` | New 7-step "Running locally (no cloud)" section before Prerequisites; updated stale silent-failure Neo4j note to reflect new startup check from CIRCUITRON-008. |

**Completed:** 2026-04-08

### CIRCUITRON-008 — Local Neo4j + startup check fix

**Priority:** high

## Goal
Run Neo4j locally via Docker Compose and eliminate the silent-failure bug where a missing Neo4j instance causes buried warnings instead of a hard startup error.

## Status: Complete ✅

## Files delivered

| File | Change | Purpose |
|------|--------|---------|
| `docker-compose.yml` | New | neo4j:5-community with Bolt/Browser ports, named volume, healthcheck. `docker compose up -d neo4j` is all that's needed. |
| `network.py` | Updated | `is_neo4j_available(uri)` — lightweight TCP socket probe on Bolt port (no neo4j driver dep); `verify_neo4j(ui)` — clear error + False if NEO4J_URI set but unreachable; silently passes if var absent (knowledge graph opt-out) |
| `cli.py` | Updated | `verify_neo4j()` called in both setup subcommand path and main pipeline startup, right after `verify_mcp_server()` |
| `.env.example` | Updated | `NEO4J_URI=bolt://localhost:7687` with comment pointing to docker compose |
| `SETUP.md` | Updated | New "Local Neo4j (Docker Compose)" section with 4-step guide and opt-out note for `USE_KNOWLEDGE_GRAPH=false` |

**Completed:** 2026-04-08

### CIRCUITRON-007 — Local vector store — pgvector on miso

**Priority:** high

## Goal
Make the MCP server's RAG layer work against the existing Postgres instance on miso (with pgvector extension) instead of Supabase cloud.

## Status: Complete ✅

## Finding
The upstream MCP server uses supabase-py exclusively — no DATABASE_URL support. A minimal patch was required.

## Files delivered

| File | Purpose |
|------|---------|
| `mcp/utils_local.py` | Patched `src/utils.py` — adds `_PostgresClient` / `_TableQuery` / `_RpcQuery` adapter that activates when `DATABASE_URL` is set; falls back to Supabase client otherwise |
| `mcp/Dockerfile` | Extends the upstream image, installs psycopg2-binary, copies the patched utils in |
| `setup_pgvector_local.sql` | Same schema as `setup_supabase.sql` without RLS (not needed for direct psycopg2 connections) |
| `mcp.env.example` | Clearly labelled `# Local path` / `# Cloud path` sections; uncomment one |
| `SETUP.md` | New "Option A: Local Postgres (pgvector)" section with full step-by-step, alongside existing Supabase "Option B" |

## Usage (miso)
```bash
# 1. Create DB + schema
psql -U postgres -c "CREATE DATABASE circuitron;"
psql -U postgres -d circuitron -f setup_pgvector_local.sql

# 2. Build patched image (once)
docker build -t circuitron-mcp-local ./mcp

# 3. Set DATABASE_URL in mcp.env, then run
docker run --env-file mcp.env -p 8051:8051 circuitron-mcp-local

# 4. Populate knowledge bases
circuitron setup
```

**Completed:** 2026-04-08

### CIRCUITRON-006 — Ollama LLM provider

**Priority:** high

## Goal
Add a fully local LLM provider backed by Ollama so Circuitron can run without any cloud API keys.

## Depends on
CIRCUITRON-005 (Anthropic provider + clean abstraction) must be complete.

## Implementation

### `circuitron/providers/ollama.py`
- Subclass or mirror `OpenAIAgentsProvider`, passing `base_url=f"{OLLAMA_BASE_URL}/v1"` and `api_key="ollama"` to the OpenAI Agents SDK
- Pull available models dynamically from `GET {OLLAMA_BASE_URL}/api/tags` at startup
- Warn (don't crash) if selected model is known to lack tool-calling support
- Register `"ollama"` as a valid value for `CIRCUITRON_PROVIDER`

### `circuitron/settings.py`
- Add `ollama_base_url: str = "http://localhost:11434"` (env: `OLLAMA_BASE_URL`)
- Add `"ollama"` to `available_providers` list

### `circuitron/network.py`
- Replace hardcoded `https://api.openai.com` ping with provider-aware check:
  - `ollama` provider → ping `{ollama_base_url}/api/tags` (confirms Ollama is reachable)
  - `openai-agents` → existing check
  - `anthropic` → ping `https://api.anthropic.com`
- Full offline: if all configured providers are local, skip internet check entirely

### `circuitron/cost_estimator.py`
- Return `$0.00` for any model served by the Ollama provider
- Update pricing display to show "local" instead of a dollar amount

## Done when
1. Full pipeline completes with `CIRCUITRON_PROVIDER=ollama` and a tool-capable model (e.g. `qwen2.5-coder:32b`)
2. `OLLAMA_BASE_URL` is respected; works with Ollama on localhost or a remote server
3. Connectivity check does not ping OpenAI when provider is `ollama`
4. Cost estimate shows `$0.00` (or "local") for Ollama runs

**Completed:** 2026-04-08

### CIRCUITRON-005 — Implement Anthropic provider adapter

**Priority:** low

## Goal
Create `circuitron/providers/anthropic.py` as a second provider to validate the abstraction.

## Status: In Progress 🔄

The provider file exists and the core implementation is solid, but two features are incomplete and the whole provider is blocked by CIRCUITRON-004 (consumer files still import OpenAI types directly, causing crashes before the Anthropic provider even runs).

## What's done ✅
- `AnthropicProvider` class implementing `LLMProvider` protocol
- Custom tool wrapping and JSON schema generation (lines 248-333)
- Async tool execution helper (lines 339-350)
- JSON extraction helper (lines 352-357)
- Zero OpenAI SDK imports

## Remaining issues

### MCP support (line 220-231)
- `make_mcp_server()` raises `NotImplementedError`
- Anthropic SDK does support MCP natively — needs implementation
- Blocked by: `mcp_manager.py` hardcodes `OpenAIAgentsProvider.make_mcp_server()` (fix in CIRCUITRON-004)

### Guardrails (line 118)
- `input_guardrails` kwarg silently stored in `extra` dict, never processed
- No guardrail enforcement when using Anthropic provider — silent security gap
- Fix: implement a pre-flight relevance check using a cheap model call before running the main agent

## Blocked by
- CIRCUITRON-004 must be completed before end-to-end testing is possible

## Done when
- Full pipeline runs end-to-end with `CIRCUITRON_PROVIDER=anthropic`
- MCP connection works
- Guardrails enforced (or explicitly documented as not supported)
- Token usage telemetry maps Anthropic usage fields correctly

**Completed:** 2026-04-08

### CIRCUITRON-004 — Wire provider factory and inject into pipeline

**Priority:** high

## Goal
Replace direct SDK imports in consumer files with injected `LLMProvider` calls.

## Status: Complete ✅

### Files fixed
- **agents.py** — removed `Agent, Tool, ModelSettings` imports; uses `AgentHandle`, `ModelConfig`, `list[Any]`
- **pipeline.py** — removed `from agents import Agent` and `from agents.result import RunResult`; uses `Any`
- **mcp_manager.py** — replaced `OpenAIAgentsProvider.make_mcp_server()` with `get_provider(settings).make_mcp_server()`
- **debug.py** — removed all SDK imports; uses `_provider.display_run_items()`, `_provider.guardrail_tripwire_type()`, `_provider.api_error_type()`
- **prompts.py** — replaced `agents.extensions.handoff_prompt` import with plain empty string constant
- **guardrails.py** — restructured `pcb_query_guardrail` as plain `_pcb_check(input_data) -> bool`; `pcb_query_guardrail = _provider.make_guardrail(_pcb_check)`
- **utils.py** — removed `ReasoningItem`, `RunResult` imports; `extract_reasoning_summary()` delegates to `_provider.extract_reasoning()`
- **setup_agent.py** — bonus fix; was also importing `Agent, ModelSettings, OpenAIAgentsProvider` directly

### Protocol additions (provider.py + both providers)
- `ModelConfig` dataclass replaces `ModelSettings` at call sites
- `make_mcp_server()` — instance method on both providers
- `make_guardrail(check_fn)` — OpenAI wraps with `@input_guardrail`; Anthropic is a no-op stub
- `guardrail_tripwire_type()` — returns correct exception class per provider
- `display_run_items(result)` — provider-specific debug output
- `extract_reasoning(result)` — provider-specific reasoning extraction

### AnthropicRunResult
- Added `final_output` property aliasing `.output` so `result.final_output` works in pipeline.py without provider-awareness

## Verification
`grep` for SDK imports outside `providers/` returns zero results.

**Completed:** 2026-04-07

### CIRCUITRON-003 — Implement OpenAI Agents provider adapter

**Priority:** high

## Goal
Create `circuitron/providers/openai_agents.py` implementing `LLMProvider` with the current SDK behavior.

## Status: Complete ✅
- All `agents.*` and `openai.*` imports confined to this file
- Protocol correctly implemented
- Clean `__all__` export list (lines 131-146)
- `make_mcp_server()` as static method works correctly
- Re-exports types (`RunResult`, `APIError`, etc.) for use by other files

## Review notes
No issues found within the provider file itself. The problem is that consumer files (`agents.py`, `pipeline.py`, etc.) import these re-exported types directly rather than staying provider-agnostic — see CIRCUITRON-004.

**Completed:** 2026-04-07

### CIRCUITRON-002 — Refactor tools.py — strip @function_tool decorator

**Priority:** high

## Goal
Convert all agent tools to plain Python functions; let the provider wrap them at agent-creation time.

## Status: Complete ✅
- `@function_tool` decorator removed from all tools
- No `agents` or `openai` imports in `tools.py`
- Provider's `wrap_tool()` is used correctly
- Tool logic (Docker, KiCad) unchanged

## Review notes
No issues found.

**Completed:** 2026-04-07

### CIRCUITRON-001 — Define LLMProvider protocol

**Priority:** high

## Goal
Create `circuitron/provider.py` defining a `LLMProvider` protocol that abstracts all SDK-specific calls.

## Status: Complete ✅
- `AgentHandle` protocol defined as empty Protocol
- `LLMProvider` protocol with all 6 methods, fully type-hinted
- `TypeVar` used for generic `extract_output()`
- Zero SDK imports
- Good docstrings

## Review notes
No issues found. This file is the cleanest part of the refactor.

**Completed:** 2026-04-07

---
