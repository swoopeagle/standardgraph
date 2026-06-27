# StandardGraph Infrastructure

## Device inventory

| Device | Chip | RAM | Tailscale IP | SSH user | Role |
|---|---|---|---|---|---|
| MacBook Pro | — | — | 100.118.151.10 | `ianwang` | Development machine |
| Mac Studio | M1 Max | 64 GB | 100.77.63.73 | `ianwangm1max` | Ollama host (LLM inference only) |
| Mac mini 2 | M4 Pro | 24 GB | 100.101.100.96 | `devos` | Pipeline runner, MCP server |
| Mac mini 3 | M4 | 16 GB | 100.123.114.101 | `devos` | Pipeline runner, MCP server |
| IWPC | — | — | 100.70.170.62 | — | Remote Windows PC |

> The project lives at `~/projects/intl-math-standards-mcp/` on both Mac minis (old project name — same codebase as `standardgraph`).

## Network topology

```
MacBook Pro ──── Thunderbolt Bridge (169.254.1.1) ──── Mac Studio (Ollama)
     │                                                       │
     └────────────── Tailscale VPN ─────────────────────────┘
                          │
               Mac mini 2 (.96), Mac mini 3 (.101), IWPC
```

- **Thunderbolt Bridge** — low-latency direct link between MacBook Pro and Mac Studio. The overnight pipeline uses `http://169.254.1.1:11434` to reach Mac Studio's Ollama.
- **Tailscale** — SSH access and general connectivity across all devices. Mac Studio Ollama also reachable at `http://100.77.63.73:11434`.

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

| Device | RAM | Safe model limit |
|---|---|---|
| Mac Studio | 64 GB | 47 GB (qwen2.5:72b) |
| Mac mini 2 | 24 GB | ~18 GB (e.g. gemma3:12b) |
| Mac mini 3 | 16 GB | ~10 GB (e.g. gemma3:4b, nomic-embed-text only) |

Neither Mac mini currently has Ollama installed — all inference routes to Mac Studio.

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
- IWPC — not yet authorized

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

## Slash command

Run `/devices` in Claude Code for a live status report across all machines.
