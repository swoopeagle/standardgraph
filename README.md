# StandardGraph

**140,000+ standards across 250+ curriculum systems, accessible via Claude.**

Covers Mathematics, Science, ELA, Social Studies, and Computer Science — US national and state standards plus major international curricula. Ask Claude to look up any standard, trace a concept across grade levels, or find the equivalent in another country's curriculum.

---

## Install

Requires [Claude Desktop](https://claude.ai/download). Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

Then **quit and reopen Claude Desktop**. Look for the 🔨 icon in a new conversation.

> The installer handles everything: downloads the pre-built database (~500 MB), installs dependencies, and patches your Claude config automatically.

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
```
Find Texas ELA standards related to argumentative writing in grades 9-10
```
```
How does the C3 Framework approach civics compared to California's social studies standards?
```

→ Full install guide: [docs/install.md](docs/install.md)

---

## Coverage

### Mathematics

| Region | Systems |
|---|---|
| 🇺🇸 United States | `ccss` (hub) + all 50 states + DC |
| 🎓 Advanced Placement | `ap-calc-ab` `ap-calc-bc` `ap-stats` `ap-precalc` |
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

### Science

| Region | Systems |
|---|---|
| 🇺🇸 United States | `ngss` (hub, K–12) + all 50 states + DC |
| 🎓 Advanced Placement | `ap-bio` `ap-chem` `ap-phys-1` `ap-phys-2` `ap-phys-c-mech` `ap-phys-c-em` `ap-env` |

### ELA (English Language Arts)

| Region | Systems |
|---|---|
| 🇺🇸 United States | `ccss-ela` (hub, K–12) + 49 states |

### Social Studies

| Region | Systems |
|---|---|
| 🇺🇸 United States | `c3` (C3 Framework hub, K–12) + 50 states |

### Computer Science

| Region | Systems |
|---|---|
| 🇺🇸 United States | `csta` (CSTA 2017 hub, K–12) + 9 states (coverage expanding) |

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
- *"Find NGSS standards related to climate change in middle school"*
- *"Compare how Texas and California cover argumentative writing in high school ELA"*
- *"What CSTA standards correspond to loops and conditionals?"*
- *"How does the C3 Framework approach historical thinking vs. Virginia's SOL social studies?"*
- *"Map CCSS.MATH.6.RP.A.3 to the Singapore curriculum"*

---

## How it works

**Ingestion** — US and Canadian standards come from [commonstandardsproject.com](https://commonstandardsproject.com). International standards are extracted from official PDF syllabuses using Gemma 4 31B (via Ollama) to parse curriculum text into structured JSON. AP course standards are extracted from College Board Course and Exam Descriptions the same way.

**Embeddings** — Every standard is embedded with `nomic-embed-text` (768 dims) and stored in SQLite.

**Crosswalk** — Each subject has a hub standard. NLP cosine similarity maps every non-hub standard to its closest hub match:

| Subject | Hub |
|---|---|
| Mathematics | CCSS Math |
| Science | NGSS |
| ELA | CCSS ELA |
| Social Studies | C3 Framework |
| Computer Science | CSTA K-12 (2017) |

`map_standard` supports direct lookup, two-hop bridging (any-to-any via hub), and semantic embedding fallback.

**MCP server** — FastMCP over stdio, five tools.

---

## Stack

- **uv** workspace monorepo
- **FastMCP** (stdio transport)
- **SQLite** — standards, embeddings (BLOBs), relationships, crosswalk mappings
- **nomic-embed-text** via Ollama — 768-dim embeddings
- **Gemma 4 31B** via Ollama — PDF→JSON extraction for international and AP curricula

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

MIT. Standards data © their respective curriculum bodies (CCSS, state DOEs, NGSS, NCSS, CSTA, ACARA, Cambridge Assessment, IBO, MOE Singapore, MEXT Japan, NZ Ministry of Education, Education Scotland, NCCA Ireland, EDB Hong Kong, NCERT India, NaCCA Ghana, DBE South Africa, etc.).
