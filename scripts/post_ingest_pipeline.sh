#!/usr/bin/env bash
# Runs automatically after a fetcher completes on Mini 3.
# Chain: wait → git pull (both) → embed → relate → crosswalk → rationale gen
#
# Usage (from Mini 2):
#   nohup bash scripts/post_ingest_pipeline.sh > logs/post_ingest_YYYYMMDD.log 2>&1 &

set -euo pipefail

REPO="$HOME/projects/intl-math-standards-mcp"
DB_PATH="${DB_PATH:-$REPO/data/common_core.db}"
MINI3="devos@100.123.114.101"
STUDIO_URL="http://100.77.63.73:11434"
IWPC_URL="http://100.70.170.62:11434"
LOG="$REPO/logs/post_ingest_$(date +%Y%m%d_%H%M%S).log"

export DB_PATH

# Auto-detect IWPC — use it for embed if reachable, else fall back to localhost
if curl -sf --max-time 3 "$IWPC_URL/api/tags" >/dev/null 2>&1; then
    EMBED_URL="$IWPC_URL"
    log "IWPC reachable — routing embed to IWPC (CUDA)"
else
    EMBED_URL="http://localhost:11434"
    log "IWPC offline — embed will use local Ollama on each mini"
fi

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
section() {
    echo "" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    echo "  $*" | tee -a "$LOG"
    echo "  $(date)" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
}

log "Post-ingest pipeline started"
log "DB: $DB_PATH"
log "Watching Mini 3 for Portugal fetcher to complete…"

# ── Step 0: Wait for Portugal to finish on Mini 3 ────────────────────────────
while ssh -o ConnectTimeout=5 "$MINI3" "pgrep -f fetch_portugal > /dev/null 2>&1"; do
    log "Portugal still running on Mini 3 — sleeping 60s"
    sleep 60
done
log "Portugal done on Mini 3."

# ── Step 1: git pull on both minis ───────────────────────────────────────────
section "Step 1: git pull"

cd "$REPO"
git pull --ff-only 2>&1 | tee -a "$LOG"
log "Mini 2 pulled."

ssh -o ConnectTimeout=10 "$MINI3" "
  cd ~/projects/intl-math-standards-mcp
  git pull --ff-only 2>&1
" | tee -a "$LOG"
log "Mini 3 pulled."

# ── Step 2: embed on both minis in parallel ───────────────────────────────────
section "Step 2: embed (Mini 2 + Mini 3 in parallel, embed via $EMBED_URL)"

export PATH="/Users/devos/.local/bin:$PATH"

# Mini 3 embed in background
ssh -o ConnectTimeout=10 "$MINI3" "
  export PATH='/Users/devos/.local/bin:\$PATH'
  cd ~/projects/intl-math-standards-mcp
  OLLAMA_BASE_URL=$EMBED_URL uv run python -m ingestion.shared.embed 2>&1
" | sed 's/^/[mini3-embed] /' | tee -a "$LOG" &
MINI3_EMBED_PID=$!

# Mini 2 embed locally, also pointing at EMBED_URL
OLLAMA_BASE_URL="$EMBED_URL" uv run python -m ingestion.shared.embed 2>&1 \
    | sed 's/^/[mini2-embed] /' | tee -a "$LOG"

wait $MINI3_EMBED_PID
log "Both embeds complete."

# ── Step 3: relate on both minis in parallel ──────────────────────────────────
section "Step 3: relate (Mini 2 + Mini 3 in parallel)"

ssh -o ConnectTimeout=10 "$MINI3" "
  export PATH='/Users/devos/.local/bin:\$PATH'
  cd ~/projects/intl-math-standards-mcp
  uv run python -m ingestion.shared.relate 2>&1
" | sed 's/^/[mini3-relate] /' | tee -a "$LOG" &
MINI3_RELATE_PID=$!

uv run python -m ingestion.shared.relate 2>&1 | sed 's/^/[mini2-relate] /' | tee -a "$LOG"

wait $MINI3_RELATE_PID
log "Both relate passes complete."

# ── Step 4: crosswalk on both minis in parallel ───────────────────────────────
section "Step 4: crosswalk nlp_pass (Mini 2 + Mini 3 in parallel)"

ssh -o ConnectTimeout=10 "$MINI3" "
  export PATH='/Users/devos/.local/bin:\$PATH'
  cd ~/projects/intl-math-standards-mcp
  uv run python -m crosswalk_engine.nlp_pass 2>&1
" | sed 's/^/[mini3-xwalk] /' | tee -a "$LOG" &
MINI3_XWALK_PID=$!

uv run python -m crosswalk_engine.nlp_pass 2>&1 | sed 's/^/[mini2-xwalk] /' | tee -a "$LOG"

wait $MINI3_XWALK_PID
log "Both crosswalk passes complete."

# ── Step 5: start rationale gen overnight ────────────────────────────────────
section "Step 5: rationale gen (Mini 2 → Mac Studio qwen2.5:72b)"

RATIONALE_LOG="$REPO/logs/rationale_$(date +%Y%m%d_%H%M%S).log"
nohup bash -c "
  export PATH='/Users/devos/.local/bin:\$PATH'
  OLLAMA_BASE_URL=$STUDIO_URL \
  DB_PATH=$DB_PATH \
  bash $REPO/scripts/overnight_rationale.sh
" > "$RATIONALE_LOG" 2>&1 &
RATIONALE_PID=$!
log "Rationale gen started → PID $RATIONALE_PID → $RATIONALE_LOG"

# ── Done ─────────────────────────────────────────────────────────────────────
section "Pipeline handed off"
log "Steps 1-4 complete. Rationale gen running in background."
log "Monitor: tail -f $RATIONALE_LOG"
log "Stats:"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;" \
    2>/dev/null | tee -a "$LOG"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' crosswalk mappings' FROM crosswalk_mappings;" \
    2>/dev/null | tee -a "$LOG"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' with rationale notes' FROM crosswalk_mappings WHERE notes IS NOT NULL;" \
    2>/dev/null | tee -a "$LOG"
