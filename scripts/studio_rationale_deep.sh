#!/usr/bin/env bash
# Deep rationale rewrite on Mac Studio (qwen2.5:72b) — designed to run all night.
# Covers: ALL AP systems, ALL IB systems, all international systems, broad state sample.
# Runs independently from Mini 2's ongoing rationale work.

set -uo pipefail

REPO="$HOME/projects/intl-math-standards-mcp"
export DB_PATH="$REPO/data/common_core.db"
export OLLAMA_BASE_URL="http://100.77.63.73:11434"
export OLLAMA_MODEL="qwen2.5:72b"
export PATH="/Users/devos/.local/bin:$PATH"

LOG="$REPO/logs/studio_rationale_deep_$(date +%Y%m%d_%H%M%S).log"
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

run() {
    local label="$1"; shift
    banner "$label  [Studio / qwen2.5:72b]"
    OLLAMA_BASE_URL="http://100.77.63.73:11434" OLLAMA_MODEL="qwen2.5:72b" \
        uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 || \
        echo "[WARN] exited non-zero — continuing"
}

banner "Studio deep rationale run started"
echo "DB: $DB_PATH"
echo "Goal: force-rewrite AP + IB + international with qwen2.5:72b"

# Warmup
echo "Warming up qwen2.5:72b..."
uv run python3 -c "
import httpx
resp = httpx.post('http://100.77.63.73:11434/api/chat', json={
    'model': 'qwen2.5:72b',
    'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False, 'options': {'num_ctx': 128}
}, timeout=300)
print('Ready:', resp.json()['message']['content'][:60])
" || echo "[WARN] warmup failed — continuing"

# ── Phase 1: ALL AP Math — every band, every mapping ─────────────────────────
banner "Phase 1: AP Math (all mappings, force-rewrite)"
run "AP Calc AB → CCSS"    --system ap-calc-ab  --sample 0 --force-rewrite
run "AP Calc BC → CCSS"    --system ap-calc-bc  --sample 0 --force-rewrite
run "AP Stats → CCSS"      --system ap-stats    --sample 0 --force-rewrite
run "AP Precalc → CCSS"    --system ap-precalc  --sample 0 --force-rewrite

# ── Phase 2: ALL AP Science ───────────────────────────────────────────────────
banner "Phase 2: AP Science (all mappings, force-rewrite)"
run "AP Bio → NGSS"        --system ap-bio      --sample 0 --force-rewrite
run "AP Chem → NGSS"       --system ap-chem     --sample 0 --force-rewrite
run "AP Phys 1 → NGSS"     --system ap-phys-1   --sample 0 --force-rewrite
run "AP Phys 2 → NGSS"     --system ap-phys-2   --sample 0 --force-rewrite
run "AP Env → NGSS"        --system ap-env      --sample 0 --force-rewrite

# ── Phase 3: ALL IB ───────────────────────────────────────────────────────────
banner "Phase 3: IB (all mappings, force-rewrite)"
run "IB-DP → CCSS"         --system ib-dp       --sample 0 --force-rewrite
run "IB-MYP → CCSS"        --system ib-myp      --sample 0 --force-rewrite
run "IB-PYP → CCSS"        --system ib-pyp      --sample 0 --force-rewrite

# ── Phase 4: International systems ───────────────────────────────────────────
banner "Phase 4: International (all mappings, force-rewrite)"
for system in sg-moe jp-mext nz-moe hk-edb in-ncert gh-nacca za-caps \
              rw-reb ph-deped ca-qc ca-ab ca-bc ca-mb ca-nb ca-on ca-sk \
              pt-dge it-miur fr-men de-kmk; do
    run "$system" --system "$system" --sample 0 --force-rewrite
done

# ── Phase 5: Broad state pass (500 per state/subject) ─────────────────────────
banner "Phase 5: US state broad sample (n=500, force-rewrite)"
for state in ca tx ny fl ga wa ma nc pa oh il co va az tn mi nj wi mn or sc \
             in mo ky al ar ct hi ia id ks la me md ms mt nd ne nh nm nv \
             ok ri sd ut vt wv wy; do
    for suffix in "" "-ela" "-sci" "-ss" "-cs"; do
        run "State ${state}${suffix} [n=500]" \
            --system "${state}${suffix}" --sample 500 --force-rewrite
    done
done

banner "ALL DONE"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' mappings, ' ||
     SUM(CASE WHEN notes IS NOT NULL AND notes!='' THEN 1 ELSE 0 END) || ' with rationale'
     FROM crosswalk_mappings;" 2>/dev/null
echo "Log: $LOG"
