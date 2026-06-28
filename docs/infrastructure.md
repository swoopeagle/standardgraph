# StandardGraph Infrastructure

## Device inventory

| Device | Chip | RAM | Tailscale IP | SSH user | Role |
|---|---|---|---|---|---|
| MacBook Pro | — | — | 100.118.151.10 | `ianwang` | Development machine |
| Mac Studio | M1 Max | 64 GB | 100.77.63.73 | `ianwangm1max` | Ollama host (LLM inference only) |
| Mac mini 2 | M4 Pro | 24 GB | 100.101.100.96 | `devos` | Pipeline runner, MCP server |
| Mac mini 3 | M4 | 16 GB | 100.123.114.101 | `devos` | Pipeline runner, MCP server |
| IWPC | RTX 3060 | 12 GB VRAM | 100.70.170.62 | — | Ollama host (Windows/CUDA) — embed + low-band rationale |

> The project lives at `~/projects/intl-math-standards-mcp/` on both Mac minis (old project name — same codebase as `standardgraph`).

## Network topology

```
Mac mini 2 (169.254.1.2) ──── Thunderbolt Bridge ──── Mac Studio (169.254.1.1 / Ollama)
     │                                                       │
     └────────────────── Tailscale VPN ─────────────────────┘
                                │
              Mac mini 3 (.101), IWPC (.62), MacBook Pro (.10)
```

- **Thunderbolt Bridge** — direct low-latency link between Mac mini 2 and Mac Studio (0.4ms RTT vs ~50ms over Tailscale). Mini 2's pipeline defaults to `http://169.254.1.1:11434` for all Ollama calls. Keep this cable — across thousands of batch LLM requests the network overhead compounds significantly.
- **Tailscale** — SSH access and general connectivity. Mac Studio also reachable at `http://100.77.63.73:11434` for Mini 3, IWPC, and MacBook Pro.

## Ollama (Mac Studio)

Mac Studio hosts Ollama exclusively — no standardgraph repo lives there. 64 GB unified memory handles the largest models comfortably.

- **Thunderbolt URL:** `http://169.254.1.1:11434`
- **Tailscale URL:** `http://100.77.63.73:11434`
- **Installed models:**

| Model | Size | Use |
|---|---|---|
| `gemma4:31b-it-q8_0` | 33 GB | PDF→JSON extraction (international & AP curricula) |
| `qwen2.5:72b` | 47 GB | General-purpose LLM, heavy reasoning |
| `gemma3:27b` | 17 GB | Alternative extraction/eval |
| `nomic-embed-text` | 274 MB | 768-dim embeddings for all standards |
| `llama3.2` | 2 GB | Lightweight tasks |

**Model size limits by device** — max model size that fits in RAM without heavy swapping:

| Device | RAM | Safe model limit | Installed models |
|---|---|---|---|
| Mac Studio | 64 GB | 47 GB | `gemma4:31b`, `qwen2.5:72b`, `gemma3:27b`, `nomic-embed-text`, `llama3.2` |
| Mac mini 2 | 24 GB | ~18 GB | `gemma4:26b` (17 GB), `qwen2.5:14b` (9 GB), `nomic-embed-text` |
| Mac mini 3 | 16 GB | ~10 GB | `qwen2.5:14b` (9 GB), `nomic-embed-text` |
| IWPC | 12 GB VRAM + 32 GB RAM (CUDA) | ~11 GB VRAM / ~20 GB RAM | `qwen2.5:14b`, `qwen2.5:7b`, `gemma4:12b`, `gemma4:e4b`, `nomic-embed-text` |

Both Mac minis have Ollama running at `localhost:11434`. The pipeline's overnight_run.sh defaults to `localhost:11434` — each mini embeds locally rather than hitting Mac Studio over the network.

## Ollama (IWPC — Windows/CUDA)

IWPC runs Ollama for Windows with CUDA acceleration on an RTX 3060 (12 GB VRAM, 32 GB system RAM).
No repo lives on IWPC — the minis call it over Tailscale, just like Mac Studio.

- **Tailscale URL:** `http://100.70.170.62:11434`
- **Setup guide:** [docs/iwpc_setup.md](iwpc_setup.md)

