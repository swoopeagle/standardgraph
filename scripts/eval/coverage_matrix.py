"""Eval 5: Coverage matrix — verify all 256 systems are semantically reachable.

For each curriculum system, embeds a subject-appropriate query and checks that
at least one standard scores above the reachability threshold (cosine ≥ 0.45).
Systems that fail are likely missing embeddings or too sparse to be useful.

Efficient: embeds 5 subject queries, loads per-system embeddings (not all 146k at once).

Usage: uv run python scripts/eval/coverage_matrix.py
"""
import sqlite3
import sys
from pathlib import Path

import httpx
import numpy as np

ROOT        = Path(__file__).parent.parent.parent
DB_PATH     = ROOT / "data" / "common_core.db"
EMBED_URL   = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

REACH_THRESHOLD = 0.45  # min cosine for a system to be considered reachable

SUBJECT_QUERIES = {
    "math":    "number operations fractions algebra geometry measurement",
    "science": "matter energy forces ecosystems scientific phenomena",
    "ela":     "reading comprehension writing speaking listening vocabulary",
    "ss":      "civics history geography economics government",
    "cs":      "programming algorithms data structures computational thinking",
}

_SCIENCE_SYSTEMS = {
    "ngss", "ap-bio", "ap-chem", "ap-phys-1", "ap-phys-2",
    "ap-phys-c-mech", "ap-phys-c-em", "ap-env",
}
_ELA_SYSTEMS = {"ccss-ela"}
_SS_SYSTEMS  = {"c3"}
_CS_SYSTEMS  = {"csta"}

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def _classify(system: str) -> str:
    if system in _SCIENCE_SYSTEMS or system.endswith("-sci"):
        return "science"
    if system in _ELA_SYSTEMS or system.endswith("-ela"):
        return "ela"
    if system in _SS_SYSTEMS or system.endswith("-ss"):
        return "ss"
    if system in _CS_SYSTEMS or system.endswith("-cs"):
        return "cs"
    return "math"


def _embed_batch(texts: list[str]) -> list[np.ndarray]:
    resp = httpx.post(
        EMBED_URL,
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    return [np.array(v, dtype=np.float32) for v in resp.json()["embeddings"]]


def _max_cosine(qvec: np.ndarray, vecs: np.ndarray) -> float:
    if len(vecs) == 0:
        return 0.0
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    scores = (vecs / norms) @ q
    return float(scores.max())


def main() -> int:
    conn = sqlite3.connect(str(DB_PATH))

    # All systems and their standard counts
    sys_rows = conn.execute(
        "SELECT system, COUNT(*) AS n FROM standards GROUP BY system ORDER BY system"
    ).fetchall()
    systems = [(r[0], r[1]) for r in sys_rows]
    conn.close()

    print(f"\n── Coverage matrix ({len(systems)} systems) ─────────────────────────────────")

    # Embed all 5 subject queries in one batch
    subjects = list(SUBJECT_QUERIES.keys())
    query_texts = [SUBJECT_QUERIES[s] for s in subjects]
    try:
        query_vecs = {subjects[i]: v for i, v in enumerate(_embed_batch(query_texts))}
    except Exception as e:
        print(f"  ERROR: could not embed subject queries — {e}")
        return 1

    no_embed: list[str] = []
    low_reach: list[tuple[str, str, float, int]] = []
    ok_count = 0

    for system, n_standards in systems:
        subject = _classify(system)
        qvec = query_vecs[subject]

        # Load only this system's embeddings
        db2 = sqlite3.connect(str(DB_PATH))
        rows = db2.execute(
            "SELECT e.vector FROM embeddings e "
            "JOIN standards s ON s.id=e.standard_id WHERE s.system=?",
            (system,),
        ).fetchall()
        db2.close()

        n_embedded = len(rows)
        if n_embedded == 0:
            no_embed.append(system)
            print(f"  [{FAIL}] {system:<25} ({n_standards:>4} stds,   0 embedded) — NO EMBEDDINGS")
            continue

        vecs = np.array([np.frombuffer(r[0], dtype=np.float32) for r in rows])
        max_score = _max_cosine(qvec, vecs)

        if max_score < REACH_THRESHOLD:
            low_reach.append((system, subject, max_score, n_standards))
            tag = WARN
        else:
            ok_count += 1
            tag = OK

        # Only print failures (keep output compact for 256 systems)
        if max_score < REACH_THRESHOLD:
            print(f"  [{tag}] {system:<25} ({n_standards:>4} stds, {n_embedded:>4} emb) "
                  f"subject={subject:<8} max_cos={max_score:.3f}")

    total = len(systems)
    print(f"\n  Summary: {ok_count}/{total} systems reachable (cosine ≥ {REACH_THRESHOLD})")

    if no_embed:
        print(f"\n  No embeddings ({len(no_embed)} systems):")
        for s in no_embed:
            print(f"    • {s}")

    if low_reach:
        print(f"\n  Low semantic reach ({len(low_reach)} systems, cosine < {REACH_THRESHOLD}):")
        for s, subj, score, n in sorted(low_reach, key=lambda x: x[2]):
            print(f"    • {s:<25} subject={subj:<8} max_cos={score:.3f}  ({n} standards)")

    print()
    failed = len(no_embed) + len(low_reach)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
