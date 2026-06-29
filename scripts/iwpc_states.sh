#!/usr/bin/env bash
# US state rationale rewrite routed to IWPC (RTX 3060, CUDA, qwen2.5:14b).
# Runs independently — doesn't conflict with Mini 2 AP/IB rationale or Studio IB fetch.

set -uo pipefail

REPO="$HOME/projects/intl-math-standards-mcp"
export DB_PATH="$REPO/data/common_core.db"
export OLLAMA_BASE_URL="http://100.70.170.62:11434"
export OLLAMA_MODEL="qwen2.5:14b"
export PATH="/Users/devos/.local/bin:$PATH"

LOG="$REPO/logs/iwpc_states_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$REPO/logs"
exec > >(tee -a "$LOG") 2>&1

cd "$REPO"

banner() {
    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  $1"
    echo "  $(date)"
    echo "══════════════════════════════════════════════════════════"
}

banner "IWPC state rationale pass started (qwen2.5:14b @ CUDA)"
echo "DB: $DB_PATH"

# Warmup
echo "Warming up qwen2.5:14b on IWPC..."
uv run python3 -c "
import httpx
resp = httpx.post('http://100.70.170.62:11434/api/chat', json={
    'model': 'qwen2.5:14b',
    'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False, 'options': {'num_ctx': 128}
}, timeout=120)
print('Ready:', resp.json()['message']['content'][:60])
" || echo "[WARN] warmup failed — will retry on first call"

run_state() {
    local state="$1"
    echo "" && echo "  → $state"
    uv run python scripts/crosswalk_rationale_gen.py \
        --system "$state" --sample 200 --force-rewrite 2>&1 || \
        echo "[WARN] $state skipped or errored"
}

# All major US states — split across math + ELA + science + SS + CS subjects
STATES=(
    ca tx ny fl ga wa ma nc pa oh il co
    va az tn mi nj wi mn or sc in mo ky
    al ak ar ct dc de hi ia id ks la me
    md ms mt nd ne nh nm nv ok ri sd ut
    vt wv wy
)

for state in "${STATES[@]}"; do
    for suffix in "" "-ela" "-sci" "-ss" "-cs"; do
        run_state "${state}${suffix}"
    done
done

banner "ALL DONE"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' state mappings with rationale'
     FROM crosswalk_mappings
     WHERE notes IS NOT NULL AND notes != ''
       AND source_system NOT LIKE 'ap%'
       AND source_system NOT LIKE 'ib%';" 2>/dev/null