**Installed models:**

| Model | Size | Use |
|---|---|---|
| `nomic-embed-text` | 274 MB | Batch embeddings (CUDA faster than Apple Silicon) |
| `qwen2.5:14b` | 9 GB | Low/mid-band rationale gen, eval |
| `qwen2.5:7b` | 4.7 GB | Fast classification, lightweight tasks |
| `gemma4:12b` | 7.6 GB | PDF extraction (lighter jobs — saves Studio for 31b-only PDFs) |
| `gemma4:e4b` | 9.6 GB | Fast multimodal, alternative extraction |

**When the pipeline uses IWPC:**
- `post_ingest_pipeline.sh` auto-detects it (3-second curl) and routes embed calls there — CUDA batch throughput beats Apple Silicon for this workload
- `overnight_rationale.sh` offloads low-band US state mappings to IWPC (`qwen2.5:14b`) while Studio handles high/mid-band AP/IB (`qwen2.5:72b`) simultaneously
- Fetchers with lighter PDFs can target `gemma4:12b` on IWPC instead of queuing on Mac Studio — use `OLLAMA_BASE_URL=http://100.70.170.62:11434 OLLAMA_MODEL=gemma4:12b`

```bash
# Check IWPC Ollama from anywhere on Tailscale
curl -sf http://100.70.170.62:11434/api/tags | python3 -m json.tool
```

```bash
# Check what's loaded (no SSH needed)
curl -sf http://100.77.63.73:11434/api/ps
```

## Pipeline (Mac minis)

Both Mac minis run the ingestion pipeline and serve the MCP server via Claude Desktop.

| | Mac mini 2 | Mac mini 3 |
|---|---|---|
| IP | 100.101.100.96 | 100.123.114.101 |
| Chip | M4 Pro | M4 |
| RAM | 24 GB | 16 GB |
| Disk | 460 GB total, ~316 GB free | 228 GB total, ~106 GB free |
| Last pipeline run | 2026-06-27 (resume, ALL DONE 11:25) | 2026-06-27 (resume, ALL DONE 11:25) |
| Crosswalk mappings | 96,805 | 96,768 |
| Project path | `~/projects/intl-math-standards-mcp/` | `~/projects/intl-math-standards-mcp/` |

Pipeline logs: `logs/JOBTYPE_YYYYMMDD_HHMMSS.log` (overnight / reingest / resume). Job history appended to `logs/job_history.tsv` after each overnight run.

Also running on both Mac minis: `devos-johnny` bot (uvicorn on port 8000).

## SSH access

**MacBook Pro public key** (authorize on each machine by running this locally on the target):
```bash
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP53tUmEA81HZQWErdYK/BcRc+lNOTaC0/YCj58aJMci ianwang@Ians-MacBook-Pro.local" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
```

**Authorization status (as of 2026-06-26):**
- Mac Studio (`ianwangm1max@100.77.63.73`) ✓ authorized
- Mac mini 2 (`devos@100.101.100.96`) ✓ authorized
- Mac mini 3 (`devos@100.123.114.101`) ✓ authorized
- IWPC — no SSH (Ollama-only host; reach via `curl http://100.70.170.62:11434/api/tags`)

## Common remote commands

```bash
# Check Mac Studio Ollama
curl -sf http://100.77.63.73:11434/api/ps

# SSH into Mac Studio
ssh ianwangm1max@100.77.63.73

# SSH into Mac mini 2
ssh devos@100.101.100.96

# SSH into Mac mini 3
ssh devos@100.123.114.101

# Tail latest pipeline log (Mac mini 2)
ssh devos@100.101.100.96 "ls -t ~/projects/intl-math-standards-mcp/logs/*.log | head -1 | xargs tail -f"

# Check DB stats (Mac mini 2)
ssh devos@100.101.100.96 "sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db \"SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;\""
```

## Division of labor

Each device has a distinct role based on its memory ceiling and what's physically connected.

### Quick reference

