# StandardGraph Infrastructure

## Device inventory

| Device | Tailscale IP | Role |
|---|---|---|
| MacBook Pro | 100.118.151.10 | Development machine |
| Mac Studio | 100.77.63.73 | Primary Ollama host, ingestion runner |
| Mac mini | 100.101.100.97 | Secondary / eval |
| IWPC | 100.70.170.62 | Remote Windows PC |

## Network topology

```
MacBook Pro ──── Thunderbolt Bridge (169.254.1.1) ──── Mac Studio
     │                                                       │
     └────────────── Tailscale VPN ─────────────────────────┘
                          │
                     Mac mini, IWPC
```

- **Thunderbolt Bridge** — low-latency direct link between MacBook Pro and Mac Studio. The overnight pipeline uses `http://169.254.1.1:11434` to reach Mac Studio's Ollama (avoids Tailscale overhead for large embedding jobs).
- **Tailscale** — used for SSH access and general connectivity across all devices. Ollama on Mac Studio is also reachable over Tailscale at `http://100.77.63.73:11434`.

## Ollama

### Mac Studio (primary)

- **URL:** `http://169.254.1.1:11434` (Thunderbolt) or `http://100.77.63.73:11434` (Tailscale)
- **Models used by pipeline:**
  - `gemma4:31b-it-q8_0` — PDF→JSON extraction for international and AP curricula
  - `nomic-embed-text` — 768-dim embeddings for all standards
- Check what's loaded: `curl -sf http://100.77.63.73:11434/api/ps`

### Mac mini (secondary)

- Used for eval runs with local LLM judge (`--local-judge` flag in eval scripts)
- Model: `gemma4:27b` (or similar capacity model)

## SSH access

SSH user: `ianwang` on all devices.

**MacBook Pro public key** (authorize this on each machine):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP53tUmEA81HZQWErdYK/BcRc+lNOTaC0/YCj58aJMci ianwang@Ians-MacBook-Pro.local
```

To authorize on a machine (run locally on the target device):
```bash
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP53tUmEA81HZQWErdYK/BcRc+lNOTaC0/YCj58aJMci ianwang@Ians-MacBook-Pro.local" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
```

**Status:** Mac Studio and Mac mini SSH access from MacBook Pro not yet authorized (as of 2026-06-26).

## Overnight pipeline

Runs on Mac Studio via `scripts/overnight_run.sh`. Triggered manually or via launchd.

```bash
# Run from repo root on Mac Studio
bash scripts/overnight_run.sh

# Watch progress from MacBook Pro (once SSH is authorized)
ssh ianwang@100.77.63.73 "bash ~/projects/standardgraph/scripts/dashboard.sh --watch"
```

- Uses `data/common_core.db` (repo-local DB, not the installed user DB)
- Logs to `logs/overnight_YYYYMMDD_HHMMSS.log`
- Lock file at `.pipeline.lock` prevents overlapping runs
- Restarts Claude Desktop on completion to refresh MCP server

## Common remote commands

```bash
# Check Mac Studio Ollama (no SSH needed)
curl -sf http://100.77.63.73:11434/api/ps

# SSH into Mac Studio (once key is authorized)
ssh ianwang@100.77.63.73

# SSH into Mac mini
ssh ianwang@100.101.100.97

# Tail latest pipeline log (from Mac Studio)
ssh ianwang@100.77.63.73 "ls -t ~/projects/standardgraph/logs/overnight_*.log | head -1 | xargs tail -f"
```

## Slash command

Run `/devices` in Claude Code to get a live status report — pings all devices, SSHes in for uptime/Ollama/disk/pipeline status, and summarizes in a table.
