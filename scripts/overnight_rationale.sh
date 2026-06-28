#!/usr/bin/env bash
# Three-stream overnight rationale generation.
#
# Crosswalk direction: non-hub → hub (AP/IB/state are sources; CCSS/NGSS are targets).
# --system is always the non-hub system code.
#
# Stream A — Mac Studio   qwen2.5:72b   AP Math high+mid       (best model for calculus→algebra)
# Stream B — Mini 2 local gemma4:26b    AP Science + IB high+mid (parallel with A; best Mini 2 can fit)
# Stream C — IWPC         qwen2.5:14b   US state sample        (CUDA volume throughput)
#
# A and B run in parallel. C interleaves with A during the state phase.
#
# Run from Mini 2:
#   OLLAMA_BASE_URL=http://169.254.1.1:11434 bash scripts/overnight_rationale.sh
#
# Runtime: ~4–6 hours (vs ~8–12 single-stream)

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$REPO_DIR/data/common_core.db}"

STUDIO_URL="${OLLAMA_BASE_URL:-http://169.254.1.1:11434}"
STUDIO_MODEL="qwen2.5:72b"

MINI2_URL="http://localhost:11434"
MINI2_MODEL="gemma4:26b"

IWPC_URL="http://100.70.170.62:11434"
IWPC_MODEL="qwen2.5:14b"

LOG_DIR="$REPO_DIR/logs"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$LOG_DIR/rationale_${TS}.log"
LOG_M2="$LOG_DIR/rationale_mini2_${TS}.log"

mkdir -p "$LOG_DIR"

# Auto-detect IWPC
if curl -sf --max-time 3 "$IWPC_URL/api/tags" >/dev/null 2>&1; then
    IWPC_ONLINE=true
else
    IWPC_ONLINE=false
fi

export DB_PATH

# ── Helpers ──────────────────────────────────────────────────────────────────

banner() {
    local label="$1" logfile="$2"
    echo "" | tee -a "$logfile"
    echo "══════════════════════════════════════════════════════════" | tee -a "$logfile"
    echo "  $label" | tee -a "$logfile"
    echo "  $(date)" | tee -a "$logfile"
    echo "══════════════════════════════════════════════════════════" | tee -a "$logfile"
}

# Stream A: Mac Studio (qwen2.5:72b)
run() {
    local label="$1"; shift
    banner "$label  [Studio / $STUDIO_MODEL]" "$LOG"
    OLLAMA_BASE_URL="$STUDIO_URL" OLLAMA_MODEL="$STUDIO_MODEL" \
        uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG"
}

# Stream B: Mini 2 local (gemma4:26b)
run_mini2() {
    local label="$1"; shift
    banner "$label  [Mini 2 / $MINI2_MODEL]" "$LOG_M2"
    OLLAMA_BASE_URL="$MINI2_URL" OLLAMA_MODEL="$MINI2_MODEL" \
        uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG_M2"
}

# Stream C: IWPC (qwen2.5:14b)
run_iwpc() {
    local label="$1"; shift
    banner "$label  [IWPC / $IWPC_MODEL]" "$LOG"
    OLLAMA_BASE_URL="$IWPC_URL" OLLAMA_MODEL="$IWPC_MODEL" \
        uv run python scripts/crosswalk_rationale_gen.py "$@" 2>&1 | tee -a "$LOG"
}

warmup() {
    local url="$1" model="$2" logfile="$3"
    echo "Warming up $model @ $url …" | tee -a "$logfile"
    uv run python3 -c "
import httpx
resp = httpx.post('$url/api/chat', json={
    'model': '$model', 'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False, 'options': {'num_ctx': 128}
}, timeout=600)
print('Ready: ' + resp.json()['message']['content'][:60])
" 2>&1 | tee -a "$logfile"
}

# ── Startup ───────────────────────────────────────────────────────────────────

echo "Overnight rationale run started at $(date)" | tee "$LOG"
echo "DB:     $DB_PATH" | tee -a "$LOG"
echo "Stream A (Studio):  $STUDIO_MODEL @ $STUDIO_URL  → AP Math" | tee -a "$LOG"
echo "Stream B (Mini 2):  $MINI2_MODEL @ $MINI2_URL    → AP Science + IB" | tee -a "$LOG"
echo "Stream C (IWPC):    $($IWPC_ONLINE && echo "$IWPC_MODEL @ $IWPC_URL → US state sample" || echo 'offline — Studio handles states')" | tee -a "$LOG"
echo "Mini 2 log: $LOG_M2" | tee -a "$LOG"

# Warm up all three hosts in parallel (failures are non-fatal — model still loads on first request)
echo "" | tee -a "$LOG"
warmup "$STUDIO_URL" "$STUDIO_MODEL" "$LOG" & W1=$!
warmup "$MINI2_URL"  "$MINI2_MODEL"  "$LOG_M2" & W2=$!
if $IWPC_ONLINE; then warmup "$IWPC_URL" "$IWPC_MODEL" "$LOG" & W3=$!; else W3=""; fi
wait $W1 || echo "[WARN] Studio warmup failed — will retry on first inference call" | tee -a "$LOG"
wait $W2 || echo "[WARN] Mini 2 warmup failed — will retry on first inference call" | tee -a "$LOG_M2"
[ -n "$W3" ] && { wait $W3 || echo "[WARN] IWPC warmup failed" | tee -a "$LOG"; }
echo "" | tee -a "$LOG"

