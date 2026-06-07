#!/usr/bin/env bash
# Show a live progress dashboard for the most recent overnight run.
# Usage: bash scripts/progress.sh          (single snapshot)
#        bash scripts/progress.sh --watch  (refresh every 30s)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"

latest_log() {
    ls -t "$LOG_DIR"/overnight_*.log 2>/dev/null | head -1
}

STEPS=(
    "Singapore MOE ingestion"
    "Japan MEXT ingestion"
    "New Zealand curriculum"
    "AERO + DoDEA ingestion"
    "Scotland CfE ingestion"
    "Ireland NCCA ingestion"
    "Hong Kong EDB ingestion"
    "India NCERT ingestion"
    "Ghana NaCCA ingestion"
    "South Africa CAPS ingestion"
    "Quebec MEES ingestion"
    "Rwanda REB ingestion"
    "Philippines DepEd ingestion"
    "Embeddings (nomic-embed-text)"
    "Grade progression relationships"
    "NLP crosswalk (all systems → CCSS)"
    "Smoke test"
    "Reloading Claude Desktop (MCP server refresh)"
)

print_dashboard() {
    local log; log="$(latest_log)"
    if [ -z "$log" ]; then
        echo "No overnight log found in $LOG_DIR"
        return
    fi

    local started; started="$(grep -m1 'overnight pipeline' "$log" | grep -oE '[A-Z][a-z]+ [A-Z][a-z]+ +[0-9]+ [0-9:]+' || echo '?')"
    clear 2>/dev/null || true
    echo "════════════════════════════════════════════════════"
    echo "  StandardGraph overnight run — started $started"
    echo "  Log: $(basename "$log")"
    echo "════════════════════════════════════════════════════"
    echo

    local now; now="$(date +%s)"
    local run_start_str; run_start_str="$(grep -m1 'started:' "$log" | sed 's/.*started: //' || true)"
    local elapsed=""
    if [ -n "$run_start_str" ]; then
        local run_start; run_start="$(date -j -f '%a %b %d %T %Z %Y' "$run_start_str" +%s 2>/dev/null || echo "")"
        if [ -n "$run_start" ]; then
            local secs=$(( now - run_start ))
            elapsed="$(printf '%dh %02dm elapsed' $((secs/3600)) $(( (secs%3600)/60 )))"
        fi
    fi

    local current_step=""
    local current_detail=""

    for step in "${STEPS[@]}"; do
        local status=""
        if grep -q "── $step ──" "$log" 2>/dev/null; then
            if grep -A200 "── $step ──" "$log" | grep -qE '  finished:|  retry succeeded:'; then
                status="done"
            elif grep -A200 "── $step ──" "$log" | grep -q '  FAILED after retry'; then
                status="failed"
            else
                status="running"
                current_step="$step"
                # Grab last non-empty content line as detail
                current_detail="$(grep -A200 "── $step ──" "$log" | tail -3 | grep -v '^\s*$' | tail -1 | sed 's/^  *//' || true)"
            fi
        else
            status="pending"
        fi

        case "$status" in
            done)    echo "  ✓  $step" ;;
            failed)  echo "  ✗  $step" ;;
            running) echo "  ⟳  $step  ← running" ;;
            pending) echo "  ○  $step" ;;
        esac
    done

    echo

    if [ -n "$current_step" ] && [ -n "$current_detail" ]; then
        echo "  Last output:  $current_detail"
        echo
    fi

    # DB stats
    local db="$REPO_DIR/data/common_core.db"
    if [ -f "$db" ]; then
        local stats; stats="$(sqlite3 "$db" \
            "SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;" 2>/dev/null || echo "DB locked")"
        echo "  DB now:  $stats"
    fi

    [ -n "$elapsed" ] && echo "  Runtime: $elapsed"
    echo
    echo "  (ctrl-C to exit)"
}

if [ "${1:-}" = "--watch" ]; then
    while true; do
        print_dashboard
        sleep 30
    done
else
    print_dashboard
fi
