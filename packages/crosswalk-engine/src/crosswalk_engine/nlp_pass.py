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
# How many CCSS candidates to store per state standard
DEFAULT_TOP_N = 1


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


def _grade_key(g: str) -> int:
    order = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]
    try:
        return order.index(g)
    except ValueError:
        return 99


def _grade_delta(g_src: str, g_tgt: str) -> int:
    return _grade_key(g_tgt) - _grade_key(g_src)


def _hub_for_system(source_system: str, conn: sqlite3.Connection) -> str:
    """Return the hub system (ccss or ngss) based on the subject of source_system."""
    row = conn.execute(
        "SELECT subject FROM standards WHERE system=? LIMIT 1", (source_system,)
    ).fetchone()
    if row and (row[0] or "").lower() == "science":
        return "ngss"
    return "ccss"


def generate_crosswalk(
    source_system: str,
    conn: sqlite3.Connection,
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
) -> int:
    """
    Map all standards from source_system to its hub (CCSS for math, NGSS for science)
    via cosine similarity. Returns number of mappings inserted.
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
        conn.executemany(
            """INSERT OR REPLACE INTO crosswalk_mappings
               (source_id, source_system, target_id, target_system, relationship,
                confidence_score, grade_delta, verified_by_human, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            mappings,
        )

    return len(mappings)


def main() -> None:
    parser = argparse.ArgumentParser(description="NLP-based crosswalk generation")
    parser.add_argument("--system", default=None, help="Single system to map (default: all non-CCSS)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, dest="top_n",
                        help="Top-N CCSS matches per standard (default: 1)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")

    if args.system:
        systems = [args.system]
    else:
        systems = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT system FROM standards WHERE system NOT IN ('ccss', 'ngss') ORDER BY system"
            ).fetchall()
        ]

    print(f"Generating NLP crosswalk for {len(systems)} systems (threshold={args.threshold}, top={args.top_n})...")
    total = 0
    for system in systems:
        n = generate_crosswalk(system, conn, threshold=args.threshold, top_n=args.top_n)
        total += n
        if n:
            print(f"  {system}: {n} mappings")

    conn.close()
    print(f"\nTotal: {total} crosswalk mappings written.")
    print("Done.")


if __name__ == "__main__":
    main()
