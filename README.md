# StandardGraph

**20,000+ math standards across 75+ curriculum systems, accessible via Claude.**

Ask Claude to look up any standard, trace a concept across grade levels, or find the equivalent of a standard in another country's curriculum — all from a single MCP server.

---

## Install

Requires [Claude Desktop](https://claude.ai/download). Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

Then **quit and reopen Claude Desktop**. Look for the 🔨 icon in a new conversation.

> The installer handles everything: downloads the pre-built database (~200 MB), installs dependencies, and patches your Claude config automatically.

**Try it:**
```
List all available curriculum systems
```
```
How does CCSS build fractions from grade 3 to 6?
```
```
What's the Singapore equivalent of CCSS.MATH.6.RP.A.3?
```

→ Full install guide: [docs/install.md](docs/install.md)

---

## Coverage

| Region | Systems |
|---|---|
| 🇺🇸 United States | `ccss` + all 50 states + DC (CCSS is the crosswalk hub) |
| 🇨🇦 Canada | `ca-ab` `ca-bc` `ca-on` `ca-mb` `ca-sk` `ca-nb` `ca-qc` |
| 🌍 International | `cambridge` `ib-myp` `ib-dp` `aero` `dodea` |
| 🇦🇺 Australia | `au-acara` `au-vic` |
| 🇬🇧 United Kingdom | `uk-nc` `uk-aqa` `gb-sco` |
| 🇸🇬 Singapore | `sg-moe` |
| 🇯🇵 Japan | `jp-mext` |
| 🇳🇿 New Zealand | `nz-moe` |
| 🇮🇪 Ireland | `ie-ncca` |
| 🇭🇰 Hong Kong | `hk-edb` |
| 🇮🇳 India | `in-ncert` |
| 🇬🇭 Ghana | `gh-nacca` |
| 🇿🇦 South Africa | `za-caps` |
| 🇷🇼 Rwanda | `rw-reb` |

> Run `list_systems` in Claude for a live count — the pipeline updates nightly.

---

## Tools

| Tool | What it does |
|---|---|
| `search_standards` | Find standards matching a concept or skill in plain English |
| `lookup_standard` | Fetch a standard by ID with full text, prerequisites, and successors |
| `get_progression` | Trace how a concept develops across grade levels |
| `map_standard` | Find the closest equivalent in another curriculum system |
| `list_systems` | Live count of all indexed systems and standards |

**More examples:**
- *"Find Ghana standards related to quadratic equations"*
- *"Compare how India NCERT and South Africa CAPS cover fractions"*
- *"Map TX.MATH.5.3.K to the Hong Kong curriculum"*
- *"When does Cambridge International introduce trigonometry?"*

---

## How it works

**Ingestion** — US/Canada standards come from [commonstandardsproject.com](https://commonstandardsproject.com). International standards are extracted from official PDF syllabuses using Gemma 4 31B (via Ollama) to parse curriculum text into structured JSON.

**Embeddings** — Every standard is embedded with `nomic-embed-text` (768 dims) and stored in SQLite.

**Crosswalk** — CCSS is the hub. NLP cosine similarity maps every non-CCSS standard to its closest CCSS match. `map_standard` supports direct lookup, two-hop bridging (any-to-any via CCSS), and semantic embedding fallback.

**MCP server** — FastMCP over stdio, five tools.

---

## Stack

- **uv** workspace monorepo
- **FastMCP** (stdio transport)
- **SQLite** — standards, embeddings (BLOBs), relationships, crosswalk mappings
- **nomic-embed-text** via Ollama — 768-dim embeddings
- **Gemma 4 31B** via Ollama — PDF→JSON extraction

---

## Development

```bash
git clone https://github.com/swoopeagle/standardgraph.git
cd standardgraph
uv sync
```

Run the MCP server locally:
```bash
DB_PATH=./data/common_core.db OLLAMA_BASE_URL=http://localhost:11434 \
  uv run python -m common_core.server
```

Run the overnight pipeline manually:
```bash
bash scripts/overnight_run.sh
```

---

## License

MIT. Standards data © their respective curriculum bodies (CCSS, state DOEs, ACARA, Cambridge Assessment, IBO, MOE Singapore, MEXT Japan, NZ Ministry of Education, Education Scotland, NCCA Ireland, EDB Hong Kong, NCERT India, NaCCA Ghana, DBE South Africa, etc.).
