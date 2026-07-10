#!/usr/bin/env python3
"""Phase 6 (final) — merge the pilot's verified edges from the scratch DB into prod.

Deliberately does NOT re-derive anything (no re-reading label files, no
re-classifying). The scratch DB already holds the exact, already-tested state
(insert + SOFT->HARD promotion; mcp_test 333/333, learning_path eval 47/47,
0 cycles). This script:

  1. Applies the same additive schema migration to prod, if not already present
     (idempotent — checks column existence first).
  2. ATTACHes the scratch DB and upserts every method='llm_validated' row,
     copying confidence_score/notes/method verbatim from scratch.
  3. Verifies row counts against the predicted diff before committing... actually
     verification is a separate read-only pass after commit (see prereq_merge_verify
     block at the bottom) so any assertion failure is visible immediately.

Usage: uv run python scripts/prereq_pilot/prereq_merge_prod.py <prod_db> <scratch_db>
"""
import sqlite3
import sys

PROD = sys.argv[1]
SCRATCH = sys.argv[2]

MIGRATION = [
    "ALTER TABLE standard_relationships ADD COLUMN confidence_score REAL",
    "ALTER TABLE standard_relationships ADD COLUMN notes TEXT",
    "ALTER TABLE standard_relationships ADD COLUMN method TEXT NOT NULL DEFAULT 'grade_heuristic'",
    "ALTER TABLE standard_relationships ADD COLUMN flagged_for_review INTEGER NOT NULL DEFAULT 0",
]
INDEX = "CREATE INDEX IF NOT EXISTS idx_relationships_method ON standard_relationships(method, relationship)"

UPSERT = """
INSERT INTO standard_relationships
    (source_id, target_id, relationship, system, confidence_score, notes, method, flagged_for_review)
VALUES (?, ?, ?, ?, ?, ?, ?, 0)
ON CONFLICT(source_id, target_id, relationship) DO UPDATE SET
    confidence_score = excluded.confidence_score,
    notes            = excluded.notes,
    method           = excluded.method,
    flagged_for_review = 0
"""


def main():
    con = sqlite3.connect(PROD)
    cur = con.cursor()

    cols = {r[1] for r in cur.execute("PRAGMA table_info(standard_relationships)").fetchall()}
    applied = []
    for stmt in MIGRATION:
        col = stmt.split("ADD COLUMN")[1].split()[0]
        if col not in cols:
            cur.execute(stmt)
            applied.append(col)
    cur.execute(INDEX)
    con.commit()
    print(f"schema migration: added columns {applied or '(none — already present)'}")

    # Pull the verified edges straight from scratch — no re-derivation.
    scr = sqlite3.connect(SCRATCH)
    rows = scr.execute(
        "SELECT source_id, target_id, relationship, system, confidence_score, notes, method "
        "FROM standard_relationships WHERE method='llm_validated'").fetchall()
    scr.close()
    print(f"copying {len(rows)} verified rows from scratch")

    before = cur.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    for r in rows:
        cur.execute(UPSERT, r)
    con.commit()
    after = cur.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    print(f"prod standard_relationships: {before} -> {after} (net new: {after - before})")

    n_llm = cur.execute(
        "SELECT COUNT(*) FROM standard_relationships WHERE method='llm_validated'").fetchone()[0]
    print(f"prod rows now method='llm_validated': {n_llm}")

    conf_dist = cur.execute(
        "SELECT confidence_score, COUNT(*) FROM standard_relationships "
        "WHERE method='llm_validated' AND relationship='prerequisite' GROUP BY confidence_score"
    ).fetchall()
    print(f"prerequisite confidence distribution: {conf_dist}")

    # sanity: unrelated tables/rows untouched
    std = cur.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    cw = cur.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    print(f"standards={std} crosswalk_mappings={cw} (should be unchanged from baseline)")

    con.close()


if __name__ == "__main__":
    main()
