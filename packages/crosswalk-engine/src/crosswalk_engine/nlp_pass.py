"""
NLP-based crosswalk: map every state standard to its closest CCSS equivalent
using precomputed 768-dim nomic-embed-text cosine similarity.

Writes rows into crosswalk_mappings(source_id, target_id, target_system,
relationship, confidence_score, grade_delta, notes).

Run:
    uv run python packages/crosswalk-engine/src/crosswalk_engine/nlp_pass.py
    uv run python packages/crosswalk-engine/src/crosswalk_engine/nlp_pass.py --system tx
    uv run python packages/crosswalk-engine/src/crosswalk_engine/nlp_pass.py --top 3
"""
import argparse
import sqlite3
import struct

import numpy as np

from shared.config import DB_PATH

# Only generate mappings above this cosine similarity threshold
DEFAULT_THRESHOLD = 0.70
# How many hub candidates to store per source standard
DEFAULT_TOP_N = 1
# Skip mappings where abs(grade_delta) exceeds this (e.g. K↔HS is delta=9, too noisy)
DEFAULT_GRADE_DELTA_MAX = 5


def _load_embeddings(conn: sqlite3.Connection, system: str) -> tuple[np.ndarray, list[str]]:
    """Load all embeddings for one curriculum system. Returns (matrix, ids)."""
    rows = conn.execute(
        """SELECT e.standard_id, e.vector, e.dimensions
           FROM embeddings e
           JOIN standards s ON s.id = e.standard_id
           WHERE s.system = ?""",
        (system,),
    ).fetchall()
    if not rows:
        return np.empty((0, 0), dtype=np.float32), []
    dim = rows[0][2]
    matrix = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), dim)
    ids = [r[0] for r in rows]
    return matrix, ids


_WORD_GRADES = {
    "kindergarten": 0, "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "tenth": 10, "eleventh": 11, "twelfth": 12,
}


def _grade_key(g: str) -> int:
    # K=0, numeric grades map to their year (1..12), HS≈9 (kept for back-compat with
    # the old K,1..8,HS ordering). Also tolerates spelled-out grades and ranges
    # ("6-8", "K-12" → low end). Grades 9-12 and these formats were previously
    # unmapped → 99, producing spurious grade_delta values of -90..-99.
    if not g:
        return 99
    g = g.strip()
    if g == "K":
        return 0
    if g == "HS":
        return 9
    if g.lower() in _WORD_GRADES:
        return _WORD_GRADES[g.lower()]
    if "-" in g:  # range like "6-8" or "K-12": use the low end
        return _grade_key(g.split("-")[0].strip())
    try:
        return int(g)
    except (ValueError, TypeError):
        return 99


def _grade_delta(g_src: str, g_tgt: str) -> int:
    return _grade_key(g_tgt) - _grade_key(g_src)


def _hub_for_system(source_system: str, conn: sqlite3.Connection) -> str:
    """Return the hub system for a given source, keyed by subject."""
    row = conn.execute(
        "SELECT subject FROM standards WHERE system=? LIMIT 1", (source_system,)
    ).fetchone()
    subject = (row[0] or "").lower() if row else ""
    if subject == "science":
        return "ngss"
    if subject == "ela":
        return "ccss-ela"
    if subject == "social-studies":
        return "c3"
    if subject == "cs":
        return "csta"
    return "ccss"


