#!/usr/bin/env python3
"""Rationale-overlay merge of two diverged StandardGraph DBs.

Background: rationale generation ran on two independent DB copies that diverged on
different axes — one is the standards/systems superset, the other has far more LLM
rationales. This merges them into one authoritative DB without trying to reconcile
standards/embeddings row-by-row.

Strategy (see docs/db_merge_strategy.md):
  * BASE wins outright for standards, embeddings, relationships, crosswalk structure.
    Use the standards/systems superset as --base.
  * Overlay only the *rationale* (crosswalk_mappings.notes) from --overlay onto the
    base's crosswalk rows, joined on (source_id, target_id, relationship) — never id.
  * A row is "scored" when notes NOT LIKE 'nlp_pass%' (the pipeline placeholder).
    Overlay wins on conflicts (it carries the bigger-model rationales).
  * confidence_score is the cosine score (structural) and is left as the base's.
  * --apply-missing also inserts overlay-only scored crosswalks whose BOTH endpoints
    exist in the base standards table (FK-safe).

Usage:
  uv run python scripts/merge_dbs.py \
      --base /tmp/mini3_current.db --overlay /tmp/mini2_current.db \
      --out /tmp/merged.db [--apply-missing] [--dry-run]

The script never touches --base or --overlay (read-only); it copies --base to --out
and mutates only the copy. Promotion (install / push to minis / upload to HF) is a
separate, deliberate step.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

SCORED = "notes IS NOT NULL AND notes NOT LIKE 'nlp_pass%'"


def _count(con, sql, params=()):
    return con.execute(sql, params).fetchone()[0]


def stats(con, label):
    s = _count(con, "SELECT COUNT(*) FROM standards")
    sys_ = _count(con, "SELECT COUNT(DISTINCT system) FROM standards")
    x = _count(con, "SELECT COUNT(*) FROM crosswalk_mappings")
    scored = _count(con, f"SELECT COUNT(*) FROM crosswalk_mappings WHERE {SCORED}")
    print(f"  {label:8} standards={s:,}  systems={sys_}  crosswalks={x:,}  scored={scored:,}")
    return scored


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="superset DB (standards/systems win)")
    ap.add_argument("--overlay", required=True, help="rationale-rich DB (notes win)")
    ap.add_argument("--out", required=True, help="output merged DB (overwritten)")
    ap.add_argument("--apply-missing", action="store_true",
                    help="also insert overlay-only scored crosswalks (FK-safe)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute uplift but do not write --out")
    args = ap.parse_args()

    base, overlay, out = Path(args.base), Path(args.overlay), Path(args.out)
    for p in (base, overlay):
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1

    print("── Inputs ──")
    with sqlite3.connect(f"file:{base}?mode=ro", uri=True) as b:
        base_scored = stats(b, "base")
    with sqlite3.connect(f"file:{overlay}?mode=ro", uri=True) as o:
        ov_scored = stats(o, "overlay")

    if args.dry_run:
        # Measure uplift without copying the (large) base file.
        con = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        con.execute("ATTACH ? AS ov", (str(overlay),))
        gain = _count(con, f"""
            SELECT COUNT(*) FROM crosswalk_mappings c
            WHERE (c.notes IS NULL OR c.notes LIKE 'nlp_pass%')
              AND EXISTS (SELECT 1 FROM ov.crosswalk_mappings s
                          WHERE s.source_id=c.source_id AND s.target_id=c.target_id
                            AND s.relationship=c.relationship
                            AND s.notes IS NOT NULL AND s.notes NOT LIKE 'nlp_pass%')""")
        missing = _count(con, f"""
            SELECT COUNT(*) FROM ov.crosswalk_mappings s
            WHERE s.notes IS NOT NULL AND s.notes NOT LIKE 'nlp_pass%'
              AND s.source_id IN (SELECT id FROM standards)
              AND s.target_id IN (SELECT id FROM standards)
              AND NOT EXISTS (SELECT 1 FROM crosswalk_mappings c
                              WHERE c.source_id=s.source_id AND c.target_id=s.target_id
                                AND c.relationship=s.relationship)""")
        con.close()
        print("\n── Dry run (no write) ──")
        print(f"  base-unscored rows the overlay can fill : {gain:,}")
        print(f"  overlay-only scored rows (--apply-missing): {missing:,}")
        print(f"  projected scored after merge            : ~{base_scored + gain:,}"
              f"{f' (+{missing:,} with --apply-missing)' if missing else ''}")
        return 0

    print(f"\n── Copying base → {out} ──")
    shutil.copyfile(base, out)

    con = sqlite3.connect(out)
    con.execute("PRAGMA foreign_keys=ON")

    # Stage the overlay's scored rows into an indexed temp table. Joining against
    # this is dramatically faster than cross-DB correlated subqueries, and it never
    # mutates the read-only overlay snapshot.
    con.execute("ATTACH ? AS ov", (str(overlay),))  # read-only in practice (SELECT only)
    con.execute(f"""
        CREATE TEMP TABLE ov_scored AS
        SELECT source_id, target_id, relationship, source_system, target_system,
               confidence_score, grade_delta, notes, created_at, updated_at
        FROM ov.crosswalk_mappings
        WHERE {SCORED}
    """)
    con.execute("DETACH ov")
    con.execute("CREATE INDEX ix_ov ON ov_scored(source_id, target_id, relationship)")
    staged = _count(con, "SELECT COUNT(*) FROM ov_scored")
    print(f"  staged {staged:,} scored overlay rows (indexed)")

    # 1) Overlay rationale onto base rows (overlay wins on every scored pair).
    # UPDATE..FROM (SQLite >= 3.33) does a single hash/merge join — far faster than
    # correlated subqueries over ~100k rows.
    cur = con.execute("""
        UPDATE crosswalk_mappings AS c
        SET notes = s.notes
        FROM ov_scored s
        WHERE s.source_id=c.source_id AND s.target_id=c.target_id
          AND s.relationship=c.relationship
    """)
    updated = cur.rowcount
    print(f"  rationales overlaid onto base rows: {updated:,}")

    inserted = 0
    if args.apply_missing:
        # Join-based form (FK check via JOIN standards, dedupe via LEFT JOIN/IS NULL)
        # is far faster than IN(...) + NOT EXISTS correlated subqueries.
        cur = con.execute("""
            INSERT INTO crosswalk_mappings
              (source_id, target_id, source_system, target_system, relationship,
               confidence_score, grade_delta, notes, created_at, updated_at)
            SELECT s.source_id, s.target_id, s.source_system, s.target_system,
                   s.relationship, s.confidence_score, s.grade_delta, s.notes,
                   s.created_at, s.updated_at
            FROM ov_scored s
            JOIN standards ss ON ss.id = s.source_id
            JOIN standards st ON st.id = s.target_id
            LEFT JOIN crosswalk_mappings c
                   ON c.source_id = s.source_id AND c.target_id = s.target_id
                  AND c.relationship = s.relationship
            WHERE c.id IS NULL
        """)
        inserted = cur.rowcount
        print(f"  overlay-only crosswalks inserted  : {inserted:,}")

    con.commit()

    print("\n── Result ──")
    merged_scored = stats(con, "merged")
    # Invariant: standards superset preserved.
    base_n = sqlite3.connect(f"file:{base}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM standards").fetchone()[0]
    out_n = _count(con, "SELECT COUNT(*) FROM standards")
    con.close()

    ok = out_n == base_n
    print(f"\n  standards preserved: {'OK' if ok else 'MISMATCH'} "
          f"({out_n:,} vs base {base_n:,})")
    print(f"  scored uplift: {base_scored:,} → {merged_scored:,} "
          f"(+{merged_scored - base_scored:,})")
    print(f"\n  Wrote {out}. Validate with:")
    print(f"    ln -sf {out} data/common_core.db && "
          f"uv run python scripts/eval/run_all.py --tier structural")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
