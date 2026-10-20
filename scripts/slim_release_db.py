"""Shrink a release DB copy without changing what the MCP tools return.

Run AFTER withhold_systems.py and the cosine-floor / flag scripts (they touch the tables this drops).
Steps (each idempotent, each skipped when already applied):
  1. drop idx_relationships_source (prefix of the UNIQUE autoindex) and idx_relationships_method
  2. delete 'successor' relationship rows (verified exact mirrors of 'prerequisite'; server derives them via target_id)
  3. drop the runtime-unused `keywords` table (the ingestion pipeline DB keeps it)
  4. float32 -> float16 embeddings (server decodes by blob length; recall@10 verified, see CONTEXT.md)
  5. VACUUM
Usage: DB_PATH=~/.standardgraph/common_core_slim.db uv run python scripts/slim_release_db.py [--dry-run] [--keep-fp32]
"""
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

LIVE = Path.home() / ".standardgraph" / "common_core.db"
R = "standard_relationships"
MIRROR = (  # rows of relationship {a} with no exact {b} mirror (fields compared: everything but id/created_at)
    "SELECT COUNT(*) FROM {r} a WHERE a.relationship='{a}' AND NOT EXISTS (SELECT 1 FROM {r} b "
    "WHERE b.relationship='{b}' AND b.source_id=a.target_id AND b.target_id=a.source_id AND b.system=a.system "
    "AND b.method=a.method AND b.confidence_score IS a.confidence_score AND b.notes IS a.notes "
    "AND b.flagged_for_review=a.flagged_for_review)"
)


def sizes(db):
    return {n: b for n, b in db.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")}


def has(db, kind, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone() is not None


def main():
    dry, fp32 = "--dry-run" in sys.argv, "--keep-fp32" in sys.argv
    path = Path(os.path.expanduser(os.environ.get("DB_PATH", ""))).resolve() if os.environ.get("DB_PATH") else None
    if not path or not path.exists():
        sys.exit("set DB_PATH to the release DB copy")
    if path == LIVE.resolve() or path.name == "common_core.db":
        sys.exit("refusing the live DB (common_core.db); point DB_PATH at a copy")
    db = sqlite3.connect(path)
    sz, before = sizes(db), path.stat().st_size
    saved = {}

    # 1. indexes
    for ix in ("idx_relationships_source", "idx_relationships_method"):
        if has(db, "index", ix):
            saved[f"index {ix}"] = sz[ix]
            if not dry:
                db.execute(f"DROP INDEX {ix}")

    # 2. successor mirrors
    n_succ = db.execute(f"SELECT COUNT(*) FROM {R} WHERE relationship='successor'").fetchone()[0]
    if n_succ:
        for a, b in (("successor", "prerequisite"), ("prerequisite", "successor")):
            bad = db.execute(MIRROR.format(r=R, a=a, b=b)).fetchone()[0]
            if bad:
                sys.exit(f"abort: {bad} {a} rows have no exact {b} mirror; successors are not derivable")
        total = db.execute(f"SELECT COUNT(*) FROM {R}").fetchone()[0]
        parts = [R, "sqlite_autoindex_standard_relationships_1", "idx_relationships_target"]
        saved[f"{n_succ} successor rows"] = int(sum(sz.get(p, 0) for p in parts) * n_succ / total)
        if not dry:
            db.execute(f"DELETE FROM {R} WHERE relationship='successor'")

    # 3. keywords
    if has(db, "table", "keywords"):
        saved["keywords table+indexes"] = sum(v for k, v in sz.items() if k == "keywords" or k.startswith(("idx_keywords", "sqlite_autoindex_keywords")))
        if not dry:
            db.execute("DROP TABLE keywords")

    # 4. float16 embeddings
    if not fp32:
        rows = db.execute("SELECT COUNT(*), SUM(LENGTH(vector)) FROM embeddings WHERE LENGTH(vector)=dimensions*4").fetchone()
        if rows[0]:
            saved[f"{rows[0]} float32 embeddings -> float16"] = rows[1] // 2
            if not dry:
                cur = db.execute("SELECT standard_id, vector FROM embeddings WHERE LENGTH(vector)=dimensions*4").fetchall()
                db.executemany("UPDATE embeddings SET vector=? WHERE standard_id=?",
                               ((np.frombuffer(v, np.float32).astype(np.float16).tobytes(), i) for i, v in cur))

    for k, v in saved.items():
        print(f"{'would save' if dry else 'saved'} ~{v / 1e6:8.1f} MB  {k}")
    if dry:
        print(f"projected: {before / 1e6:.0f} MB -> ~{(before - sum(saved.values())) / 1e6:.0f} MB (before VACUUM rounding)")
        return
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"{before / 1e6:.0f} MB -> {path.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
