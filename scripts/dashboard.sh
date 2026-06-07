#!/usr/bin/env bash
# Unified dashboard: hardware health + overnight pipeline progress
# Usage: bash scripts/dashboard.sh           (single snapshot)
#        bash scripts/dashboard.sh --watch   (refresh every 30s)
#        bash scripts/dashboard.sh --bench   (add tokens/sec benchmark — slow if Gemma is busy)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
OLLAMA_URL="http://169.254.1.1:11434"
BENCH=0
WATCH=0
for arg in "$@"; do
    case "$arg" in --watch) WATCH=1 ;; --bench) BENCH=1 ;; esac
done

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

latest_log() {
    ls -t "$LOG_DIR"/overnight_*.log 2>/dev/null | head -1
}

section() { echo "  ── $1 $(printf '%.0s─' {1..40})" | cut -c1-58; }

print_hardware() {
    section "Hardware"
    echo

    # Ollama liveness
    if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        printf "  %-16s %s\n" "Ollama" "▲ UP"

        # Loaded model
        local ps; ps="$(curl -sf "$OLLAMA_URL/api/ps" 2>/dev/null || echo '{}')"
        local model_line; model_line="$(python3 - <<'PY' "$ps"
import sys, json
d = json.loads(sys.argv[1])
models = d.get("models", [])
if models:
    m = models[0]
    vram_gb = m.get("size_vram", 0) / 1_073_741_824
    exp = m.get("expires_at", "")[:19].replace("T", " ")
    print(f"{m['name']}  {vram_gb:.1f} GB VRAM  keep-alive until {exp}")
else:
    print("none — idle")
PY
)"
        printf "  %-16s %s\n" "Model loaded" "$model_line"

        # Optional benchmark
        if [ "$BENCH" = "1" ]; then
            printf "  %-16s " "Throughput"
            local bench; bench="$(curl -sf "$OLLAMA_URL/api/generate" \
                -d '{"model":"gemma4:31b-it-q8_0","prompt":"What is 2+2?","stream":false,"options":{"num_predict":20}}' \
                2>/dev/null || echo '{}')"
            python3 - <<PY "$bench"
import sys, json
d = json.loads(sys.argv[1])
tps  = d.get("eval_count", 0) / max(d.get("eval_duration", 1), 1) * 1e9
ttft = d.get("prompt_eval_duration", 0) / 1e9
print(f"{tps:.1f} tok/s   TTFT {ttft:.2f}s")
PY
        fi
    else
        printf "  %-16s %s\n" "Ollama" "▼ DOWN"
    fi

    echo

    # Unified memory (vm_stat reports CPU-visible pages; GPU pool claimed by Metal is separate)
    local mem; mem="$(vm_stat | awk '
        /Pages free/        { free=$3+0 }
        /Pages active/      { active=$3+0 }
        /Pages wired/       { wired=$4+0 }
        /Pages compressed/  { comp=$3+0 }
        END {
            p = 16384
            printf "Free %.1f GB   Active %.1f GB   Wired %.1f GB   Compressed %.1f GB",
                free*p/1073741824, active*p/1073741824,
                wired*p/1073741824, comp*p/1073741824
        }')"
    printf "  %-16s %s\n" "Unified memory" "$mem"

    # Memory pressure
    local pressure; pressure="$(memory_pressure 2>/dev/null \
        | grep -oE 'System-wide memory free percentage: [0-9]+%' \
        | head -1 || echo "")"
    [ -n "$pressure" ] && printf "  %-16s %s\n" "Pressure" "$pressure"

    # Pipeline process alive?
    local py_procs; py_procs="$(pgrep -c python 2>/dev/null || echo 0)"
    printf "  %-16s %s Python process(es) running\n" "Processes" "$py_procs"

    echo
}

print_pipeline() {
    section "Pipeline"
    echo

    local log; log="$(latest_log)"
    if [ -z "$log" ]; then
        echo "  No overnight log found in $LOG_DIR"
        echo
        return
    fi

    # Elapsed time
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

    printf "  Log: %s   %s\n" "$(basename "$log")" "$elapsed"
    echo

    local current_detail=""

    for step in "${STEPS[@]}"; do
        if grep -q "── $step" "$log" 2>/dev/null; then
            if grep -A200 "── $step" "$log" | grep -qE '  finished:|  retry succeeded:'; then
                printf "  ✓  %s\n" "$step"
            elif grep -A200 "── $step" "$log" | grep -q '  FAILED after retry'; then
                printf "  ✗  %s\n" "$step"
            else
                printf "  ⟳  %s  ← running\n" "$step"
                current_detail="$(grep -A200 "── $step" "$log" \
                    | tail -3 | grep -v '^\s*$' | tail -1 | sed 's/^  *//' || true)"
            fi
        else
            printf "  ○  %s\n" "$step"
        fi
    done

    echo
    [ -n "$current_detail" ] && printf "  Last output:  %s\n" "$current_detail" && echo

    # DB stats
    local db="$REPO_DIR/data/common_core.db"
    if [ -f "$db" ]; then
        local stats; stats="$(sqlite3 "$db" \
            "SELECT COUNT(*)||' standards, '||COUNT(DISTINCT system)||' systems' FROM standards;" \
            2>/dev/null || echo "DB locked")"
        printf "  DB now:  %s\n" "$stats"
    fi

    echo
}

print_dashboard() {
    clear 2>/dev/null || true
    printf "════════════════════════════════════════════════════════\n"
    printf "  StandardGraph — %s\n" "$(date)"
    printf "════════════════════════════════════════════════════════\n"
    echo
    print_hardware
    print_pipeline
    echo "  (ctrl-C to exit  ·  --bench to add throughput test  ·  --watch to auto-refresh)"
}

if [ "$WATCH" = "1" ]; then
    while true; do print_dashboard; sleep 30; done
else
    print_dashboard
fi
