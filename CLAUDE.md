# StandardGraph — Claude Code context

## What this is

FastMCP server exposing 153,000+ education standards across 300 curriculum systems as five MCP tools for Claude Desktop. Standards cover Math, Science, ELA, Social Studies, CS, Arts, and World Languages.

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
  mcp_test.py        → 330-test suite (imports server directly, no MCP protocol)
  overnight_run.sh   → full ingestion pipeline (run on Mac Studio overnight)
  dashboard.sh       → hardware + pipeline progress dashboard
  progress.sh        → pipeline-only progress view
```

## Key facts

- **DB size:** ~1.5 GB
- **Standards:** 153,988 across 300 systems
- **Crosswalk rows:** ~94,754 (hub-centric: CCSS for math, NGSS for science, etc.)
- **Crosswalk quality scores:** ~75,134 rows (~79.3%) carry a 1–5 quality score (LLM rubric scoring + deterministic exact-match); all AP/IB source rows are scored. Remainder unscored (`nlp_pass`, ranked by cosine, treated as neutral quality).
- **Relationships:** ~3.15M rows (prerequisites/successors)
- **Ollama host:** `http://169.254.1.1:11434` (Mac Studio via Thunderbolt Bridge from Mini 2 — 0.4ms RTT)
- **HuggingFace dataset:** `swoopeagle/standardgraph` (file: `common_core.db`)
- **PyPI package:** `standardgraph`

## Tailscale devices

| Device | Chip | RAM | IP | SSH user | Role |
|---|---|---|---|---|---|
| MacBook Pro | — | — | 100.118.151.10 | `ianwang` | dev machine |
| Mac Studio | M1 Max | 64 GB | 100.77.63.73 | `ianwangm1max` | Ollama host only (no repo) |
| Mac mini 2 | M4 Pro | 24 GB | 100.101.100.96 | `devos` | pipeline runner, MCP server |
| Mac mini 3 | M4 | 16 GB | 100.81.61.57 | `devos` | pipeline runner, MCP server (Tailscale down — use LAN 192.168.12.222) |
| IWPC | RTX 3060 | 12 GB VRAM / 32 GB RAM | 100.70.170.62 | — | Ollama host (Windows, CUDA) — embed + extraction + low-band rationale |

Model roster per device (do not exceed safe limits):
- **Mac Studio (64 GB):** `gemma4:31b-it-q8_0`, `qwen2.5:72b`, `gemma3:27b`, `nomic-embed-text`, `llama3.2` — any model up to 47 GB
- **Mac mini 2 (24 GB M4 Pro):** `gemma4:26b` (17 GB), `qwen2.5:14b` (9 GB), `nomic-embed-text` — limit ~18 GB
- **Mac mini 3 (16 GB M4):** `qwen2.5:14b` (9 GB), `nomic-embed-text` — limit ~10 GB; never install 17+ GB models
- **IWPC (12 GB VRAM + 32 GB RAM, CUDA):** `nomic-embed-text`, `qwen2.5:14b` (9 GB), `qwen2.5:7b` (4.7 GB), `gemma4:12b` (7.6 GB), `gemma4:e4b` (9.6 GB) — keep VRAM under 11 GB; 32 GB system RAM available for overflow

Both Mac minis run Ollama at `localhost:11434`. Pipeline defaults to local Ollama for embeddings; Mac Studio handles PDF extraction (gemma4:31b).

Project on Mac minis: `~/projects/intl-math-standards-mcp/` (old name, same codebase).
SSH authorized on Mac Studio and both Mac minis as of 2026-06-26.

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

## Batch execution workflow

Full details in `docs/run_playbook.md`. Short version:

For longer runs, use this two-phase pattern:

### Phase 1 — Planning (get approval upfront)

Before starting a multi-step run, draft a plan table with every job, its device,
its dependencies, estimated time, and any risk flags. Present it for a single
approval. Format:

| # | Job | Device | Deps | Est. time | Risk |
|---|---|---|---|---|---|
| 1 | fetch_portugal | Mini 3 → Studio | — | 30 min | low |
| 2 | embed + relate | Mini 2 + Mini 3 (parallel) | 1 | 20 min | low |
| ... | | | | | |

Risk flags:
- `token` — requires PyPI or HuggingFace credential (always prompt separately)
- `destructive` — modifies or deletes data in the DB
- `irreversible` — publish to PyPI, push to HuggingFace

### Phase 2 — Execution (run uninterrupted)

Once plan is approved, execute without mid-run check-ins. Report only:
- Chapter milestones (job N complete, moving to job N+1)
- Blockers that weren't in the plan
- Final summary

### Pre-authorized work (no per-step approval needed)

The following are always safe to run without asking:
- SSH to `devos@100.101.100.96`, `devos@100.123.114.101`, `ianwangm1max@100.77.63.73`
- `git add`, `git commit`, `git push` to `origin main`
- File edits anywhere in this repo
- Starting background pipeline jobs on the minis (embed, relate, crosswalk, fetchers)
- Running `mcp_test.py` or eval scripts
- Building the package (`uv build`)
- Pulling the DB from Mini 2 to MacBook via `sqlite3 .backup`

### Always prompt separately (never include in batch)

- PyPI upload (`uvx twine upload`) — needs token, remind to rotate after use
- HuggingFace upload (`huggingface-cli upload`) — needs token, remind to rotate after use
- `DELETE` or `DROP` SQL against the production DB
- Force push or branch deletion

## Security reminder

User shares PyPI and HuggingFace tokens in chat — always remind to rotate immediately after use.
