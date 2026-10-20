"""Suppress low-cosine hub crosswalks (flagged_for_review=1) - the crosswalk-quality rule.

Rule (chosen on gold-v2, held-out; see CONTEXT.md 2026-10-19 crosswalk-quality): a crosswalk is served
only if confidence_score (embedding cosine) >= FLOOR. Edges below it are flagged, not deleted, and
tagged in `notes` with MARKER so the change is reversible (--revert) and include_flagged=True still shows them.

    DB_PATH=<db> python scripts/apply_cosine_floor.py --dry-run | --apply | --revert
"""
import argparse, os, sqlite3, sys

FLOOR = 0.75
MARKER = " | COSINE-FLOOR<0.75"


def apply(conn, floor=FLOOR):
    cur = conn.execute(
        "UPDATE crosswalk_mappings SET flagged_for_review=1, notes=COALESCE(notes,'')||?, updated_at=datetime('now') "
        "WHERE flagged_for_review=0 AND verified_by_human=0 AND confidence_score<? AND COALESCE(notes,'') NOT LIKE '%'||?||'%'",
        (MARKER, floor, MARKER))
    return cur.rowcount


def revert(conn):
    cur = conn.execute(
        "UPDATE crosswalk_mappings SET flagged_for_review=0, notes=REPLACE(notes,?,''), updated_at=datetime('now') "
        "WHERE notes LIKE '%'||?||'%'", (MARKER, MARKER))
    return cur.rowcount


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--apply", action="store_true"); g.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    path = os.path.expanduser(os.environ.get("DB_PATH", "~/.standardgraph/common_core.db"))
    if "common_core.db" == os.path.basename(path) and not a.dry_run:
        sys.exit("refusing to write the live DB; point DB_PATH at a copy")
    conn = sqlite3.connect(path)
    if a.dry_run:
        n = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review=0 AND verified_by_human=0 AND confidence_score<?", (FLOOR,)).fetchone()[0]
        print(f"would flag {n:,} edges with cosine < {FLOOR}")
    else:
        print(f"{'reverted' if a.revert else 'flagged'} {(revert if a.revert else apply)(conn):,} edges"); conn.commit()
