#!/usr/bin/env bash
# Overnight pipeline: ingest pending sources → embed → relate → crosswalk
# Run from the repo root: bash scripts/overnight_run.sh
# Output is tee'd to logs/overnight_YYYYMMDD_HHMMSS.log

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"

# Prevent overlapping runs
LOCK_FILE="$REPO_DIR/.pipeline.lock"
if [ -f "$LOCK_FILE" ]; then
    existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || echo "")"
    if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
        echo "Pipeline already running (PID $existing_pid). Exiting."
        exit 0
    fi
    echo "Stale lock file found — removing."
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

LOG_FILE="$LOG_DIR/overnight_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

# Wait for Ollama to be reachable (up to 5 minutes)
echo "Checking Ollama availability..."
OLLAMA_URL="http://169.254.1.1:11434"
for i in $(seq 1 30); do
    if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        echo "Ollama is up."
        break
    fi
    echo "  Waiting for Ollama... attempt $i/30"
    sleep 10
done
if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "ERROR: Ollama not reachable at $OLLAMA_URL after 5 minutes. Aborting."
    exit 1
fi

echo "======================================================"
echo "  StandardGraph overnight pipeline — $(date)"
echo "======================================================"
echo "Log: $LOG_FILE"
echo

cd "$REPO_DIR"

STEP_PASS=()
STEP_FAIL=()
DB="$REPO_DIR/data/common_core.db"

run_step() {
    local label="$1"; shift
    echo
    echo "── $label ──────────────────────────────────────────"
    echo "  started: $(date)"
    local exit_code=0
    "$@" || exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo "  finished: $(date)"
        STEP_PASS+=("$label")
    else
        echo "  FAILED (exit $exit_code): $(date) — retrying once..."
        sleep 5
        "$@" || exit_code=$?
        if [ $exit_code -eq 0 ]; then
            echo "  retry succeeded: $(date)"
            STEP_PASS+=("$label [retry]")
        else
            echo "  FAILED after retry (exit $exit_code): $(date)"
            STEP_FAIL+=("$label")
        fi
    fi
}

# Skip Gemma-heavy PDF fetchers if already ingested within the last 6 days.
# Fast API-based fetchers (states, CSP) and the embed/relate/crosswalk steps always run.
is_fresh() {
    local system="$1"
    local cutoff; cutoff=$(date -v-6d +%Y-%m-%d 2>/dev/null || date -d '6 days ago' +%Y-%m-%d 2>/dev/null)
    local last; last=$(sqlite3 "$DB" \
        "SELECT MAX(last_verified_date) FROM standards WHERE system='$system';" 2>/dev/null || echo "")
    [[ -n "$last" && "$last" > "$cutoff" ]]
}

run_step_unless_fresh() {
    local label="$1"
    local system="$2"
    shift 2
    if is_fresh "$system"; then
        echo
        echo "── $label (skipped — ingested within 6 days) ──────"
        STEP_PASS+=("$label [skipped, fresh]")
    else
        run_step "$label" "$@"
    fi
}

# ── Ingestion steps ──────────────────────────────────────────────────────────
# PDF-heavy steps use run_step_unless_fresh (skip if ingested within 6 days).
# API-based steps always run (fast and idempotent).

run_step_unless_fresh "Singapore MOE ingestion"      "sg-moe"   \
    uv run python -m ingestion.international.fetch_singapore

run_step_unless_fresh "Japan MEXT ingestion"         "jp-mext"  \
    uv run python -m ingestion.international.fetch_japan

run_step_unless_fresh "New Zealand curriculum"       "nz-moe"   \
    uv run python -m ingestion.international.fetch_nz

run_step             "AERO + DoDEA ingestion" \
    uv run python -m ingestion.international.fetch_csp_extra

run_step_unless_fresh "Scotland CfE ingestion"       "gb-sco"   \
    uv run python -m ingestion.international.fetch_scotland

