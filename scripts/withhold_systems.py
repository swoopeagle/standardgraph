"""Remove withheld systems (data/withheld_systems.txt) from a release DB copy.

Deletes their standards and every row that points at them. Refuses the live DB;
re-ingest with the system's fetcher once permission arrives.
Usage: DB_PATH=~/.standardgraph/common_core_scan.db uv run python scripts/withhold_systems.py [--dry-run]
"""
import os
import sqlite3
import sys
from pathlib import Path

LIST = Path(__file__).resolve().parent.parent / "data" / "withheld_systems.txt"


def withheld():
    return [l.split("#")[0].strip() for l in LIST.read_text().splitlines() if l.split("#")[0].strip()]


def main():
    dry = "--dry-run" in sys.argv
    path = os.path.expanduser(os.environ.get("DB_PATH", "~/.standardgraph/common_core.db"))
    if os.path.basename(path) == "common_core.db" and not dry:
        sys.exit("refusing to write the live DB; point DB_PATH at a copy")
    systems = withheld()
    db = sqlite3.connect(path)
    q = ",".join("?" * len(systems))
    ids = f"(SELECT id FROM standards WHERE system IN ({q}))"
    stmts = [
        ("crosswalk_mappings", f"source_system IN ({q}) OR target_system IN ({q})", systems * 2),
        ("standard_relationships", f"source_id IN {ids} OR target_id IN {ids}", systems * 2),
        ("embeddings", f"standard_id IN {ids}", systems),
        ("keywords", f"standard_id IN {ids}", systems),
        ("sub_standards", f"system IN ({q})", systems),
        ("standards", f"system IN ({q})", systems),  # last: the subqueries above need these rows
    ]
    for table, where, args in stmts:
        n = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]
        print(f"{table}: {n} rows{' (dry run)' if dry else ''}")
        if not dry:
            db.execute(f"DELETE FROM {table} WHERE {where}", args)
    if not dry:
        db.commit()
        db.execute("VACUUM")


if __name__ == "__main__":
    main()
