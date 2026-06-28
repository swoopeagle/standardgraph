#!/usr/bin/env bash
# Overnight rationale generation + crosswalk review for US math/science focus.
#
# Crosswalk direction: non-hub systems → hub (CCSS, NGSS, etc.)
# So --system is always the non-hub (AP, state, IB), not the hub itself.
#
# Run from Mini 2:
#   OLLAMA_BASE_URL=http://100.77.63.73:11434 bash scripts/overnight_rationale.sh
#
# Runtime: ~8–12 hours (5,000+ mappings at ~6–8/min with qwen2.5:72b)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$REPO_DIR/data/common_core.db}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://100.77.63.73:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:72b}"
LOG_DIR="$REPO_DIR/logs"
LOG="$LOG_DIR/rationale_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"
export DB_PATH OLLAMA_BASE_URL OLLAMA_MODEL

run() {
    local label="$1"; shift
    echo "" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    echo "  $label" | tee -a "$LOG"
    echo "  $(date)" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG"
}

echo "Overnight rationale run started at $(date)" | tee "$LOG"
echo "DB:    $DB_PATH" | tee -a "$LOG"
echo "Model: $OLLAMA_MODEL @ $OLLAMA_BASE_URL" | tee -a "$LOG"

# Warm up the model — evicting previous model and loading qwen2.5:72b can take
# 5+ minutes. Ping it once and wait until we get a response before processing.
echo "" | tee -a "$LOG"
echo "Warming up $OLLAMA_MODEL (may take several minutes) …" | tee -a "$LOG"
python3 -c "
import httpx, sys, os
url = os.environ['OLLAMA_BASE_URL'] + '/api/chat'
model = os.environ['OLLAMA_MODEL']
resp = httpx.post(url, json={
    'model': model, 'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False, 'options': {'num_ctx': 128}
}, timeout=600)
print('Model ready: ' + resp.json()['message']['content'][:60])
" 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Phase 1: AP Math → CCSS — high confidence first ──────────────────────────
# AP courses are the SOURCE; CCSS is the target hub.
run "AP Calc AB → CCSS  [high]"   --system ap-calc-ab  --band high  --sample 0
run "AP Calc BC → CCSS  [high]"   --system ap-calc-bc  --band high  --sample 0
run "AP Stats → CCSS    [high]"   --system ap-stats    --band high  --sample 0
run "AP Precalc → CCSS  [high]"   --system ap-precalc  --band high  --sample 0

# ── Phase 2: AP Science → NGSS — high confidence ─────────────────────────────
run "AP Bio → NGSS      [high]"   --system ap-bio      --band high  --sample 0
run "AP Chem → NGSS     [high]"   --system ap-chem     --band high  --sample 0
run "AP Phys 1 → NGSS   [high]"   --system ap-phys-1   --band high  --sample 0
run "AP Phys 2 → NGSS   [high]"   --system ap-phys-2   --band high  --sample 0
run "AP Env → NGSS      [high]"   --system ap-env      --band high  --sample 0

# ── Phase 3: IB Math → CCSS — high confidence ────────────────────────────────
run "IB-DP → CCSS       [high]"   --system ib-dp       --band high  --sample 0
run "IB-MYP → CCSS      [high]"   --system ib-myp      --band high  --sample 0

# ── Phase 4: AP Math → CCSS — mid confidence ─────────────────────────────────
run "AP Calc AB → CCSS  [mid]"    --system ap-calc-ab  --band mid   --sample 0
run "AP Calc BC → CCSS  [mid]"    --system ap-calc-bc  --band mid   --sample 0
run "AP Stats → CCSS    [mid]"    --system ap-stats    --band mid   --sample 0
run "AP Precalc → CCSS  [mid]"    --system ap-precalc  --band mid   --sample 0

# ── Phase 5: AP Science → NGSS — mid confidence ──────────────────────────────
run "AP Bio → NGSS      [mid]"    --system ap-bio      --band mid   --sample 0
run "AP Chem → NGSS     [mid]"    --system ap-chem     --band mid   --sample 0
run "AP Phys 1 → NGSS   [mid]"    --system ap-phys-1   --band mid   --sample 0
run "AP Phys 2 → NGSS   [mid]"    --system ap-phys-2   --band mid   --sample 0
run "AP Env → NGSS      [mid]"    --system ap-env      --band mid   --sample 0

# ── Phase 6: IB Math — mid confidence ────────────────────────────────────────
run "IB-DP → CCSS       [mid]"    --system ib-dp       --band mid   --sample 0
run "IB-MYP → CCSS      [mid]"    --system ib-myp      --band mid   --sample 0

# ── Phase 7: US state math high-volume sample (all bands, sampled) ────────────
# States have many mappings — sample 200 each from the largest.
for state in ca tx ny fl ga wa ma nc pa oh; do
    run "State $state → CCSS [all bands, n=200]" \
        --system "$state" --sample 200
done

# ── Phase 8: Review — re-score mid-band to flag bad mappings ─────────────────
run "Review: AP math mid [flag bad]" \
    --system ap-calc-ab --band mid --review-only --sample 0
run "Review: AP sci mid  [flag bad]" \
    --system ap-bio     --band mid --review-only --sample 0

echo "" | tee -a "$LOG"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
echo "  ALL DONE $(date)" | tee -a "$LOG"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"

sqlite3 "$DB_PATH" \
    "SELECT 'Mappings with rationale: ' || COUNT(*) FROM crosswalk_mappings WHERE notes IS NOT NULL AND notes != '';" \
    2>/dev/null | tee -a "$LOG"
sqlite3 "$DB_PATH" \
    "SELECT 'Mappings flagged for review: ' || COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review = 1;" \
    2>/dev/null | tee -a "$LOG"
