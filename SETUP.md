# circuitron-open Setup Guide

This is a dedicated guide to getting the dependencies for the project set up.

Tip: After you configure and start the MCP server (see [Option A](#option-a-local-postgres-pgvector) for local pgvector or [Option B](#option-b-supabase-cloud) for Supabase cloud), you can initialize Circuitron’s knowledge bases directly via the built-in command:

```bash
circuitron setup
```

This is idempotent and should be run once per environment. It uses the MCP tools `smart_crawl_url` and `parse_github_repository` to populate Supabase and Neo4j respectively. You can also trigger it from the interactive UI by typing `/setup`.

## Table of Contents

1. [Docker Setup](#docker-setup)
2. [MCP Server Setup](#mcp-server-setup)
   - [Option A: Local Postgres (pgvector) — no Supabase account](#option-a-local-postgres-pgvector)
   - [Option B: Supabase cloud](#option-b-supabase-cloud)
3. [Setting up AI Assistant for Knowledge Base Population](#setting-up-ai-assistant-for-knowledge-base-population)
4. [Populating Knowledge Bases](#populating-knowledge-bases)
5. [Additional Notes on OpenAI API](#additional-notes-on-openai-api)

## Docker Setup

First make sure you have docker installed on your machine.

Then run the following commands to pull the required docker images:

```bash
docker pull ghcr.io/shaurya-sethi/circuitron-kicad:latest
docker pull ghcr.io/shaurya-sethi/circuitron-mcp:latest
docker pull python:3.12-slim
```

## Node.js Dependencies

Circuitron requires the `netlistsvg` package for generating SVG diagrams from netlists. Install it using npm:

```bash
npm install https://github.com/nturley/netlistsvg
```

**Note:** Ensure you have Node.js and npm installed on your system. If not, download and install from https://nodejs.org/.

## MCP Server Setup

There are two ways to provide the vector store for the MCP server. Choose one.

---

### Option A: Local Postgres (pgvector)

Use this if you already run PostgreSQL (e.g. on a home server) and want to avoid
creating a Supabase account.

**Prerequisites**

- PostgreSQL 14+ with the [pgvector](https://github.com/pgvector/pgvector) extension.
  On Ubuntu/Debian: `sudo apt install postgresql-<ver>-pgvector`
- The `circuitron-mcp-local` Docker image (built below).

**Step A1 — Create the database and schema**

```bash
# Create a database (if it doesn't exist yet)
psql -U postgres -c "CREATE DATABASE circuitron;"

# Apply the schema (creates tables + vector search functions, no Supabase required)
psql -U postgres -d circuitron -f setup_pgvector_local.sql
```

**Step A2 — Build the patched MCP image**

The upstream `circuitron-mcp` image uses the Supabase Python client exclusively.
A minimal patch in `mcp/utils_local.py` adds a psycopg2 adapter that activates
when `DATABASE_URL` is set. Build it once:

```bash
docker build -t circuitron-mcp-local ./mcp
```

**Step A3 — Create `mcp.env`**

Copy `mcp.env.example` to `mcp.env` and fill in the `DATABASE_URL` block:

```env
TRANSPORT=sse
HOST=0.0.0.0
PORT=8051
OPENAI_API_KEY=<your OpenAI API key>
MODEL_CHOICE=gpt-5-nano
USE_CONTEXTUAL_EMBEDDINGS=true
USE_HYBRID_SEARCH=true
USE_AGENTIC_RAG=true
USE_RERANKING=true
USE_KNOWLEDGE_GRAPH=true
LLM_MAX_CONCURRENCY=2
LLM_REQUEST_DELAY=0.5

# Local Postgres — uncomment and fill in:
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/circuitron

# Neo4j (local or cloud):
NEO4J_URI=bolt://host.docker.internal:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your Neo4j password>
```

**Step A4 — Run the patched server**

```bash
docker run --env-file mcp.env -p 8051:8051 circuitron-mcp-local
```

Then run `circuitron setup` (or type `/setup` in the UI) to populate the knowledge
bases. No Supabase credentials are needed.

> **Embedding dimensions:** The default embedding model is OpenAI `text-embedding-3-small`
> (1536 dimensions). If you switch to a local Ollama model, you **must** update the
> `vector(1536)` column definitions in `setup_pgvector_local.sql` to match the model's
> dimension before running the schema, then set `EMBEDDING_DIMENSIONS` in `mcp.env`:
>
> | Model | Dimensions |
> |---|---|
> | `nomic-embed-text` | 768 |
> | `mxbai-embed-large` | 1024 |
> | `all-minilm` | 384 |
> | `bge-m3` | 1024 |
>
> Changing dimensions requires dropping and recreating all vector tables and
> re-running `circuitron setup`. See `mcp.env.local.example` for the full config.

> **Note on USE_KNOWLEDGE_GRAPH**: the knowledge graph feature still requires Neo4j.
> For a fully local stack, run Neo4j locally and set
> `NEO4J_URI=bolt://host.docker.internal:7687`. To disable the knowledge graph
> entirely, set `USE_KNOWLEDGE_GRAPH=false` in `mcp.env`.

---

### Option B: Supabase cloud

Use this if you prefer a managed cloud setup.

### Step 1: Get API credentials for the MCP server

The MCP server requires an OpenAI API key for its internal LLM and embedding calls. This is separate from the main app's LLM provider — you need it regardless of which provider (`openai-agents` or `anthropic`) you use for the main pipeline.

Obtain an OpenAI API key from https://platform.openai.com/signup. You will need to add some credits to the account.

> **If you are using Anthropic for the main app:** you still need OpenAI here, for the MCP server only. This limitation will be removed when MCP server provider abstraction is implemented.

### Step 2: Create Supabase Account and Project

Create a supabase account at https://supabase.com/

- Go to your dashboard and create a new project. (Follow the instructions on the website - they will guide you through the process and are very straightforward.)
- Then, go to the project settings → API Keys → service_role key and copy it.
- In the same project settings, under the CONFIGURATION tab, go to Data API → And copy your project URL.

**Important:** Once this is done, please go to the "SQL Editor" and then paste the contents of the `setup_supabase.sql` file from the repository into the SQL editor and run it. This will create the required tables in your Supabase database.

### Step 3: Create Neo4j Database


Create a neo4j database on Neo4j Aura cloud service https://neo4j.com/cloud/aura/

(Or you can use a local Neo4j instance, but the cloud service is recommended for ease of use if you are unfamiliar with neo4j and don't already use it locally.)

**If you are using a local Neo4j instance, use this exact URI for the connection:**

```
bolt://host.docker.internal:7687
```

- Once you have created a database, go to the database settings and copy the connection URI, username, and password.

### Step 4: Create mcp.env File

Create a mcp.env file in the root directory of the project and add the following environment variables:

```env
TRANSPORT=sse
HOST=0.0.0.0
PORT=8051
OPENAI_API_KEY=<your OpenAI API key>
MODEL_CHOICE=gpt-5-nano
USE_CONTEXTUAL_EMBEDDINGS=true
USE_HYBRID_SEARCH=true
USE_AGENTIC_RAG=true
USE_RERANKING=true
USE_KNOWLEDGE_GRAPH=true
LLM_MAX_CONCURRENCY=2
LLM_REQUEST_DELAY=0.5
SUPABASE_URL=<your Supabase project URL>
SUPABASE_SERVICE_KEY=<your Supabase service_role key>
NEO4J_URI=<your Neo4j URI>
NEO4J_USER=<your Neo4j username>
NEO4J_PASSWORD=<your Neo4j password>
```

Here, you will need to replace the placeholders with the actual values you obtained in the previous steps. Don't change other values.

### Step 5: Run the MCP Server

Now you can run the MCP server using the following command:

```bash
docker run --env-file mcp.env -p 8051:8051 ghcr.io/shaurya-sethi/circuitron-mcp:latest
```

To confirm that the server is running, you can open logs in docker desktop and check for the following:

```
2025-08-01 11:54:15
INFO: Started server process [1]
2025-08-01 11:54:15
INFO: Waiting for application startup.
2025-08-01 11:54:15
INFO: Application startup complete.
2025-08-01 11:54:15
INFO: Uvicorn running on http://0.0.0.0:8051⁠ (Press CTRL+C to quit)
2025-08-01 11:54:18
INFO: 172.17.0.1:48912 - "GET /sse HTTP/1.1" 200 OK
```

---

## Setting up AI Assistant for Knowledge Base Population (Optional in case `/setup` does not work)

Now let's add this mcp server to your favourite coding agent so it can assist you with setting up the knowledge bases for circuitron.

### For (VSCode) Github Copilot:

- Open the chat sidebar by clicking on the Copilot icon in the Activity Bar on the side of the window.
- Select **Configure Tools → (Scroll all the way down) Add More Tools… → Add MCP Server → HTTP** and enter the URL `http://localhost:8051/sse`. That's it, you should now see the MCP server and its tools listed under the same Configure Tools menu. (Just make sure that they are enabled by checking the checkboxes next to them.)

### For Cline

- Open the Cline chat interface, and click on the icon at the bottom that says "Manage MCP Servers".
- In this, click on the gear icon at the top right to open settings.
- Go to Remote Servers and then add a name for the server (e.g., "Circuitron MCP") and the URL `http://localhost:8051/sse`.
- Click on Add Server. Now Cline should be able to make use of this MCP server to assist you with setting up the knowledge bases for circuitron.

**Note:** With Cline, you can make use of the following **free** model providers' apis: 
- Gemini api is free to use and you just need to get the key from https://aistudio.google.com/apikey
  - For gemini use gemini 2.5 pro or flash
- The Mistral API also has a free tier which you can use by signing up at https://mistral.ai/products/la-plateforme → "Try the API"
  - for mistral use devstral medium

This is just general advice and you can use these apis for free with cline while coding your own projects :)

### For Other IDEs/Coding Agents

Both these are popular free extensions for VSCode, which itself is a popular IDE that most people use. If you are using a different IDE/coding agent (like cursor, gemini-cli, claude code, etc) please refer to their documentation on how to add a custom MCP server. The URL will be the same as above: `http://localhost:8051/sse`. (This should be easy to do but if you're unfamiliar with anything, please just install cline or copilot and follow the above steps, as they are very straightforward and easy to use.)

## Populating Knowledge Bases

Now we can ask our agent to help us set up the knowledge bases for circuitron.

### Step 1: Crawl SKiDL Documentation

Instruct the agent to crawl `https://devbisme.github.io/skidl/` to build the SKiDL documentation corpus.

The agent will use the MCP tool `smart_crawl_url` to parse the documentation and create a knowledge base for SKiDL. (This may take just a few minutes so please be patient.)

**Note:** Sometimes, using models like GPT 4.1 in model selection in copilot may cause the agent to not use the MCP tool. If this happens, try using a different model like claude 4 or be more explicit in your instructions to the agent, such as "Use the MCP tool `smart_crawl_url` to parse the URL `https://devbisme.github.io/skidl/` and create a knowledge base for SKiDL documentation." This should help the agent understand that it needs to use the MCP tool for this task.

At any given point, the agent should NOT be making custom crawling scripts. Please post any issues you face with this in Discussions or create an issue on the GitHub repository.

### Step 2: Parse GitHub Repository

Next, instruct it to parse the GitHub repository `https://github.com/devbisme/skidl` to populate the knowledge graph. For this, the agent should use the `parse_github_repository` MCP tool.

This concludes the dependencies setup for Circuitron. Now you can start using Circuitron as mentioned in the README.md file, but just ensure that the MCP server is running in the background.

### Maintenance: Keep SKiDL Knowledge Base Up to Date

- Why: Major SKiDL releases can include breaking changes, deprecations, or new features that Circuitron can use. Rebuild the SKiDL knowledge bases after such releases.
- When: After any major SKiDL release, or whenever you notice API/behavior changes.
- Check version: Visit https://pypi.org/project/skidl/ or the GitHub releases, or run `python -c "import skidl; print(skidl.__version__)"` / `pip show skidl` locally.

Refresh procedure (clean rebuild):
1. Stop the MCP server if it is running.
2. Delete previously ingested SKiDL corpus so you start clean, then repopulate:
   - Supabase: remove/truncate the SKiDL documentation and embedding records that were created during the crawl.
   - Neo4j: delete nodes/relationships that were created for the SKiDL docs knowledge graph.
   - If you’re unsure what to remove, you can create a fresh Supabase project and/or a new Neo4j database for a clean slate.
3. Start the MCP server again.
4. Re-run the steps in “Populating Knowledge Bases” for SKiDL:
   - Step 1: Crawl SKiDL Documentation (`smart_crawl_url`).
   - Step 2: Parse GitHub Repository (`parse_github_repository`).

Important: Always delete the existing SKiDL knowledge base contents before repopulating to avoid mixing old and new documentation.

## Local Neo4j (Docker Compose)

If you are using the local pgvector path (Option A) or simply want to avoid a
cloud Neo4j account, you can run Neo4j locally with Docker Compose.

**Step 1 — Start Neo4j**

```bash
docker compose up -d neo4j
```

This starts Neo4j 5 Community Edition on the standard ports:

| Port | Purpose |
|------|---------|
| 7687 | Bolt (driver/tool connections) |
| 7474 | Neo4j Browser (web UI) |

Data is persisted in a named Docker volume (`neo4j_data`).

**Step 2 — Configure credentials in `mcp.env`**

```env
NEO4J_URI=bolt://host.docker.internal:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=circuitron   # matches NEO4J_PASSWORD in .env (default: circuitron)
```

`host.docker.internal` resolves to the host from inside a Docker container.  If
running the MCP server outside Docker, use `bolt://localhost:7687` instead.

**Step 3 — Add `NEO4J_URI` to `.env`**

Circuitron checks Neo4j reachability at startup (when `NEO4J_URI` is set).  Add
it to your `.env` so the check runs:

```env
NEO4J_URI=bolt://localhost:7687
```

**Step 4 — Populate the knowledge graph**

```bash
circuitron setup
```

This calls the MCP `parse_github_repository` tool to populate the local Neo4j
instance with the SKiDL knowledge graph.

**Opting out of the knowledge graph**

Set `USE_KNOWLEDGE_GRAPH=false` in `mcp.env` and omit `NEO4J_URI` from `.env`.
The RAG documentation corpus will still work; only the graph-based validation
features will be disabled.

---

## Additional Notes on LLM Provider Configuration

### Using Anthropic Claude (no OpenAI required for the main app)

Set `CIRCUITRON_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=<key>` in your `.env`. No OpenAI key is needed for the main pipeline. Note: the MCP server container still requires `OPENAI_API_KEY` in `mcp.env` until MCP server provider abstraction is implemented.

Update the default model names in `circuitron/settings.py` to Anthropic model IDs (e.g. `claude-sonnet-4-5`, `claude-opus-4-5`) when using this provider.

### Using OpenAI (upstream default)

You will need an OpenAI API key. Set `CIRCUITRON_PROVIDER=openai-agents` (this is the default if unset) and `OPENAI_API_KEY=<key>` in your `.env`.

#### Organization Verification

Reasoning models like `o4-mini` require [organization verification](https://help.openai.com/en/articles/10910291-api-organization-verification) on OpenAI. If you prefer to skip this, change the default model in `circuitron/settings.py` to `gpt-4.1`:

```python
code_generation_model: str = field(default="gpt-4.1")
```

Using `gpt-4.1-mini` or `nano` may reduce performance; `gpt-4.1` may increase cost and hit rate limits on low-credit accounts.

#### Cost Optimization (OpenAI)

Enabling data sharing on OpenAI's platform grants additional free daily usage and reduces effective cost significantly.

---

Hope this helps you get started with circuitron-open! If you have any questions or run into issues, feel free to open an issue on the GitHub repository.

## Memex electronics knowledge base (optional)

If you run [memex](https://github.com/erictheechidna/memex) with an electronics
collection (datasheets, application notes), Circuitron can query it during planning,
part selection, and code generation.

Set `MEMEX_API_URL` in `.env`:

```env
MEMEX_API_URL=http://miso:8002
```

When this variable is set, the planner, part-finder, and code-generation agents
gain a `retrieve_electronics_knowledge` tool that queries
`GET {MEMEX_API_URL}/search?q=...&project=kicad&n=5` and formats the top results
as markdown context.  The tool silently returns nothing if memex is unreachable —
it is never a hard dependency and does not require `circuitron setup` to work.

---

## Pricing and Cost Estimation

Circuitron ships with built-in default prices in `circuitron/model_prices_builtin.py` so cost estimates work out of the box.

Override options (highest precedence first):

1. Create `circuitron/_model_prices_local.py` with:

   ```python
   PRICES = {
     "gpt-5-mini": {"input": 0.25, "output": 2.0, "cached_input": 0.025},
     # ...
   }
   ```

2. Or set `CIRCUITRON_PRICES_FILE=C:/path/to/prices.json` where the JSON is `{ model: { input, output, cached_input } }`.

3. Otherwise, built-in defaults are used. To disable them set `CIRCUITRON_DISABLE_BUILTIN_PRICES=1`.

