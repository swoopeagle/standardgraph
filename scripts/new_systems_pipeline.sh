#!/usr/bin/env bash
# Ingest new international math systems not yet in the DB, then run full post-ingest chain.
# Systems: fr-men, ar-men, kr-ncf, mx-sep, mx-sep-bachillerato, es-mecd, es-eso, jp-mext-secondary

set -uo pipefail

REPO="$HOME/projects/intl-math-standards-mcp"
export DB_PATH="$REPO/data/common_core.db"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://169.254.1.1:11434}"
export PATH="/Users/devos/.local/bin:$PATH"

LOG="$REPO/logs/new_systems_$(date +%Y%m%d_%H%M%S).log"
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

run_fetcher() {
    local label="$1" module="$2"
    banner "$label"
    uv run python -m "$module" || echo "[WARN] $label exited with error — continuing"
}

banner "New systems pipeline started"
echo "DB: $DB_PATH"
echo "Studio: $OLLAMA_BASE_URL"

# ── Phase 1: Fetch new systems ────────────────────────────────────────────────

run_fetcher "France MEN (fr-men)"                   ingestion.international.fetch_france
run_fetcher "Argentina MEN (ar-men)"                ingestion.international.fetch_argentina
run_fetcher "Korea NCIC (kr-ncf)"                   ingestion.international.fetch_korea
run_fetcher "Mexico SEP (mx-sep)"                   ingestion.international.fetch_mexico
run_fetcher "Mexico Bachillerato (mx-sep-bach)"     ingestion.international.fetch_mexico_bachillerato
run_fetcher "Spain MECD (es-mecd)"                  ingestion.international.fetch_spain
run_fetcher "Spain ESO (es-eso)"                    ingestion.international.fetch_spain_eso
run_fetcher "Japan secondary (jp-mext-secondary)"   ingestion.international.fetch_japan_secondary

banner "All fetchers done — starting post-ingest chain"

sqlite3 "$DB_PATH" \
    "SELECT system, COUNT(*) FROM standards GROUP BY system ORDER BY COUNT(*) DESC LIMIT 10;" \
    2>/dev/null || true

# ── Phase 2: Embed new standards ──────────────────────────────────────────────

banner "Embed (nomic-embed-text)"
OLLAMA_BASE_URL="http://localhost:11434" uv run python -m ingestion.shared.embed

# ── Phase 3: Relate ───────────────────────────────────────────────────────────

banner "Relate (grade progression)"
uv run python -m ingestion.shared.relate

# ── Phase 4: Crosswalk ────────────────────────────────────────────────────────

banner "Crosswalk NLP pass"
uv run python -m crosswalk_engine.nlp_pass

# ── Phase 5: Rationale for new mappings ───────────────────────────────────────

banner "Rationale gen for new systems"
bash "$REPO/scripts/overnight_rationale.sh"

banner "ALL DONE"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;" \
    2>/dev/null
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' crosswalk mappings' FROM crosswalk_mappings;" \
    2>/dev/null
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' with rationale' FROM crosswalk_mappings WHERE notes IS NOT NULL AND notes != '';" \
    2>/dev/null