def generate_crosswalk(
    source_system: str,
    conn: sqlite3.Connection,
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    grade_delta_max: int = DEFAULT_GRADE_DELTA_MAX,
) -> int:
    """
    Map all standards from source_system to its hub (CCSS for math, NGSS for science)
    via cosine similarity. Returns number of mappings inserted.

    grade_delta_max: skip candidate pairs where abs(grade_delta) > this value.
    Filters out systematically bad matches (e.g. K-level source → HS hub) that
    pass the cosine threshold due to generic vocabulary overlap.
    """
    hub_system = _hub_for_system(source_system, conn)
    src_matrix, src_ids = _load_embeddings(conn, source_system)
    hub_matrix, hub_ids = _load_embeddings(conn, hub_system)

    if src_matrix.size == 0 or hub_matrix.size == 0:
        print(f"  {source_system}: no embeddings found — skipping")
        return 0

    # Normalise both matrices
    src_norms = np.linalg.norm(src_matrix, axis=1, keepdims=True) + 1e-9
    hub_norms = np.linalg.norm(hub_matrix, axis=1, keepdims=True) + 1e-9
    src_unit  = src_matrix / src_norms
    hub_unit  = hub_matrix / hub_norms

    # (n_src, n_hub) cosine similarity matrix
    scores = src_unit @ hub_unit.T

    src_grades: dict[str, str] = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT id, grade FROM standards WHERE system=?", (source_system,)
        ).fetchall()
    }
    hub_grades: dict[str, str] = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT id, grade FROM standards WHERE system=?", (hub_system,)
        ).fetchall()
    }

    mappings: list[tuple] = []
    for i, src_id in enumerate(src_ids):
        row = scores[i]
        top_indices = np.argsort(row)[::-1]
        added = 0
        for j in top_indices:
            score = float(row[j])
            if score < threshold or added >= top_n:
                break
            tgt_id = hub_ids[j]
            delta  = _grade_delta(src_grades.get(src_id, ""), hub_grades.get(tgt_id, ""))
            if abs(delta) > grade_delta_max:
                continue
            mappings.append((
                src_id,
                source_system,
                tgt_id,
                hub_system,
                "equivalent",
                round(score, 4),
                delta,
                0,
                f"nlp_pass cosine={score:.4f}",
            ))
            added += 1

    with conn:
        # UPSERT rather than INSERT OR REPLACE: on an existing (source_id,
        # target_id) pair, refresh the cosine confidence/grade_delta but PRESERVE
        # the notes if they already carry an LLM quality score, and never clobber
        # human-curation columns (verified_by_human, flagged_for_review, verified_*).
        # INSERT OR REPLACE deletes+reinserts the row, silently wiping all of that
        # — see feedback_nlp_pass_overwrites_scores (2026-07 regression).
        conn.executemany(
            """INSERT INTO crosswalk_mappings
               (source_id, source_system, target_id, target_system, relationship,
                confidence_score, grade_delta, verified_by_human, notes)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id, target_id) DO UPDATE SET
                 confidence_score = excluded.confidence_score,
                 grade_delta      = excluded.grade_delta,
                 notes            = CASE
                     WHEN crosswalk_mappings.notes LIKE '%LLM score%'
                     THEN crosswalk_mappings.notes
                     ELSE excluded.notes END,
                 updated_at       = datetime('now')""",
            mappings,
        )

    return len(mappings)


def main() -> None:
    parser = argparse.ArgumentParser(description="NLP-based crosswalk generation")
    parser.add_argument("--system", default=None, help="Single system to map (default: all non-CCSS)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, dest="top_n",
                        help="Top-N hub matches per standard (default: 1)")
    parser.add_argument("--grade-delta-max", type=int, default=DEFAULT_GRADE_DELTA_MAX,
                        dest="grade_delta_max",
                        help="Max abs(grade_delta) before skipping a candidate (default: 5)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")

    if args.system:
        systems = [args.system]
    else:
        systems = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT system FROM standards WHERE system NOT IN ('ccss', 'ngss', 'ccss-ela', 'c3', 'csta') ORDER BY system"
            ).fetchall()
        ]

    print(f"Generating NLP crosswalk for {len(systems)} systems "
          f"(threshold={args.threshold}, top={args.top_n}, grade_delta_max={args.grade_delta_max})...")
    total = 0
    for system in systems:
        n = generate_crosswalk(system, conn, threshold=args.threshold,
                               top_n=args.top_n, grade_delta_max=args.grade_delta_max)
        total += n
        if n:
            print(f"  {system}: {n} mappings")

    conn.close()
    print(f"\nTotal: {total} crosswalk mappings written.")
    print("Done.")


if __name__ == "__main__":
    main()
