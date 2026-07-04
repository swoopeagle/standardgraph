"""Deterministically score exact-match crosswalks — no LLM required.

When a crosswalk's source and target standard text are byte-identical, the mapping
is a definitional 5/5 equivalence (a jurisdiction adopting a hub standard verbatim).
This scores those rows without any model call, raising honest quality-score coverage.

Only rows still carrying an unscored `nlp_pass ...` note are touched; existing
`[LLM score N/5]` and `[exact-match N/5]` rows are left as-is (idempotent). Rows are
NOT flagged (an exact match is high quality by definition).

Usage:
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/score_exact_matches.py --dry-run
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/score_exact_matches.py --apply
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".standardgraph" / "common_core.db")).expanduser()

NOTE      = "[exact-match 5/5] Source and target standard text are identical."
NOTE_NORM = "[exact-match 5/5] Source and target text are identical apart from whitespace/case."

# A whitespace/case-insensitive normalization: same words, same order → same standard.
def _norm(col: str) -> str:
    return (f"lower(trim(replace(replace(replace({col},char(10),' '),char(9),' '),'  ',' ')))")

# Rows to score: unscored (nlp_pass) crosswalks whose source/target text match exactly,
# or match after whitespace/case normalization (still a definitional equivalence).
SELECT_SQL = f"""
    SELECT cm.id, cm.grade_delta,
           CASE WHEN s.standard_text = t.standard_text THEN 0 ELSE 1 END AS normalized
    FROM crosswalk_mappings cm
    JOIN standards s ON cm.source_id = s.id
    JOIN standards t ON cm.target_id = t.id
    WHERE cm.notes LIKE 'nlp_pass%'
      AND (s.standard_text = t.standard_text
           OR {_norm('s.standard_text')} = {_norm('t.standard_text')})
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministically score exact-match crosswalks")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing")
    g.add_argument("--apply", action="store_true", help="Write the exact-match scores to the DB")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(SELECT_SQL).fetchall()
    ids = [r[0] for r in rows]
    norm_ids = {r[0] for r in rows if r[2] == 1}
    gd_gt1 = sum(1 for r in rows if abs(r[1]) > 1)

    print(f"DB: {DB_PATH}")
    print(f"Exact-match unscored rows found: {len(ids):,}  "
          f"(byte-identical: {len(ids) - len(norm_ids):,}, whitespace/case-only: {len(norm_ids):,}; "
          f"grade_delta ≤1: {len(ids) - gd_gt1:,}, >1: {gd_gt1:,})")

    scored_before = conn.execute(
        "SELECT COUNT(*) FROM crosswalk_mappings WHERE notes LIKE '%LLM score%' OR notes LIKE '%exact-match%'"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]

    if args.dry_run:
        after = scored_before + len(ids)
        print(f"Quality-scored coverage: {scored_before:,}/{total:,} ({scored_before/total*100:.1f}%) "
              f"→ would become {after:,}/{total:,} ({after/total*100:.1f}%)")
        conn.close()
        return 0

    # --apply
    conn.executemany(
        "UPDATE crosswalk_mappings SET notes = ?, updated_at = datetime('now') WHERE id = ?",
        [(NOTE_NORM if i in norm_ids else NOTE, i) for i in ids],
    )
    conn.commit()
    scored_after = conn.execute(
        "SELECT COUNT(*) FROM crosswalk_mappings WHERE notes LIKE '%LLM score%' OR notes LIKE '%exact-match%'"
    ).fetchone()[0]
    conn.close()
    print(f"Applied. Quality-scored coverage: {scored_before:,} → {scored_after:,} "
          f"({scored_after/total*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
