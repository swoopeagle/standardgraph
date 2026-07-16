"""
Family-structured direct crosswalk: map standards DIRECTLY between sibling systems
within a curriculum family, instead of only through the CCSS hub.

The main crosswalk graph is a star (every system -> CCSS). For systems that share a
curriculum lineage (e.g. the British Commonwealth family), routing A -> CCSS -> B
loses fidelity: the two curricula often match each other more closely than either
matches CCSS. This pass materialises the direct A <-> B edges (both directions) for
every ordered pair within a family, using the same cosine + grade-delta logic as
nlp_pass, tagged `direct_family` in notes so they are identifiable and reversible.

Run:
    uv run python -m crosswalk_engine.direct_family --family commonwealth
"""
import argparse
import sqlite3
import numpy as np

from shared.config import DB_PATH
from crosswalk_engine.nlp_pass import _grade_delta

FAMILIES = {
    "commonwealth": [
        "uk-nc", "au-acara", "nz-moe", "sg-moe", "in-ncert", "ke-kicd", "tz-tie",
        "ug-ncdc", "gh-nacca", "ng-nerdc", "za-caps", "zm-cdc", "na-nied",
    ],
}

DEFAULT_THRESHOLD = 0.70
DEFAULT_GRADE_DELTA_MAX = 5


def _load(conn, system):
    rows = conn.execute(
        """SELECT e.standard_id, e.vector, s.grade
           FROM embeddings e JOIN standards s ON s.id = e.standard_id
           WHERE s.system = ? AND s.subject = 'mathematics'""",
        (system,),
    ).fetchall()
    if not rows:
        return None
    ids = [r[0] for r in rows]
    grades = [r[2] for r in rows]
    M = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), 768)
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    return ids, grades, M


def build_family(family, conn, threshold=DEFAULT_THRESHOLD, grade_delta_max=DEFAULT_GRADE_DELTA_MAX):
    systems = FAMILIES[family]
    data = {s: _load(conn, s) for s in systems}
    data = {s: d for s, d in data.items() if d is not None}
    systems = list(data)
    print(f"Family '{family}': {len(systems)} systems loaded")

    rows_out = []
    for A in systems:
        a_ids, a_gr, a_M = data[A]
        for B in systems:
            if A == B:
                continue
            b_ids, b_gr, b_M = data[B]
            S = a_M @ b_M.T                      # (nA, nB) cosine
            best_j = S.argmax(axis=1)
            best_s = S[np.arange(S.shape[0]), best_j]
            for i, j in enumerate(best_j):
                score = float(best_s[i])
                if score < threshold:
                    continue
                delta = _grade_delta(a_gr[i], b_gr[j])
                if abs(delta) > grade_delta_max:
                    continue
                rows_out.append((
                    a_ids[i], A, b_ids[j], B, "equivalent",
                    round(score, 4), delta, 0, f"direct_family cosine={score:.4f}",
                ))
    with conn:
        conn.executemany(
            """INSERT INTO crosswalk_mappings
               (source_id, source_system, target_id, target_system, relationship,
                confidence_score, grade_delta, verified_by_human, notes)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id, target_id) DO UPDATE SET
                 confidence_score = excluded.confidence_score,
                 grade_delta      = excluded.grade_delta,
                 notes            = CASE WHEN crosswalk_mappings.notes LIKE '%LLM score%'
                                    THEN crosswalk_mappings.notes ELSE excluded.notes END,
                 updated_at       = datetime('now')""",
            rows_out,
        )
    return len(rows_out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--family", default="commonwealth", choices=list(FAMILIES))
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = p.parse_args()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    n = build_family(args.family, conn, threshold=args.threshold)
    print(f"Direct-family edges written: {n:,}")
    conn.close()


if __name__ == "__main__":
    main()
