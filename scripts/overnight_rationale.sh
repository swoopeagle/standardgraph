#!/usr/bin/env bash
# Overnight rationale generation + crosswalk review for US math/science focus.
#
# Crosswalk direction: non-hub systems → hub (CCSS, NGSS, etc.)
# So --system is always the non-hub (AP, state, IB), not the hub itself.
#
# Run from Mini 2:
#   OLLAMA_BASE_URL=http://100.77.63.73:11434 bash scripts/overnight_rationale.sh
#
# If IWPC is online, low-band state mappings run there (qwen2.5:14b) in
# parallel while Studio handles high/mid-band (qwen2.5:72b).
#
# Runtime: ~8–12 hours single-host; ~5–7 hours with IWPC assisting.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$REPO_DIR/data/common_core.db}"
STUDIO_URL="${OLLAMA_BASE_URL:-http://100.77.63.73:11434}"
IWPC_URL="http://100.70.170.62:11434"
STUDIO_MODEL="qwen2.5:72b"
IWPC_MODEL="qwen2.5:14b"
LOG_DIR="$REPO_DIR/logs"
LOG="$LOG_DIR/rationale_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

# Auto-detect IWPC
if curl -sf --max-time 3 "$IWPC_URL/api/tags" >/dev/null 2>&1; then
    IWPC_ONLINE=true
else
    IWPC_ONLINE=false
fi

export DB_PATH
export OLLAMA_BASE_URL="$STUDIO_URL"
export OLLAMA_MODEL="$STUDIO_MODEL"

run() {
    local label="$1"; shift
    echo "" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    echo "  $label" | tee -a "$LOG"
    echo "  $(date)" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG"
}

# Run via IWPC (qwen2.5:14b) — called only when IWPC is online
run_iwpc() {
    local label="$1"; shift
    echo "" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    echo "  $label  [IWPC / qwen2.5:14b]" | tee -a "$LOG"
    echo "  $(date)" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    OLLAMA_BASE_URL="$IWPC_URL" OLLAMA_MODEL="$IWPC_MODEL" \
        uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG"
}

warmup() {
    local url="$1" model="$2"
    echo "Warming up $model @ $url …" | tee -a "$LOG"
    uv run python3 -c "
import httpx, sys
resp = httpx.post('$url/api/chat', json={
    'model': '$model', 'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False, 'options': {'num_ctx': 128}
}, timeout=600)
print('Ready: ' + resp.json()['message']['content'][:60])
" 2>&1 | tee -a "$LOG"
}

echo "Overnight rationale run started at $(date)" | tee "$LOG"
echo "DB:     $DB_PATH" | tee -a "$LOG"
echo "Studio: $STUDIO_MODEL @ $STUDIO_URL" | tee -a "$LOG"
echo "IWPC:   $($IWPC_ONLINE && echo "$IWPC_MODEL @ $IWPC_URL" || echo 'offline — Studio only')" | tee -a "$LOG"

# Warm up Studio (evicting gemma4:31b → loading qwen2.5:72b takes 3–5 min)
echo "" | tee -a "$LOG"
warmup "$STUDIO_URL" "$STUDIO_MODEL"

# Warm up IWPC if online
if $IWPC_ONLINE; then
    warmup "$IWPC_URL" "$IWPC_MODEL"
fi
echo "" | tee -a "$LOG"

# ── Phase 1: AP Math → CCSS — high confidence (Studio) ───────────────────────
run "AP Calc AB → CCSS  [high]"   --system ap-calc-ab  --band high  --sample 0
run "AP Calc BC → CCSS  [high]"   --system ap-calc-bc  --band high  --sample 0
run "AP Stats → CCSS    [high]"   --system ap-stats    --band high  --sample 0
run "AP Precalc → CCSS  [high]"   --system ap-precalc  --band high  --sample 0

# ── Phase 2: AP Science → NGSS — high confidence (Studio) ────────────────────
run "AP Bio → NGSS      [high]"   --system ap-bio      --band high  --sample 0
run "AP Chem → NGSS     [high]"   --system ap-chem     --band high  --sample 0
run "AP Phys 1 → NGSS   [high]"   --system ap-phys-1   --band high  --sample 0
run "AP Phys 2 → NGSS   [high]"   --system ap-phys-2   --band high  --sample 0
run "AP Env → NGSS      [high]"   --system ap-env      --band high  --sample 0

# ── Phase 3: IB Math → CCSS — high confidence (Studio) ───────────────────────
run "IB-DP → CCSS       [high]"   --system ib-dp       --band high  --sample 0
run "IB-MYP → CCSS      [high]"   --system ib-myp      --band high  --sample 0

# ── Phase 4: AP Math → CCSS — mid confidence (Studio) ────────────────────────
run "AP Calc AB → CCSS  [mid]"    --system ap-calc-ab  --band mid   --sample 0
run "AP Calc BC → CCSS  [mid]"    --system ap-calc-bc  --band mid   --sample 0
run "AP Stats → CCSS    [mid]"    --system ap-stats    --band mid   --sample 0
run "AP Precalc → CCSS  [mid]"    --system ap-precalc  --band mid   --sample 0

# ── Phase 5: AP Science → NGSS — mid confidence (Studio) ─────────────────────
run "AP Bio → NGSS      [mid]"    --system ap-bio      --band mid   --sample 0
run "AP Chem → NGSS     [mid]"    --system ap-chem     --band mid   --sample 0
run "AP Phys 1 → NGSS   [mid]"    --system ap-phys-1   --band mid   --sample 0
run "AP Phys 2 → NGSS   [mid]"    --system ap-phys-2   --band mid   --sample 0
run "AP Env → NGSS      [mid]"    --system ap-env      --band mid   --sample 0

# ── Phase 6: IB Math — mid confidence (Studio) ───────────────────────────────
run "IB-DP → CCSS       [mid]"    --system ib-dp       --band mid   --sample 0
run "IB-MYP → CCSS      [mid]"    --system ib-myp      --band mid   --sample 0

# ── Phase 7: US state sample ──────────────────────────────────────────────────
# High-volume states sampled at 200 each.
# If IWPC is online: Studio and IWPC run different states in parallel.
# If offline: Studio runs all states sequentially.
if $IWPC_ONLINE; then
    # Even states → Studio (72b); odd states → IWPC (14b), interleaved
    STUDIO_STATES=(ca ny wa ma pa)
    IWPC_STATES=(tx fl ga nc oh)

    for state in "${STUDIO_STATES[@]}"; do
        run "State $state → CCSS [n=200, Studio]" --system "$state" --sample 200 &
        STUDIO_BG=$!
        # Pull one IWPC state while Studio runs
        if [ ${#IWPC_STATES[@]} -gt 0 ]; then
            iwpc_state="${IWPC_STATES[0]}"
            IWPC_STATES=("${IWPC_STATES[@]:1}")
            run_iwpc "State $iwpc_state → CCSS [n=200, IWPC]" --system "$iwpc_state" --sample 200
        fi
        wait $STUDIO_BG
    done
    # Any remaining IWPC states
    for state in "${IWPC_STATES[@]}"; do
        run_iwpc "State $state → CCSS [n=200, IWPC]" --system "$state" --sample 200
    done
else
    for state in ca tx ny fl ga wa ma nc pa oh; do
        run "State $state → CCSS [n=200]" --system "$state" --sample 200
    done
fi

# ── Phase 8: Review — re-score to flag bad mappings (Studio) ─────────────────
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
