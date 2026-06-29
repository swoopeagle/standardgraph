#!/usr/bin/env bash
# Run PDF-heavy fetchers using Mac Studio (qwen2.5:72b) directly.
# Runs in parallel with Mini 2's ongoing rationale work.

set -uo pipefail

REPO="$HOME/projects/intl-math-standards-mcp"
export DB_PATH="$REPO/data/common_core.db"
export OLLAMA_BASE_URL="http://169.254.1.1:11434"
export OLLAMA_MODEL="qwen2.5:72b"
export PATH="/Users/devos/.local/bin:$PATH"

LOG="$REPO/logs/studio_fetch_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$REPO/logs"
exec > >(tee -a "$LOG") 2>&1

cd "$REPO"

banner() {
    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  $1"
    echo "  $(date)"
    echo "  Model: $OLLAMA_MODEL @ $OLLAMA_BASE_URL"
    echo "══════════════════════════════════════════════════════════"
}

run_fetcher() {
    local label="$1" module="$2"
    banner "$label"
    uv run python -m "$module" || echo "[WARN] $label exited non-zero — continuing"
}

banner "Studio fetch pipeline started"

# ── IB DP extended subjects ───────────────────────────────────────────────────
# These are 2-page subject briefs — fast to download, Ollama structures content
run_fetcher "IB DP subjects (Bio/Chem/Physics/CS/etc)"  ingestion.international.fetch_ib_dp

# ── Italy re-fetch (was timing out before; Studio now idle) ───────────────────
run_fetcher "Italy MIUR (it-miur)"                      ingestion.international.fetch_italy

# ── France re-fetch (got 0 standards yesterday due to Studio timeout) ─────────
run_fetcher "France MEN (fr-men)"                       ingestion.international.fetch_france

# ── IB PYP (Young learner, PK-5 equivalent) ───────────────────────────────────
run_fetcher "IB PYP"                                    ingestion.international.fetch_ib_pyp

# ── IB MYP ────────────────────────────────────────────────────────────────────
run_fetcher "IB MYP"                                    ingestion.international.fetch_ib_myp

banner "Fetchers done — running post-ingest chain"

sqlite3 "$DB_PATH" \
    "SELECT system, COUNT(*) FROM standards WHERE system LIKE 'ib%' OR system IN ('it-miur','fr-men')
     GROUP BY system ORDER BY system;" 2>/dev/null || true

# ── Embed new standards ───────────────────────────────────────────────────────
banner "Embed (nomic-embed-text via localhost)"
OLLAMA_BASE_URL="http://localhost:11434" OLLAMA_MODEL="nomic-embed-text" \
    uv run python -m ingestion.shared.embed

# ── Relate ───────────────────────────────────────────────────────────────────
banner "Relate"
uv run python -m ingestion.shared.relate

# ── Crosswalk ─────────────────────────────────────────────────────────────────
banner "Crosswalk NLP pass"
uv run python -m crosswalk_engine.nlp_pass

# ── Rationale for new IB/Italy/France mappings ────────────────────────────────
# Only new mappings lacking rationale (no --force-rewrite)
banner "Rationale gen for new mappings (Studio qwen2.5:72b)"
export OLLAMA_BASE_URL="http://169.254.1.1:11434"
export OLLAMA_MODEL="qwen2.5:72b"

for system in ib-dp-bio ib-dp-chem ib-dp-physics ib-dp-cs ib-dp-english-a \
              ib-dp-history ib-dp-geography ib-dp-economics ib-dp-psych \
              ib-myp ib-pyp it-miur fr-men; do
    echo "" && echo "  → rationale: $system"
    OLLAMA_BASE_URL="http://169.254.1.1:11434" OLLAMA_MODEL="qwen2.5:72b" \
        uv run python scripts/crosswalk_rationale_gen.py \
            --system "$system" --sample 0 2>&1 || \
        echo "[WARN] rationale for $system skipped or errored"
done

banner "ALL DONE"
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' total standards, ' || COUNT(DISTINCT system) || ' systems' FROM standards;" \
    2>/dev/null
sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) || ' crosswalk mappings, ' || 
     SUM(CASE WHEN notes IS NOT NULL AND notes!='' THEN 1 ELSE 0 END) || ' with rationale'
     FROM crosswalk_mappings;" 2>/dev/null
