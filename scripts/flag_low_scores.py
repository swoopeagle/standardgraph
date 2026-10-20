"""Enforce the documented score-flag policy (CLAUDE.md): direct-family edges scored <=2 and hub edges
scored <=HUB_MAX are flagged_for_review=1. Some edges escaped it (scored before/without the flag step).
Flags are tagged in `notes` with MARKER so --revert undoes exactly this change.

    DB_PATH=<db> python scripts/flag_low_scores.py --dry-run | --apply | --revert [--hub-max 1|2]
"""
import argparse, os, sqlite3, sys

MARKER = " | SCORE-FLAG"
SCORE = "CAST(substr(notes, instr(notes,'[LLM score ')+11, 1) AS INTEGER)"
WHERE = (f"flagged_for_review=0 AND verified_by_human=0 AND notes LIKE '%[LLM score %' AND ("
         f"(notes LIKE '%direct_family%' AND {SCORE}<=2) OR (notes NOT LIKE '%direct_family%' AND {SCORE}<=?))")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--apply", action="store_true"); g.add_argument("--revert", action="store_true")
    ap.add_argument("--hub-max", type=int, default=1, help="documented policy is 1; gold-v2 shows hub score-2 edges are 39%% lenient-correct")
    a = ap.parse_args()
    path = os.path.expanduser(os.environ.get("DB_PATH", "~/.standardgraph/common_core.db"))
    if os.path.basename(path) == "common_core.db" and not a.dry_run:
        sys.exit("refusing to write the live DB; point DB_PATH at a copy")
    conn = sqlite3.connect(path)
    if a.dry_run:
        print(f"would flag {conn.execute(f'SELECT COUNT(*) FROM crosswalk_mappings WHERE {WHERE}', (a.hub_max,)).fetchone()[0]:,} edges")
    elif a.revert:
        n = conn.execute("UPDATE crosswalk_mappings SET flagged_for_review=0, notes=REPLACE(notes,?,''), updated_at=datetime('now') WHERE notes LIKE '%'||?||'%'", (MARKER, MARKER)).rowcount
        conn.commit(); print(f"reverted {n:,} edges")
    else:
        n = conn.execute(f"UPDATE crosswalk_mappings SET flagged_for_review=1, notes=notes||?, updated_at=datetime('now') WHERE {WHERE}", (MARKER, a.hub_max)).rowcount
        conn.commit(); print(f"flagged {n:,} edges")
