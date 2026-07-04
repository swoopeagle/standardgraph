"""In-session crosswalk scoring harness (Claude-as-scorer, no Ollama needed).

Two modes:

  export — dump the next batch of unscored (nlp_pass) crosswalks as JSON for a
           human/Claude to score. Prioritizes by source-system filter then cosine.

  apply  — read a scores JSON ({"<id>": {"score": 1-5, "rationale": "..."}, ...})
           and write each into crosswalk_mappings.notes as "[LLM score N/5] ...".
           Scores of 1-2 set flagged_for_review=1 and append " | MISMATCH: ...".

Usage:
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/score_batch.py \
        export --like 'ap-%' --limit 60 --out /tmp/batch.json
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/score_batch.py \
        apply --scores /tmp/scores.json
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".standardgraph" / "common_core.db")).expanduser()


def export(like: str | None, limit: int, out: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    where = ["cm.notes LIKE 'nlp_pass%'"]
    params: list = []
    if like:
        where.append("cm.source_system LIKE ?")
        params.append(like)
    params.append(limit)
    rows = conn.execute(
        f"""SELECT cm.id, cm.source_id, cm.target_id, cm.source_system, cm.target_system,
                   cm.confidence_score, cm.grade_delta,
                   s.standard_text AS source_text, s.domain AS source_domain,
                   t.standard_text AS target_text, t.domain AS target_domain
            FROM crosswalk_mappings cm
            JOIN standards s ON s.id = cm.source_id
            JOIN standards t ON t.id = cm.target_id
            WHERE {' AND '.join(where)}
            ORDER BY cm.confidence_score DESC
            LIMIT ?""",
        params,
    ).fetchall()
    conn.close()
    batch = [dict(r) for r in rows]
    Path(out).write_text(json.dumps(batch, indent=2))
    print(f"Exported {len(batch)} rows → {out}")
    return 0


def apply(scores_path: str) -> int:
    scores = json.loads(Path(scores_path).read_text())
    conn = sqlite3.connect(DB_PATH)
    n_ok = n_flag = 0
    for row_id, val in scores.items():
        score = int(val["score"])
        rationale = str(val["rationale"]).strip().rstrip(".")
        note = f"[LLM score {score}/5] {rationale}."
        flagged = 1 if score <= 2 else 0
        if flagged:
            mismatch = str(val.get("mismatch", rationale)).strip().rstrip(".")
            note += f" | MISMATCH: {mismatch}."
            n_flag += 1
        conn.execute(
            "UPDATE crosswalk_mappings SET notes=?, flagged_for_review=?, updated_at=datetime('now') WHERE id=?",
            (note, flagged, int(row_id)),
        )
        n_ok += 1
    conn.commit()
    conn.close()
    print(f"Applied {n_ok} scores ({n_flag} flagged as 1-2).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--like", default=None, help="source_system LIKE filter (e.g. 'ap-%')")
    e.add_argument("--limit", type=int, default=60)
    e.add_argument("--out", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--scores", required=True)
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 2
    if args.cmd == "export":
        return export(args.like, args.limit, args.out)
    return apply(args.scores)


if __name__ == "__main__":
    sys.exit(main())
