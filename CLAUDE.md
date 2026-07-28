# StandardGraph — Claude Code context

## What this is

FastMCP server exposing 175,000+ education standards across 310 curriculum systems as six MCP tools for Claude Desktop. Standards cover Math, Science, ELA, Social Studies, CS, Arts, and World Languages.

## Architecture

```
packages/
  common-core/       → PyPI package "standardgraph" — the MCP server
    src/common_core/
      server.py      → all six MCP tools (search, lookup, progression, learning_path, map, list)
      config.py      → DB_PATH resolution (~/.standardgraph/common_core.db)
  ingestion/         → pipeline: fetchers → embed → relate → crosswalk
  shared/            → shared DB helpers

data/common_core.db          → dev/pipeline DB (used by overnight_run.sh)
~/.standardgraph/common_core.db  → installed user DB (used by MCP server)

scripts/
  mcp_test.py        → 333-test suite (imports server directly, no MCP protocol)
  overnight_run.sh   → full ingestion pipeline (run on Mac Studio overnight)
  dashboard.sh       → hardware + pipeline progress dashboard
  progress.sh        → pipeline-only progress view
```

## Key facts

- **DB size:** ~1.9 GB
- **Standards:** 175,738 across 310 systems (incl. CCSS sub-standard decomposition, source-side decomposition of 11 high-bundling systems, CCSS Mathematical Practice standards, the 2026-07 international expansion incl. 10 African systems, and the 2026-07-15 math grade-coverage fill-in for 11 countries)
- **Crosswalk rows:** ~208,442 — hub-centric (CCSS for math, NGSS for science, etc.) PLUS ~88,944 direct within-family country-to-country math edges (see `crosswalk_engine/direct_family.py`; tagged `direct_family` in notes). map_standard serves direct edges automatically, two-hop-via-CCSS is the fallback.
- **Crosswalk quality scores:** **ALL 208,442 crosswalks now carry a 1–5 LLM quality score (100%)** — completed 2026-07-18 via two overnight Ollama fleet runs (Studio + Mini 2 + IWPC GPU, qwen2.5:14b): the 88,944 direct-family math edges, then the 41,697 hub-centric edges (mostly ELA/Sci/SS). 37,335 edges carry `flagged_for_review=1` and are suppressed from default `map_standard` results. Flagging policy differs by layer: direct-family flags score ≤2; hub-centric flags **only score 1** (hub 2s are often valid-but-grade-shifted, and map_standard already ranks by score). Non-math hub rationales were re-scored with a subject-neutral prompt (the initial fleet prompt said "math", polluting ~2,520 non-math rationales — fixed). Note: scores span calibration regimes (earlier Sonnet mode=4; fleet 14b generous top-end) — directional weak/strong signal intact.
- **Relationships:** ~3.79M rows (prerequisites/successors)
- **Ollama host:** `http://169.254.1.1:11434` (Mac Studio via Thunderbolt Bridge from Mini 2 — 0.4ms RTT)
- **HuggingFace dataset:** `swoopeagle/standardgraph` (file: `common_core.db`)
- **PyPI package:** `standardgraph`

## Tailscale devices

| Device | Chip | RAM | IP | SSH user | Role |
|---|---|---|---|---|---|
| MacBook Pro | — | — | 100.118.151.10 | `ianwang` | dev machine |
| Mac Studio | M1 Max | 64 GB | 100.77.63.73 | `ianwangm1max` | Ollama host only (no repo) |
| Mac mini 2 | M4 Pro | 24 GB | 100.101.100.96 (LAN 192.168.12.135) | `devos` | pipeline runner, **hosted MCP server** |
| Mac mini 3 | M4 | 16 GB | 100.91.162.102 | `devos` | pipeline runner; **former** MCP host — unreliable, see below |
| Mac mini 4 | M4 | 16 GB | 100.106.61.114 (LAN 192.168.12.112) | `devos` | undocumented; SSH reachable over LAN only |
| IWPC | RTX 3060 | 12 GB VRAM / 32 GB RAM | 100.70.170.62 | — | Ollama host (Windows, CUDA) — embed + extraction + low-band rationale |

⚠️ **Mac mini 3 is not dependable as a service host.** Its LaunchAgents only load
inside a logged-in GUI session, so any unattended reboot silently takes the hosted
endpoint down (a ~5h outage on 2026-07-18, another on 2026-07-28). Its Tailscale IP
also changed from the long-documented `100.81.61.57` to `100.91.162.102`. The hosted
MCP server was moved to Mac mini 2 on 2026-07-28 for this reason.

Model roster per device (do not exceed safe limits):
- **Mac Studio (64 GB):** `gemma4:31b-it-q8_0`, `qwen2.5:72b`, `gemma3:27b`, `nomic-embed-text`, `llama3.2` — any model up to 47 GB
- **Mac mini 2 (24 GB M4 Pro):** `gemma4:26b` (17 GB), `qwen2.5:14b` (9 GB), `nomic-embed-text` — limit ~18 GB
- **Mac mini 3 (16 GB M4):** `qwen2.5:14b` (9 GB), `nomic-embed-text` — limit ~10 GB; never install 17+ GB models
- **IWPC (12 GB VRAM + 32 GB RAM, CUDA):** `nomic-embed-text`, `qwen2.5:14b` (9 GB), `qwen2.5:7b` (4.7 GB), `gemma4:12b` (7.6 GB), `gemma4:e4b` (9.6 GB) — keep VRAM under 11 GB; 32 GB system RAM available for overflow

Both Mac minis run Ollama at `localhost:11434`. Pipeline defaults to local Ollama for embeddings; Mac Studio handles PDF extraction (gemma4:31b).

Project on Mac minis: `~/projects/intl-math-standards-mcp/` (old name, same codebase).
SSH authorized on Mac Studio and both Mac minis as of 2026-06-26.

## Hosted MCP endpoint

Public URL: `https://standardgraph.walkmakewalk.com/mcp` (Cloudflare tunnel →
`localhost:8010`). Landing page: https://swoopeagle.github.io/standardgraph/
(GitHub Pages, `main` `/docs`).

Two launchd jobs make it work:
- `life.devos.standardgraph-serve` — runs `~/sg-serve-env/bin/standardgraph-serve`
  with `DB_PATH` pointed at the repo's `data/common_core.db` and `SG_HTTP_PORT=8010`.
- `life.walkmakewalk.standardgraph-tunnel` — runs `cloudflared` with an **isolated**
  `HOME=~/sg-home` so it never touches the `devos-johnny` tunnel. Never touch that one.

⚠️ **The tunnel credentials are a single point of failure.** Tunnel
`4312deb9-f5e4-40e4-b396-aa1a87a695ac`'s credentials JSON lives only in
`~/sg-home/.cloudflared/` on whichever machine hosts it. There is no backup. When
Mac mini 3 went offline on 2026-07-28 the endpoint could not be moved because the
credentials were unreachable. **Keep a copy somewhere else**, or recover via the
Cloudflare dashboard (Zero Trust → Networks → Tunnels → Configure → token, then
`cloudflared tunnel run --token <TOKEN>`), which reuses the same tunnel and needs
no DNS change.

⚠️ **LaunchAgents do not survive an unattended reboot** — they only load inside a
logged-in GUI session. Prefer LaunchDaemons in `/Library/LaunchDaemons` with
`UserName: devos` set (without it they run as root and the venv/DB paths break).
Installing them needs sudo.

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
