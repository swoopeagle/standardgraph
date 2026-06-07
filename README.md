# StandardGraph

**20,000+ math standards across 75+ curriculum systems, semantically cross-referenced and accessible via Claude MCP.**

StandardGraph indexes math curricula from the US, Canada, and 18 international systems — all mapped to a common CCSS hub through NLP-based crosswalk alignment. Expose it to Claude as an MCP server and query any standard in plain English.

---

## Coverage

| Region | Systems | Notes |
|---|---|---|
| 🇺🇸 United States | `ccss` + all 50 states + DC | CCSS is the crosswalk hub |
| 🇨🇦 Canada | `ca-ab` `ca-bc` `ca-on` `ca-mb` `ca-sk` `ca-nb` | |
| 🌍 International | `cambridge` `ib-myp` `ib-dp` `aero` `dodea` | |
| 🇦🇺 Australia | `au-acara` `au-vic` | |
| 🇬🇧 United Kingdom | `uk-nc` `uk-aqa` | |
| 🇸🇬 Singapore | `sg-moe` | Primary + Secondary + NT |
| 🇯🇵 Japan | `jp-mext` | Elementary Gr 1–6 |
| 🇳🇿 New Zealand | `nz-moe` | Years 7–8 (Phase 3) |
| 🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scotland | `gb-sco` | Curriculum for Excellence |
| 🇮🇪 Ireland | `ie-ncca` | Junior Cycle |
| 🇭🇰 Hong Kong | `hk-edb` | KS1–KS3 |
| 🇮🇳 India | `in-ncert` | Classes I–XII |
| 🇬🇭 Ghana | `gh-nacca` | Basic 1–12 |
| 🇿🇦 South Africa | `za-caps` | Grade R–12 |

> Run `list_systems` in Claude for a live count — the pipeline adds new standards nightly.

---

## MCP Tools

| Tool | Use it when… |
|---|---|
| `lookup_standard` | You have a specific standard ID and want its full text, domain, prerequisites, and successors |
| `search_standards` | You want to find standards matching a concept or skill description |
| `get_progression` | You want to see how a topic develops across grade levels |
| `map_standard` | You want the closest equivalent to a standard in another curriculum system |
| `list_systems` | You want a live count of all indexed systems and standards |

**Example queries in Claude:**
- *"How does CCSS build fractions from grade 3 to 6?"*
- *"Find Singapore MOE standards on geometric transformations for grade 5"*
- *"What's the Ghana equivalent of CCSS 4.NBT.A.1?"*
- *"Compare how India NCERT and South Africa CAPS cover quadratic equations"*
- *"Map TX.MATH.5.3.K to the Hong Kong curriculum"*

---

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/swoopeagle/standardgraph.git
cd standardgraph
uv sync
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "intl-math-standards": {
      "command": "/path/to/standardgraph/.venv/bin/python",
      "args": ["-m", "common_core.server"]
    }
  }
}
```

Restart Claude Desktop. The server appears under the hammer icon as **intl-math-standards**.

---

## Nightly Pipeline

Standards are kept fresh by a scheduled pipeline (`scripts/overnight_run.sh`) that:
1. Re-ingests all sources (idempotent — `INSERT OR REPLACE`)
2. Embeds any new standards with `nomic-embed-text`
3. Rebuilds grade-progression relationships
4. Regenerates NLP crosswalk mappings to CCSS
5. Runs a smoke test validating min counts per system
6. Restarts Claude Desktop to pick up the updated MCP server state

To enable nightly scheduling (macOS):
```bash
launchctl load ~/Library/LaunchAgents/com.devos.intl-math-standards-overnight.plist
```
Runs at 9:30 PM daily. Logs go to `logs/overnight_YYYYMMDD_HHMMSS.log`.

To run manually:
```bash
bash scripts/overnight_run.sh
```

---

## How it works

**Ingestion** — US/Canada standards come from [commonstandardsproject.com](https://commonstandardsproject.com). International standards are extracted from official PDF syllabuses using Gemma 4 31B (via Ollama) to parse free-form curriculum text into structured JSON.

**Embeddings** — Every standard text is embedded with `nomic-embed-text` (768 dimensions) via Ollama, stored as a binary blob in SQLite.

**Crosswalk** — CCSS is the hub. For every non-CCSS standard, cosine similarity against all 343 CCSS vectors finds the closest match. `map_standard` also supports two-hop bridging (any-to-any via CCSS) and a semantic embedding fallback when no precomputed mapping exists.

**MCP server** — A FastMCP server exposes five tools over stdio.

---

## Stack

- **uv** workspace monorepo (`packages/shared`, `ingestion`, `common-core`, `crosswalk-engine`)
- **FastMCP** for the MCP server (stdio transport)
- **SQLite** — standards, embeddings (as BLOBs), relationships, crosswalk mappings
- **nomic-embed-text** via Ollama for 768-dim embeddings
- **Gemma 4 31B** (`gemma4:31b-it-q8_0`) via Ollama for PDF→JSON extraction
- **commonstandardsproject.com** as the primary source for US/Canada standards

---

## License

MIT. Standards data © their respective curriculum bodies (CCSS, state DOEs, ACARA, Cambridge Assessment, IBO, MOE Singapore, MEXT Japan, NZ Ministry of Education, Education Scotland, NCCA Ireland, EDB Hong Kong, NCERT India, NaCCA Ghana, DBE South Africa, etc.).
