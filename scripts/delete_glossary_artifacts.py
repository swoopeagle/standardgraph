"""Remove glossary-artifact 'standards' — single words/acronyms with <5-char text.

Some fetchers captured glossary/vocabulary terms and acronyms as standards
(e.g. "[MAX]", "[SUM]", "[Bias]", "[NASA]", "[9/11]", "[MRSA]"). They carry no
pedagogical content, pollute search_standards, and fail the db_integrity eval.
This deletes them; ON DELETE CASCADE clears their embeddings/keywords/sub_standards/
crosswalk rows, and the external-content FTS index is rebuilt.

Usage:
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/delete_glossary_artifacts.py --dry-run
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/delete_glossary_artifacts.py --apply
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".standardgraph" / "common_core.db")).expanduser()

# "Standards" whose trimmed text is shorter than this are treated as artifacts.
MIN_LEN = 5


def main() -> int:
    ap = argparse.ArgumentParser(description="Delete <5-char glossary-artifact standards")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Report what would be deleted; write nothing")
    g.add_argument("--apply", action="store_true", help="Delete the artifacts and rebuild the FTS index")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT system, COUNT(*) FROM standards WHERE LENGTH(TRIM(standard_text)) < ? "
        "GROUP BY system ORDER BY COUNT(*) DESC",
        (MIN_LEN,),
    ).fetchall()
    total = sum(n for _, n in rows)
    print(f"DB: {DB_PATH}")
    print(f"Glossary-artifact standards (<{MIN_LEN} chars): {total}")
    for system, n in rows:
        print(f"  {system}: {n}")

    if args.dry_run or total == 0:
        conn.close()
        return 0

    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM standards WHERE LENGTH(TRIM(standard_text)) < ?", (MIN_LEN,))
    conn.commit()
    # External-content FTS5 has no delete triggers; rebuild it from the content table.
    conn.execute("INSERT INTO standards_fts(standards_fts) VALUES('rebuild')")
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM standards WHERE LENGTH(TRIM(standard_text)) < ?", (MIN_LEN,)
    ).fetchone()[0]
    conn.close()
    print(f"Deleted {total} artifacts; remaining <{MIN_LEN}-char standards: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
