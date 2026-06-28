#!/usr/bin/env bash
# Overnight rationale generation + crosswalk review for US math/science focus.
#
# Run this on Mac mini 2 (or any machine with access to Mac Studio):
#   OLLAMA_BASE_URL=http://100.77.63.73:11434 bash scripts/overnight_rationale.sh
#
# Runtime: ~10–14 hours (5,000–6,000 mappings at ~6/min with qwen2.5:72b)
# All jobs queue to Mac Studio's Ollama — no coordination needed.

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

# ── Phase 1: US Math hierarchy — high confidence first ────────────────────────
# CCSS ↔ AP Math
run "CCSS → AP Calc AB  [high]"   --system ccss  --target ap-calc-ab  --band high
run "CCSS → AP Calc BC  [high]"   --system ccss  --target ap-calc-bc  --band high
run "CCSS → AP Stats    [high]"   --system ccss  --target ap-stats     --band high
run "CCSS → AP Precalc  [high]"   --system ccss  --target ap-precalc   --band high

# AP Math ↔ IB Math
run "AP Calc AB → IB-DP [high]"   --system ap-calc-ab  --target ib-dp  --band high
run "AP Calc BC → IB-DP [high]"   --system ap-calc-bc  --target ib-dp  --band high
run "AP Stats → IB-DP   [high]"   --system ap-stats    --target ib-dp  --band high
run "CCSS → IB-MYP      [high]"   --system ccss        --target ib-myp --band high
run "CCSS → IB-DP       [high]"   --system ccss        --target ib-dp  --band high

# ── Phase 2: Science hierarchy — high confidence ──────────────────────────────
run "NGSS → AP Bio      [high]"   --system ngss  --target ap-bio      --band high
run "NGSS → AP Chem     [high]"   --system ngss  --target ap-chem     --band high
run "NGSS → AP Phys 1   [high]"   --system ngss  --target ap-phys-1   --band high
run "NGSS → AP Phys 2   [high]"   --system ngss  --target ap-phys-2   --band high
run "NGSS → AP Env      [high]"   --system ngss  --target ap-env      --band high

# ── Phase 3: US Math — mid confidence (catches useful near-matches) ───────────
run "CCSS → AP Calc AB  [mid]"    --system ccss  --target ap-calc-ab  --band mid
run "CCSS → AP Calc BC  [mid]"    --system ccss  --target ap-calc-bc  --band mid
run "CCSS → AP Stats    [mid]"    --system ccss  --target ap-stats     --band mid
run "CCSS → IB-DP       [mid]"    --system ccss  --target ib-dp       --band mid
run "CCSS → IB-MYP      [mid]"    --system ccss  --target ib-myp      --band mid

# ── Phase 4: Science — mid confidence ────────────────────────────────────────
run "NGSS → AP Bio      [mid]"    --system ngss  --target ap-bio      --band mid
run "NGSS → AP Chem     [mid]"    --system ngss  --target ap-chem     --band mid
run "NGSS → AP Phys 1   [mid]"    --system ngss  --target ap-phys-1   --band mid

# ── Phase 5: Crosswalk review — flag bad mappings in mid band ─────────────────
# (Same model, same queue — runs after rationale gen completes above)
run "Review: CCSS↔AP math mid"    --system ccss  --target ap-calc-ab  --band mid  --review-only
run "Review: NGSS↔AP sci  mid"    --system ngss  --target ap-bio      --band mid  --review-only

echo "" | tee -a "$LOG"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
echo "  ALL DONE $(date)" | tee -a "$LOG"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"

# Print summary from DB
sqlite3 "$DB_PATH" "
  SELECT
    'Mappings with rationale: ' || COUNT(*) FROM crosswalk_mappings WHERE notes IS NOT NULL AND notes != '';
  SELECT
    'Mappings flagged for review: ' || COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review = 1;
" | tee -a "$LOG"
