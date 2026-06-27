# StandardGraph — Claude Code context

## What this is

FastMCP server exposing 157,000+ education standards across 298 curriculum systems as five MCP tools for Claude Desktop. Standards cover Math, Science, ELA, Social Studies, CS, Arts, and World Languages.

## Architecture

```
packages/
  common-core/       → PyPI package "standardgraph" — the MCP server
    src/common_core/
      server.py      → all five MCP tools (search, lookup, progression, map, list)
      config.py      → DB_PATH resolution (~/.standardgraph/common_core.db)
  ingestion/         → pipeline: fetchers → embed → relate → crosswalk
  shared/            → shared DB helpers

data/common_core.db          → dev/pipeline DB (used by overnight_run.sh)
~/.standardgraph/common_core.db  → installed user DB (used by MCP server)

scripts/
  mcp_test.py        → 272-test suite (imports server directly, no MCP protocol)
  overnight_run.sh   → full ingestion pipeline (run on Mac Studio overnight)
  dashboard.sh       → hardware + pipeline progress dashboard
  progress.sh        → pipeline-only progress view
```

## Key facts

- **DB size:** ~1.8 GB
- **Standards:** 157,101 across 298 systems
- **Crosswalk rows:** ~93,385 (hub-centric: CCSS for math, NGSS for science, etc.)
- **Relationships:** ~3.7M rows (prerequisites/successors)
- **Ollama host:** `http://169.254.1.1:11434` (Mac Studio via Thunderbolt Bridge)
- **HuggingFace dataset:** `swoopeagle/standardgraph` (file: `common_core.db`)
- **PyPI package:** `standardgraph`

## Tailscale devices

| Device | IP | Role |
|---|---|---|
| MacBook Pro | 100.118.151.10 | dev machine |
| Mac Studio | 100.77.63.73 | Ollama / ingestion host |
| Mac mini | 100.101.100.97 | secondary |
| IWPC | 100.70.170.62 | remote |

SSH: `ssh ianwang@<ip>` — Mac Studio and Mac mini may not have MacBook's key authorized yet.

## Common commands

```bash
# Run full test suite
DB_PATH=~/.standardgraph/common_core.db uv run python scripts/mcp_test.py

# Check DB stats
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(*) FROM standards;"
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(DISTINCT system) FROM standards;"
ls -lh ~/.standardgraph/common_core.db

# Build package
cd packages/common-core && uv build   # output goes to ../../dist/

# Upload to PyPI (token via env var)
uvx twine upload --username __token__ dist/standardgraph-X.Y.Z*

# Upload DB to HuggingFace
uvx huggingface-cli upload swoopeagle/standardgraph \
    ~/.standardgraph/common_core.db common_core.db --repo-type dataset

# Watch overnight pipeline
bash scripts/dashboard.sh --watch
```

## Release checklist

1. Bump version in `packages/common-core/pyproject.toml`
2. `cd packages/common-core && uv build`
3. `uvx twine upload --username __token__ ../../dist/standardgraph-X.Y.Z*`
4. Commit version bump + push to GitHub
5. If DB changed: upload to HuggingFace
6. Verify stats in docs match DB (`/stats` command)

Use `/release` to run this interactively.

## map_standard response formats

Two distinct JSON schemas — always use `_is_precomputed()` / `_has_mapping()` helpers in `mcp_test.py`:

- **Precomputed:** `{"mapping_method": "precomputed_crosswalk", "mappings": [...]}`
- **Fallback:** `{"result": "no_precomputed_mapping_above_threshold", "two_hop_via_ccss": [...], "nearest_by_concept": [...]}`

## Standard ID formats

| System | Example |
|---|---|
| CCSS Math | `CCSS.MATH.5.NF.A.1` |
| AP | `AP.AP_CALC_AB.LIM-1.A` |
| IB-DP | `IB_DP.MATH.AHL.5.19b` |
| IB-MYP | `IB_MYP.MATH.6.D5` |
| Ontario K-8 | `CA-ON.MATH.5.5.B2.5` |
| Ontario HS | `CA-ON.MATH.HS.9.E1.4` |
| AP Precalc | `AP.AP_PRECALC.1.1.A` (not PCR-format) |

## Security reminder

User shares PyPI and HuggingFace tokens in chat — always remind to rotate immediately after use.
