# StandardGraph

**17,743 math standards across 64 curriculum systems, semantically cross-referenced and accessible via Claude MCP.**

StandardGraph indexes math curricula from the US (CCSS + all 50 states), Canada, Australia, the UK, Cambridge International, and IB — all mapped to a common hub through NLP-based crosswalk alignment. Expose it to Claude as an MCP server and query any standard in plain English.

---

## Coverage

| Region | Systems | Standards |
|---|---|---|
| 🇺🇸 United States | `ccss` + all 50 states + DC | 12,405 |
| 🇨🇦 Canada | `ca-ab` `ca-bc` `ca-on` `ca-mb` `ca-sk` `ca-nb` | 3,522 |
| 🌍 International | `cambridge` `ib-myp` `ib-dp` | 1,005 |
| 🇦🇺 Australia | `au-acara` `au-vic` | 397 |
| 🇬🇧 United Kingdom | `uk-nc` `uk-aqa` | 414 |

**Total:** 17,743 standards · 15,256 crosswalk mappings · 233,346 relationships

---

## MCP Tools

| Tool | Use it when… |
|---|---|
| `lookup_standard` | You have a specific standard ID and want its full text, domain, prerequisites, and successors |
| `search_standards` | You want to find standards matching a concept or skill description |
| `get_progression` | You want to see how a topic develops across grade levels |
| `map_standard` | You want the closest equivalent to a standard in another curriculum system |

**Example queries in Claude:**
- *"How does CCSS build fractions from grade 3 to 6?"*
- *"Find Cambridge standards on geometric transformations"*
- *"What's the Alberta equivalent of CCSS 5.NBT.A.1?"*
- *"Compare how Texas and CCSS cover quadratic equations"*

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

## How it works

**Ingestion** — Standards are fetched from [commonstandardsproject.com](https://commonstandardsproject.com) and ingested into a SQLite database. Each standard gets a canonical ID (`CCSS.MATH.6.RP.A.3`, `TX.MATH.5.3.K`, `CA_BC.MATH.3.a`, etc.), domain/cluster metadata, and grade classification.

**Embeddings** — Every standard text is embedded with `nomic-embed-text` (768 dimensions) via Ollama, stored as a binary blob in SQLite.

**Crosswalk** — CCSS is the hub. For every non-CCSS standard, cosine similarity against all 343 CCSS vectors finds the closest match. Mappings above 0.70 confidence are stored with a grade-delta flag to catch level mismatches.

**MCP server** — A FastMCP server exposes four tools. Semantic search at query time embeds the user's query and scores it against all stored vectors.

---

## Stack

- **uv** workspace monorepo (`packages/shared`, `ingestion`, `common-core`, `crosswalk-engine`)
- **FastMCP** for the MCP server (stdio transport)
- **SQLite** — standards, embeddings (as BLOBs), relationships, crosswalk mappings
- **nomic-embed-text** via Ollama for 768-dim embeddings
- **commonstandardsproject.com** as the primary data source

---

## License

MIT. Standards data © their respective curriculum bodies (CCSS, state DOEs, ACARA, Cambridge Assessment, IBO, etc.).