run_step_unless_fresh "Ireland NCCA ingestion"       "ie-ncca"  \
    uv run python -m ingestion.international.fetch_ireland

run_step_unless_fresh "Hong Kong EDB ingestion"      "hk-edb"   \
    uv run python -m ingestion.international.fetch_hk

run_step_unless_fresh "India NCERT ingestion"        "in-ncert" \
    uv run python -m ingestion.international.fetch_india

run_step_unless_fresh "Ghana NaCCA ingestion"        "gh-nacca" \
    uv run python -m ingestion.international.fetch_ghana

run_step_unless_fresh "South Africa CAPS ingestion"  "za-caps"  \
    uv run python -m ingestion.international.fetch_southafrica

run_step_unless_fresh "Quebec MEES ingestion"        "ca-qc"    \
    uv run python -m ingestion.international.fetch_quebec

run_step_unless_fresh "Rwanda REB ingestion"         "rw-reb"   \
    uv run python -m ingestion.international.fetch_rwanda

run_step_unless_fresh "Philippines DepEd ingestion"  "ph-deped" \
    uv run python -m ingestion.international.fetch_philippines

# ── 2. Embeddings ─────────────────────────────────────────────────────────────
# Only embeds standards that don't already have an embedding (LEFT JOIN check).
run_step "Embeddings (nomic-embed-text)" \
    uv run python -m ingestion.shared.embed

# ── 3. Prerequisite / successor relationships ─────────────────────────────────
run_step "Grade progression relationships" \
    uv run python -m ingestion.shared.relate

# ── 4. NLP crosswalk → CCSS ───────────────────────────────────────────────────
# Maps all standards to closest CCSS via cosine similarity.
run_step "NLP crosswalk (all systems → CCSS)" \
    uv run python -m crosswalk_engine.nlp_pass

echo
echo "======================================================"
echo "  All steps complete — $(date)"
echo "======================================================"
echo

if [ ${#STEP_PASS[@]} -gt 0 ]; then
    echo "  PASSED (${#STEP_PASS[@]}):"
    for s in "${STEP_PASS[@]}"; do echo "    ✓ $s"; done
fi
if [ ${#STEP_FAIL[@]} -gt 0 ]; then
    echo "  FAILED (${#STEP_FAIL[@]}):"
    for s in "${STEP_FAIL[@]}"; do echo "    ✗ $s"; done
fi
echo

echo "DB size: $(du -sh "$REPO_DIR/data/common_core.db" 2>/dev/null | cut -f1)"
sqlite3 "$REPO_DIR/data/common_core.db" \
    "SELECT 'Standards: ' || COUNT(*) FROM standards; \
     SELECT 'Embeddings: ' || COUNT(*) FROM embeddings; \
     SELECT 'Relationships: ' || COUNT(*) FROM standard_relationships; \
     SELECT 'Crosswalk mappings: ' || COUNT(*) FROM crosswalk_mappings;"
echo
echo "Systems in DB:"
sqlite3 "$REPO_DIR/data/common_core.db" \
    "SELECT '  ' || system || ': ' || COUNT(*) || ' standards' FROM standards GROUP BY system ORDER BY system;"
echo
echo "Log saved to: $LOG_FILE"

# ── 5. Smoke test ─────────────────────────────────────────────────────────────
echo
echo "── Smoke test ──────────────────────────────────────────────────────────"
uv run python "$REPO_DIR/scripts/smoke_test.py" || true

# ── 6. Reload MCP server ──────────────────────────────────────────────────────
# Restart Claude Desktop so the MCP server picks up new system counts/names.
echo
echo "── Reloading Claude Desktop (MCP server refresh) ───────────────────────"
if osascript -e 'tell application "Claude" to quit' 2>/dev/null; then
    sleep 8
    open -a "Claude" && echo "  Claude restarted." || echo "  Could not reopen Claude."
else
    echo "  Claude not running — no restart needed."
fi
