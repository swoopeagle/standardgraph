#!/usr/bin/env bash
# Post-ingest chain: git pull → embed → relate → crosswalk → rationale gen.
#
# Usage (from the Mac Studio):
#   nohup bash scripts/post_ingest_pipeline.sh > logs/post_ingest.log 2>&1 &
#
# This used to run from mini2 and fan embed/relate/crosswalk out to mini3 in
# parallel, each mini working its own copy of the DB and the halves merged
# afterwards with scripts/merge_dbs.py. mini3 was sold 2026-08-12 and mini2 is
# pending sale, so the chain is now sequential on the Studio against the one
# DB -- which also means there is no longer a merge step to forget.
#
# It also no longer waits on a fetcher on mini3, and the repo path is derived
# from this script's own location instead of being hardcoded to mini2's
# ~/projects/intl-math-standards-mcp.

set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DB_PATH="${DB_PATH:-$REPO/data/common_core.db}"
IWPC_URL="http://100.70.170.62:11434"
LOG="$REPO/logs/post_ingest_$(date +%Y%m%d_%H%M%S).log"

export DB_PATH
mkdir -p "$REPO/logs"

# Defined before first use: the old version called log() six lines above this
# point, which under `set -e` killed the script with "log: command not found".
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
section() {
    echo "" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
    echo "  $*" | tee -a "$LOG"
    echo "  $(date)" | tee -a "$LOG"
    echo "══════════════════════════════════════════════════════════" | tee -a "$LOG"
}

# Embeddings prefer IWPC's CUDA node (2-3x faster), else the local Ollama.
if curl -sf --max-time 3 "$IWPC_URL/api/tags" >/dev/null 2>&1; then
    EMBED_URL="$IWPC_URL"
    EMBED_WHERE="IWPC (CUDA)"
else
    EMBED_URL="http://localhost:11434"
    EMBED_WHERE="local Ollama (IWPC offline)"
fi

log "Post-ingest pipeline started"
log "Repo: $REPO"
log "DB:   $DB_PATH"

section "Step 1: git pull"
cd "$REPO"
git pull --ff-only 2>&1 | tee -a "$LOG"

section "Step 2: embed via $EMBED_WHERE"
OLLAMA_BASE_URL="$EMBED_URL" uv run python -m ingestion.shared.embed 2>&1 | tee -a "$LOG"

section "Step 3: relate"
uv run python -m ingestion.shared.relate 2>&1 | tee -a "$LOG"

section "Step 4: crosswalk nlp_pass"
uv run python -m crosswalk_engine.nlp_pass 2>&1 | tee -a "$LOG"

section "Step 5: rationale gen (background)"
RATIONALE_LOG="$REPO/logs/rationale_$(date +%Y%m%d_%H%M%S).log"
nohup env DB_PATH="$DB_PATH" bash "$REPO/scripts/overnight_rationale.sh" \
    > "$RATIONALE_LOG" 2>&1 &
log "Rationale gen started → PID $! → $RATIONALE_LOG"

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
