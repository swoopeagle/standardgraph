# IWPC Setup — RTX 3060 as Second Ollama Host

IWPC (Windows PC, Tailscale IP `100.70.170.62`) runs Ollama with CUDA acceleration.
It acts as a **second LLM host**, parallel to Mac Studio, handling:

- **Embeddings** (`nomic-embed-text`) — CUDA batch throughput beats Apple Silicon
- **Mid/low-band rationale gen** (`qwen2.5:14b`) — frees Studio for high-band (72b) only

The pipeline on the minis calls IWPC over Tailscale, exactly like Mac Studio.
No repo clone needed on Windows.

---

## One-time setup (do this on IWPC)

### 1. Confirm Tailscale is running

Open Tailscale from the system tray. It should show a green icon and the IP
`100.70.170.62`. If not, sign in with the same Tailscale account.

### 2. Install Ollama

Download and run the installer from https://ollama.com/download/windows

Ollama installs as a Windows service and starts automatically.

### 3. Allow Ollama to listen on all interfaces

By default Ollama only listens on `localhost`, so the minis can't reach it.
Set the environment variable in PowerShell (run as Administrator):

```powershell
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "Machine")
```

Then restart the Ollama service:
```powershell
Stop-Service Ollama
Start-Service Ollama
```

Or reboot — whichever is easier.

### 4. Open Windows Firewall for port 11434

```powershell
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
```

### 5. Pull the models

In PowerShell or Command Prompt:
```
ollama pull nomic-embed-text
ollama pull qwen2.5:14b
```

`nomic-embed-text` is 274 MB. `qwen2.5:14b` is ~9 GB. Both fit in 12 GB VRAM.

### 6. Verify from a Mac mini

SSH into Mini 2 and test:
```bash
curl http://100.70.170.62:11434/api/tags
```

You should see a JSON response listing `nomic-embed-text` and `qwen2.5:14b`.

---

## How the pipeline uses IWPC

Once IWPC is reachable, `post_ingest_pipeline.sh` and `overnight_rationale.sh`
auto-detect it and route work there:

| Job | If IWPC reachable | If IWPC offline |
|---|---|---|
| Embed | Route to IWPC (CUDA) | Fall back to localhost on each mini |
| Rationale gen low-band | IWPC (`qwen2.5:14b`) | Skip low-band (Studio handles high+mid only) |
| Rationale gen high/mid | Mac Studio (`qwen2.5:72b`) | Mac Studio (unchanged) |

The pipeline checks reachability with a 3-second curl — zero config change needed
when IWPC is on or off.

---

## Troubleshooting

**`Connection refused` from a mini**
- Check Ollama is running: `curl http://localhost:11434/api/tags` on IWPC
- Check OLLAMA_HOST is set: `[System.Environment]::GetEnvironmentVariable("OLLAMA_HOST","Machine")`
- Check firewall: `Get-NetFirewallRule -DisplayName "Ollama"`

**Model loads slowly on first call**
Normal — CUDA model load takes 10-30s. Subsequent calls are fast.

**`qwen2.5:14b` slower than expected**
Check VRAM usage in Task Manager → Performance → GPU. If it shows high shared
memory usage, the model is spilling to system RAM. This shouldn't happen with
12 GB VRAM + 9 GB model, but check no other GPU process is running.