| Work type | Device | Why |
|---|---|---|
| PDF → JSON extraction (LLM) | Mac Studio | Only machine with enough VRAM for `gemma4:31b` / `qwen2.5:72b` |
| Crosswalk rationale generation | Mac Studio | Needs `qwen2.5:72b` (47 GB); quality reasoning for pedagogical context |
| Embedding standards (`nomic-embed-text`) | Mac mini (local) | 274 MB model fits anywhere; avoid network hop to Studio |
| `relate` (prereq/successor graph) | Mac mini (CPU) | Pure numpy/SQLite, no GPU needed; runs well on M4 Pro/M4 |
| `crosswalk_engine.nlp_pass` | Mac mini (CPU) | Cosine similarity over pre-computed vectors; CPU-bound, parallelizable |
| MCP server (Claude Desktop) | Mac mini | Always-on; Studio is kept free for inference, not serving |
| Development, git, test runs | MacBook Pro | Full repo lives here; minis are clones |

### The mental model

**Mac Studio is a job queue, not a workhorse.**
It does one thing — run large LLMs — and everything else waits in line. Ollama serializes requests to the same model, so Mini 2 and Mini 3 can both send extraction jobs simultaneously and they'll be processed one at a time. The minis don't block each other; they just share Studio's throughput.

**Mac minis run in parallel by default.**
Any CPU-bound step (embed locally, relate, crosswalk) can run on both minis simultaneously against their own DBs. This effectively doubles throughput. Mini 2 is the authoritative source for publishing (its DB is what gets pushed to HuggingFace).

**The MacBook is development-only.**
Never run the pipeline on the MacBook against the real DB — it lacks persistent storage for a 1.8 GB DB and you'd block your dev environment. Use it to push code, run `mcp_test.py` against a pulled snapshot, and build packages.

### Routing new work

When adding a new curriculum system, ask:

1. **Does it need PDF extraction?**
   - Yes → run the fetcher on a mini, point `OLLAMA_BASE_URL` at Mac Studio: `OLLAMA_BASE_URL=http://100.77.63.73:11434 OLLAMA_MODEL=gemma4:31b-it-q8_0`
   - No (web scrape / structured data) → run on either mini, no Studio needed

2. **Multiple fetchers at once?**
   - Run one fetcher per mini (Mini 2 → system A, Mini 3 → system B). Both send LLM calls to Studio; Studio serializes them. Net result: effectively single-threaded LLM work with zero idle time.

3. **After ingestion: embed → relate → crosswalk?**
   - Run on **both minis in parallel** — they each process their own DB and catch up to the same state.
   - Embed uses local Ollama (`localhost:11434`) — no Studio needed.
   - Relate and crosswalk are CPU-only — both minis run simultaneously.

4. **Rationale generation?**
   - Queue after fetchers finish (same Studio endpoint, serializes automatically).
   - Start with `--band high` to annotate confident mappings first.

### Model assignment

```
Mac Studio (64 GB):
  gemma4:31b-it-q8_0   ← PDF extraction (default for fetchers)
  qwen2.5:72b          ← rationale generation, heavy reasoning
  gemma3:27b           ← lighter extraction / eval
  nomic-embed-text     ← if minis are busy (rare)

Mac mini 2 (24 GB M4 Pro):
  gemma4:26b           ← can handle medium extraction locally if Studio is busy
  qwen2.5:14b          ← general tasks, eval
  nomic-embed-text     ← standard embeddings (always use local)

Mac mini 3 (16 GB M4):
  qwen2.5:14b          ← general tasks, eval
  nomic-embed-text     ← standard embeddings (always use local)
  ← never install models > 10 GB here
```

### Typical pipeline sequence

```
1. Fetcher(s)       → Mini 2 + Mini 3 simultaneously → LLM calls → Mac Studio
2. embed            → Mini 2 + Mini 3 simultaneously → local Ollama (nomic)
3. relate           → Mini 2 + Mini 3 simultaneously → CPU only
4. crosswalk        → Mini 2 + Mini 3 simultaneously → CPU only
5. rationale gen    → Mac Studio (qwen2.5:72b), sample --band high first
6. eval suite       → Mini 2 (authoritative DB)
7. pull DB          → MacBook ← sqlite3 .backup from Mini 2
8. mcp_test.py      → MacBook
9. ship             → MacBook (build + PyPI + HuggingFace)
```

## Slash command

Run `/devices` in Claude Code for a live status report across all machines.