# ── Streams A + B: high band (parallel) ──────────────────────────────────────
# A: AP Math high — Studio
# B: AP Science + IB high — Mini 2 (background)

echo "[$(date)] Starting high-band phase: A=AP Math (Studio) || B=AP Science+IB (Mini 2)" | tee -a "$LOG"

(
    run_mini2 "AP Bio → NGSS      [high]"  --system ap-bio     --band high --sample 0
    run_mini2 "AP Chem → NGSS     [high]"  --system ap-chem    --band high --sample 0
    run_mini2 "AP Phys 1 → NGSS   [high]"  --system ap-phys-1  --band high --sample 0
    run_mini2 "AP Phys 2 → NGSS   [high]"  --system ap-phys-2  --band high --sample 0
    run_mini2 "AP Env → NGSS      [high]"  --system ap-env     --band high --sample 0
    run_mini2 "IB-DP → CCSS       [high]"  --system ib-dp      --band high --sample 0
    run_mini2 "IB-MYP → CCSS      [high]"  --system ib-myp     --band high --sample 0
) &
MINI2_HIGH_PID=$!

run "AP Calc AB → CCSS  [high]"  --system ap-calc-ab  --band high --sample 0
run "AP Calc BC → CCSS  [high]"  --system ap-calc-bc  --band high --sample 0
run "AP Stats → CCSS    [high]"  --system ap-stats    --band high --sample 0
run "AP Precalc → CCSS  [high]"  --system ap-precalc  --band high --sample 0

wait $MINI2_HIGH_PID || echo "[WARN] Mini 2 high-band stream had errors — check $LOG_M2" | tee -a "$LOG"
echo "[$(date)] High-band phase complete" | tee -a "$LOG"

# ── Streams A + B: mid band (parallel) ───────────────────────────────────────

echo "[$(date)] Starting mid-band phase: A=AP Math (Studio) || B=AP Science+IB (Mini 2)" | tee -a "$LOG"

(
    run_mini2 "AP Bio → NGSS      [mid]"   --system ap-bio     --band mid  --sample 0
    run_mini2 "AP Chem → NGSS     [mid]"   --system ap-chem    --band mid  --sample 0
    run_mini2 "AP Phys 1 → NGSS   [mid]"   --system ap-phys-1  --band mid  --sample 0
    run_mini2 "AP Phys 2 → NGSS   [mid]"   --system ap-phys-2  --band mid  --sample 0
    run_mini2 "AP Env → NGSS      [mid]"   --system ap-env     --band mid  --sample 0
    run_mini2 "IB-DP → CCSS       [mid]"   --system ib-dp      --band mid  --sample 0
    run_mini2 "IB-MYP → CCSS      [mid]"   --system ib-myp     --band mid  --sample 0
) &
MINI2_MID_PID=$!

run "AP Calc AB → CCSS  [mid]"   --system ap-calc-ab  --band mid  --sample 0
run "AP Calc BC → CCSS  [mid]"   --system ap-calc-bc  --band mid  --sample 0
run "AP Stats → CCSS    [mid]"   --system ap-stats    --band mid  --sample 0
run "AP Precalc → CCSS  [mid]"   --system ap-precalc  --band mid  --sample 0

wait $MINI2_MID_PID || echo "[WARN] Mini 2 mid-band stream had errors — check $LOG_M2" | tee -a "$LOG"
echo "[$(date)] Mid-band phase complete" | tee -a "$LOG"

# ── Stream A + C: US state sample ─────────────────────────────────────────────
# Studio and IWPC split states in parallel if IWPC is online.

echo "[$(date)] Starting state sample phase" | tee -a "$LOG"

if $IWPC_ONLINE; then
    STUDIO_STATES=(ca ny wa ma pa il)
    IWPC_STATES=(tx fl ga nc oh co)

    for state in "${STUDIO_STATES[@]}"; do
        run "State $state → CCSS [n=200]" --system "$state" --sample 200 &
        STUDIO_BG=$!
        if [ ${#IWPC_STATES[@]} -gt 0 ]; then
            iwpc_state="${IWPC_STATES[0]}"
            IWPC_STATES=("${IWPC_STATES[@]:1}")
            run_iwpc "State $iwpc_state → CCSS [n=200]" --system "$iwpc_state" --sample 200
        fi
        wait $STUDIO_BG
    done
    for state in "${IWPC_STATES[@]}"; do
        run_iwpc "State $state → CCSS [n=200]" --system "$state" --sample 200
    done
else
    for state in ca tx ny fl ga wa ma nc pa oh il co; do
        run "State $state → CCSS [n=200]" --system "$state" --sample 200
    done
fi

echo "[$(date)] State sample phase complete" | tee -a "$LOG"

# ── Phase: review pass (Studio) ───────────────────────────────────────────────

run "Review: AP math mid [flag bad]" --system ap-calc-ab --band mid --review-only --sample 0
run "Review: AP sci mid  [flag bad]" --system ap-bio     --band mid --review-only --sample 0

# ── Summary ───────────────────────────────────────────────────────────────────

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

echo "Studio log:  $LOG" | tee -a "$LOG"
echo "Mini 2 log:  $LOG_M2" | tee -a "$LOG"
