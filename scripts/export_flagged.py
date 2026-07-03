"""Export flagged crosswalk rows for audit.

Groups by source_system + mismatch_type and writes:
  - flagged_export.csv   — one row per mapping, human-readable
  - flagged_export.json  — same data, structured for downstream scripts

Usage:
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/export_flagged.py
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/export_flagged.py --out /tmp/flagged
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/export_flagged.py --system ngss
"""
import argparse
import csv
import json
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".standardgraph" / "common_core.db"))

_MISMATCH_RE = re.compile(r"MISMATCH:\s*(.+?)\.?\s*$")
_SCORE_RE = re.compile(r"\[LLM score (\d)/5\]")


def _parse_mismatch(notes: str | None) -> str:
    if not notes:
        return "unknown"
    m = _MISMATCH_RE.search(notes)
    return m.group(1).strip() if m else "unknown"


def _parse_score(notes: str | None) -> int | None:
    if not notes:
        return None
    m = _SCORE_RE.search(notes)
    return int(m.group(1)) if m else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Export flagged crosswalk rows")
    parser.add_argument("--out", default="flagged_export", help="Output path prefix (no extension)")
    parser.add_argument("--target-system", default=None,
                        help="Filter to one target hub (e.g. 'ngss', 'ccss')")
    parser.add_argument("--min-score", type=int, default=None,
                        help="Only export rows with LLM quality score <= N (e.g. 2)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where_clauses = ["cm.flagged_for_review = 1"]
    params: list = []
    if args.target_system:
        where_clauses.append("cm.target_system = ?")
        params.append(args.target_system)

    rows = conn.execute(
        f"""SELECT
              cm.source_id, cm.source_system,
              cm.target_id, cm.target_system,
              cm.confidence_score, cm.grade_delta,
              cm.notes,
              s.standard_text AS source_text,
              t.standard_text AS target_text
            FROM crosswalk_mappings cm
            JOIN standards s ON s.id = cm.source_id
            JOIN standards t ON t.id = cm.target_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY cm.source_system, cm.confidence_score DESC""",
        params,
    ).fetchall()
    conn.close()

    records = []
    for r in rows:
        score = _parse_score(r["notes"])
        if args.min_score is not None and score is not None and score > args.min_score:
            continue
        records.append({
            "source_id":       r["source_id"],
            "source_system":   r["source_system"],
            "source_text":     r["source_text"],
            "target_id":       r["target_id"],
            "target_system":   r["target_system"],
            "target_text":     r["target_text"],
            "confidence":      round(r["confidence_score"], 4),
            "grade_delta":     r["grade_delta"],
            "quality_score":   score,
            "mismatch_type":   _parse_mismatch(r["notes"]),
            "notes":           r["notes"],
        })

    # Summary by (source_system, target_system, mismatch_type)
    from collections import defaultdict
    summary: dict = defaultdict(int)
    for rec in records:
        key = (rec["source_system"], rec["target_system"], rec["mismatch_type"])
        summary[key] += 1

    csv_path = Path(args.out).with_suffix(".csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source_id", "source_system", "source_text",
            "target_id", "target_system", "target_text",
            "confidence", "grade_delta", "quality_score", "mismatch_type", "notes",
        ])
        writer.writeheader()
        writer.writerows(records)

    json_path = Path(args.out).with_suffix(".json")
    with open(json_path, "w") as f:
        json.dump({
            "total_flagged": len(records),
            "summary": [
                {"source_system": k[0], "target_system": k[1],
                 "mismatch_type": k[2], "count": v}
                for k, v in sorted(summary.items(), key=lambda x: -x[1])
            ],
            "rows": records,
        }, f, indent=2)

    print(f"Exported {len(records)} flagged rows")
    print(f"  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")
    print()
    print("Top mismatch categories:")
    for (src_sys, tgt_sys, mtype), cnt in sorted(summary.items(), key=lambda x: -x[1])[:15]:
        print(f"  {src_sys:15s} → {tgt_sys:10s}  [{cnt:4d}]  {mtype}")


if __name__ == "__main__":
    main()
