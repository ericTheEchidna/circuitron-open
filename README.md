# circuitron-open

> **Fork of [Shaurya-Sethi/circuitron](https://github.com/Shaurya-Sethi/circuitron)** — vendor-agnostic by design. The upstream project is hard-coded to OpenAI, Supabase, and Neo4j. This fork introduces a provider abstraction layer so the LLM backend is swappable via a single environment variable.

Circuitron is an agent-driven PCB design accelerator that converts natural language requirements into SKiDL scripts, KiCad schematics, and PCB layout files. It integrates a multi-agent pipeline with reasoning and retrieval-augmented capabilities.

---

![Demo of Circuitron in Action](assets/circuitron-demo.gif)

---

## What's different from upstream

- **LLM provider abstraction** — a `LLMProvider` protocol (`circuitron/provider.py`) defines a stable interface. Two full implementations exist today: `openai-agents` and `anthropic`. Switch between them with one environment variable (`CIRCUITRON_PROVIDER`). No code changes required.
- **No forced OpenAI dependency for the main app** — if you supply `ANTHROPIC_API_KEY` and set `CIRCUITRON_PROVIDER=anthropic`, the main pipeline runs entirely on Anthropic Claude with no OpenAI calls.
- **MCP server is still upstream** — the MCP server container (RAG, knowledge graph, embeddings) is unchanged from upstream and still uses OpenAI for embeddings and LLM calls, Supabase for vector/doc storage, and Neo4j for the knowledge graph. Abstracting the MCP server is on the roadmap but not yet implemented. See [Supported Providers](#supported-providers).

## Features

- **Provider-agnostic agent orchestration** — planning, part discovery, code generation, validation, and error correction all run through the `LLMProvider` interface.
- **Retrieval-Augmented Generation (RAG)** — a dedicated MCP (Model Context Protocol) server surfaces relevant SKiDL documentation and examples to the LLM at every design step.
- **Real part selection** — queries KiCad libraries via Docker to ensure chosen components exist and match the specification.
- **Automatic schematic and PCB generation** — produces `.sch` and `.kicad_pcb` files alongside netlists and SVG schematic previews for direct use in KiCad.
- **Iterative correction loop** — agents validate generated code, apply fixes, and run ERC checks until a clean design is produced.
- **Containerized toolchain** — Docker images for KiCad, the MCP server, and the Python execution environment guarantee repeatable results.

## Architecture Overview

The pipeline uses dedicated agents for each design step:

1. **Planner** — break down the prompt into design tasks.
2. **Plan editor** — incorporate user feedback.
3. **Part finder** — search KiCad libraries for components.
4. **Part selector** — choose optimal parts.
5. **Documentation agent** — fetch SKiDL references via the MCP server.
6. **Code generator** — write SKiDL code based on the plan and documentation.
7. **Validator and corrector** — detect issues, use the knowledge graph, and fix problems.
8. **Runtime correction** — ensure the script executes correctly.
9. **ERC handler** — resolve electrical rule check warnings.
10. **Execution step** — output schematic, netlist, PCB file, and an SVG preview.

All agents are created through the active `LLMProvider`, so they are decoupled from any specific SDK.

The MCP server provides RAG and knowledge graph lookups. It runs as a separate Docker container and communicates with the main app over HTTP. In its current form it requires Supabase and Neo4j; the main Circuitron app never imports their SDKs directly.

## Architecture Diagram

<p align="center">
  <img src="assets/circuitron_architecture_light.png" alt="Circuitron Architecture Diagram" width="1400"/>
</p>

## Supported Providers

### Main application (LLM orchestration)

| Provider | Status | Env var value |
|---|---|---|
| OpenAI (via Agents SDK) | Implemented | `openai-agents` |
| Anthropic Claude | Implemented | `anthropic` |
| Ollama (local) | Planned | — |
| Gemini, other OpenAI-compatible APIs | Planned | — |

Set the provider with `CIRCUITRON_PROVIDER=<value>` in your `.env` file.

### MCP server (RAG, embeddings, knowledge graph)

The MCP server is a separate container inherited from upstream. Its internal dependencies are not yet abstracted:

| Component | Current | Planned |
|---|---|---|
| Embeddings / LLM | OpenAI | Configurable |
| Vector / doc store | Supabase | Configurable |
| Knowledge graph | Neo4j | Configurable |

Until the MCP server is abstracted, running the full pipeline requires OpenAI API access (for the MCP server), Supabase, and Neo4j — even if the main app is running on Anthropic.

## Prerequisites

- **Python 3.10+** (developed with 3.12)
- **Node.js and npm** — required for `netlistsvg`
- **Docker** with permission to run containers
- **LLM provider credentials** — see [Configuration](#configuration) below
- **Supabase account** — used by the MCP server ([sign up](https://supabase.com/))
- **Neo4j database** — free instances available from [AuraDB](https://neo4j.com/cloud/platform/aura-graph-database/) or run locally

> **Note on the MCP server:** Until MCP server provider abstraction is implemented, you will need OpenAI API access for the MCP server regardless of which provider you use for the main app.

## Installation

```bash
pip install -e .
```

```bash
npm install https://github.com/nturley/netlistsvg
```

This installs `openai-agents`, `anthropic`, `python-dotenv`, `skidl`, `rich`, and `logfire`. Tracing with Pydantic Logfire is enabled by default. A `requirements.txt` mirroring `pyproject.toml` is included for convenience.

## Setup

> For detailed setup instructions see [SETUP.md](SETUP.md).

### 1. Pull required Docker images

```bash
docker pull ghcr.io/shaurya-sethi/circuitron-kicad:latest
docker pull ghcr.io/shaurya-sethi/circuitron-mcp:latest
docker pull python:3.12-slim
```

### 2. Create a `.env` file

Copy `.env.example` to `.env`. Set the variables appropriate to your chosen LLM provider:

**Using Anthropic Claude:**
```env
CIRCUITRON_PROVIDER=anthropic
ANTHROPIC_API_KEY=<your Anthropic API key>
MCP_URL=http://localhost:8051
```

**Using OpenAI:**
```env
CIRCUITRON_PROVIDER=openai-agents
OPENAI_API_KEY=<your OpenAI API key>
MCP_URL=http://localhost:8051
```

Full list of optional overrides:

| Variable | Default | Description |
|---|---|---|
| `CIRCUITRON_PROVIDER` | `openai-agents` | LLM provider: `openai-agents` or `anthropic` |
| `MCP_URL` | `http://localhost:8051` | MCP server endpoint |
| `KICAD_IMAGE` | `ghcr.io/shaurya-sethi/circuitron-kicad:latest` | KiCad Docker image |
| `CALC_IMAGE` | `python:3.12-slim` | Python execution image |
| `CIRCUITRON_MAX_TURNS` | `50` | Agent loop turn limit |
| `CIRCUITRON_NETWORK_TIMEOUT` | `300` | Network timeout in seconds |
| `LOGFIRE_TOKEN` | — | Pydantic Logfire token (tracing always enabled) |
| `CIRCUITRON_PRICES_FILE` | — | Path to a JSON pricing override file |
| `CIRCUITRON_DISABLE_BUILTIN_PRICES` | — | Set to `1` to disable built-in cost estimates |

### 3. Create `mcp.env` for the MCP server

The MCP server still requires OpenAI credentials and Supabase/Neo4j connections:

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

### 4. Run the MCP server

```bash
docker run --env-file mcp.env -p 8051:8051 ghcr.io/shaurya-sethi/circuitron-mcp:latest
```

### 5. Prepare the MCP database

- Run the SQL schema in `setup_supabase.sql` against your Supabase project via the SQL Editor.
- Provide your Neo4j credentials in `mcp.env`.

### 6. Populate the knowledge base

With the MCP server running:

```bash
circuitron setup
```

This crawls SKiDL documentation and parses the SKiDL repository to populate the knowledge base. It is idempotent and only needs to be run once per environment.

## Usage

With the MCP server running and Docker images available:

```bash
# Interactive mode
circuitron

# One-shot prompt
circuitron "Design a voltage divider"

# Save the generated SKiDL script
circuitron --keep-skidl "Design a 12V to 5V buck converter"

# Write outputs to a specific directory
circuitron --output-dir ./my-designs "Design a voltage divider"

# Enable verbose debug output
circuitron --dev "Design a voltage divider"
```

> **Note:** Use `--no-footprint-search` to disable footprint searches. SVG and netlist generation are more reliable without it. Footprint search can produce PCB layouts when it works, but the pipeline sometimes fails on hallucinated footprint names.

> **Before running:** Ensure Neo4j is reachable and your Supabase project is not paused (free-tier projects pause after a few days of inactivity). Circuitron will detect a missing MCP server and warn you before proceeding.

### Model switching

Use the `/model` command in interactive mode to switch models for the current session. The default is `o4-mini` when using the OpenAI provider. When using Anthropic, set model names in `.env` or override at the `Settings` level in `circuitron/settings.py`.

Available OpenAI models: `o4-mini`, `gpt-5-mini`, `gpt-5`, `gpt-5-nano`, `gpt-4.1`, `o3`, `o3-pro`

## Cost Estimation and Pricing

Circuitron estimates token cost using built-in defaults in `circuitron/model_prices_builtin.py`. Override options (highest precedence first):

1. Create `circuitron/_model_prices_local.py` with `PRICES = { ... }`
2. Set `CIRCUITRON_PRICES_FILE=/absolute/path/prices.json`
3. Built-in defaults are used otherwise. Disable with `CIRCUITRON_DISABLE_BUILTIN_PRICES=1`.

Estimates are conservative — cache hits and data-sharing credits are not factored in.

## Example Output

**Design query:**
```
Design a 12V to 5V buck converter using LM2596.
```

**Schematic Preview:**
<p align="center">
  <img src="assets/buck_converter.jpg" alt="Buck Converter Schematic" width="500"/>
</p>

See the original README or `docs/` for extended examples including generated SKiDL code and netlists.

## Running Tests

```bash
pytest -q
```

## Troubleshooting

- **MCP server not reachable** — ensure the container is running with the correct `mcp.env` and that port 8051 is accessible.
- **KiCad container fails to start** — re-pull the image: `docker pull ghcr.io/shaurya-sethi/circuitron-kicad:latest`
- **Missing provider credentials** — the CLI exits with an error if the required API key for the selected provider is not set. Check your `.env`.
- **Anthropic provider: model names** — Anthropic model names differ from OpenAI. If you switch to `CIRCUITRON_PROVIDER=anthropic`, update model names in `circuitron/settings.py` (e.g. `claude-opus-4-5`, `claude-sonnet-4-5`) or they will be passed as-is to the Anthropic API.

## Contributing

Contributions are welcome — open issues or pull requests on the repository. See `AGENTS.md` for coding guidelines and `overview.md` for architecture background.

Priority areas for contribution:
- MCP server provider abstraction (embeddings, vector store, graph DB)
- Ollama provider implementation
- Model name management per provider

> **GitHub repo rename:** To rename the repository on GitHub, go to **Settings → General → Repository name** and update it to `circuitron-open`. This must be done manually — the git remote in your local clone will need to be updated afterward with `git remote set-url origin <new-url>`.

## License

MIT License. This project is a fork of [Shaurya-Sethi/circuitron](https://github.com/Shaurya-Sethi/circuitron), also MIT licensed.
