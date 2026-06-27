Check the status of all machines on the StandardGraph Tailscale network.

Tailscale IPs:
- Mac Studio: 100.77.63.73 (Ollama host, ingestion machine)
- Mac mini: 100.101.100.97
- IWPC: 100.70.170.62
- MacBook Pro (local): 100.118.151.10

For each remote device, run a ping first to confirm reachability:
```bash
ping -c 1 -W 2 <ip>
```

For reachable machines, SSH in and collect:
```bash
ssh -o ConnectTimeout=5 ianwang@<ip> "
  echo '=== uptime ===' && uptime &&
  echo '=== ollama ===' && (curl -sf http://localhost:11434/api/ps 2>/dev/null || echo 'ollama not running') &&
  echo '=== pipeline ===' && (pgrep -a python | grep -v grep || echo 'no python processes') &&
  echo '=== disk ===' && df -h / | tail -1
"
```

For Mac Studio specifically, also check:
```bash
ssh -o ConnectTimeout=5 ianwang@100.77.63.73 "
  curl -sf http://localhost:11434/api/ps | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(m[\"name\"], round(m.get(\"size_vram\",0)/1e9,1),\"GB VRAM\") for m in d.get(\"models\",[])]' 2>/dev/null || echo 'no models loaded'
"
```

Report as a clean table:
| Device | Status | Ollama | Active jobs | Disk free |
and note if SSH fails (key not yet authorized — Mac Studio and Mac mini may need key setup).

If overnight pipeline is running on Mac Studio, also tail the latest log:
```bash
ssh ianwang@100.77.63.73 "ls -t ~/projects/standardgraph/logs/overnight_*.log 2>/dev/null | head -1 | xargs tail -20 2>/dev/null"
```
