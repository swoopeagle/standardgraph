Check the status of all machines on the StandardGraph Tailscale network.

Tailscale devices:
- Mac Studio: ianwangm1max@100.77.63.73 (Ollama host, no repo)
- Mac mini 2: devos@100.101.100.96 (pipeline + MCP server)
- Mac mini 3: devos@100.123.114.101 (pipeline + MCP server)
- IWPC: 100.70.170.62 (Windows, SSH not yet set up)
- MacBook Pro (local): 100.118.151.10

Project path on Mac minis: ~/projects/intl-math-standards-mcp/

Step 1 — ping all remotes in parallel:
```bash
ping -c 1 -W 2000 100.77.63.73 && echo "Mac Studio REACHABLE" || echo "Mac Studio UNREACHABLE"
ping -c 1 -W 2000 100.101.100.96 && echo "Mac mini 2 REACHABLE" || echo "Mac mini 2 UNREACHABLE"
ping -c 1 -W 2000 100.123.114.101 && echo "Mac mini 3 REACHABLE" || echo "Mac mini 3 UNREACHABLE"
ping -c 1 -W 2000 100.70.170.62 && echo "IWPC REACHABLE" || echo "IWPC UNREACHABLE"
```

Step 2 — Mac Studio (Ollama only, no SSH needed for status):
```bash
curl -sf --max-time 5 http://100.77.63.73:11434/api/ps | python3 -c "import sys,json; d=json.load(sys.stdin); models=d.get('models',[]); print('Ollama UP —', [m['name'] + ' ' + str(round(m.get('size_vram',0)/1e9,1)) + 'GB' for m in models] or ['idle'])"
```

Step 3 — Mac mini 2:
```bash
ssh -o ConnectTimeout=5 devos@100.101.100.96 "
  echo '--- uptime ---' && uptime &&
  echo '--- ollama ---' && (curl -sf http://localhost:11434/api/ps | python3 -c 'import sys,json; d=json.load(sys.stdin); models=d.get(\"models\",[]); print(len(models),\"model(s):\", [m[\"name\"] for m in models])' 2>/dev/null || echo 'not running') &&
  echo '--- pipeline ---' && (ps aux | grep -E 'overnight|reingest|embed|relate|crosswalk' | grep -v grep || echo 'none') &&
  echo '--- lock ---' && (ls ~/projects/intl-math-standards-mcp/.pipeline.lock 2>/dev/null && echo 'LOCKED' || echo 'no lock') &&
  echo '--- db ---' && sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db \"SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;\" 2>/dev/null &&
  echo '--- disk ---' && df -h / | tail -1
"
```

Step 4 — Mac mini 3 (same as above with different IP):
```bash
ssh -o ConnectTimeout=5 devos@100.123.114.101 "
  echo '--- uptime ---' && uptime &&
  echo '--- ollama ---' && (curl -sf http://localhost:11434/api/ps | python3 -c 'import sys,json; d=json.load(sys.stdin); models=d.get(\"models\",[]); print(len(models),\"model(s):\", [m[\"name\"] for m in models])' 2>/dev/null || echo 'not running') &&
  echo '--- pipeline ---' && (ps aux | grep -E 'overnight|reingest|embed|relate|crosswalk' | grep -v grep || echo 'none') &&
  echo '--- lock ---' && (ls ~/projects/intl-math-standards-mcp/.pipeline.lock 2>/dev/null && echo 'LOCKED' || echo 'no lock') &&
  echo '--- db ---' && sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db \"SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;\" 2>/dev/null &&
  echo '--- disk ---' && df -h / | tail -1
"
```

Report as a clean table:
| Device | Status | Ollama | Pipeline | DB | Disk free |
and note any lock files (stale from power loss — safe to remove with `rm .pipeline.lock`).

If a pipeline was in progress on either Mac mini, tail the latest log:
```bash
ssh devos@100.101.100.96 "ls -t ~/projects/intl-math-standards-mcp/logs/*.log | head -1 | xargs tail -20"
```
