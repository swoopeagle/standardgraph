"""Eval 2: Duplicate detection — exact and near-duplicate standards within each system."""
import hashlib
import sqlite3
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).parent.parent.parent / "data" / "common_core.db"

COSINE_THRESHOLD = 0.97   # near-duplicate threshold (very high — almost identical)
SAMPLE_MAX = 300          # max standards to check per system for near-dupes (O(n²))

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def _normalise(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", text.lower().strip())


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    total_exact = total_near = 0

    print("\n── Exact duplicate detection (normalised text hash) ─────────────────")
    systems = [r[0] for r in conn.execute(
        "SELECT system FROM standards GROUP BY system ORDER BY system"
    ).fetchall()]

    exact_offenders = []
    for system in systems:
        rows = conn.execute(
            "SELECT id, grade, standard_text FROM standards WHERE system=?", (system,)
        ).fetchall()
        # Key includes grade so cross-grade repeats (ELA CCR anchor standards,
        # science grade-band standards) don't trigger false positives.
        seen: dict[str, str] = {}
        dupes = []
        for sid, grade, text in rows:
            key = hashlib.md5((_normalise(text) + "|" + (grade or "")).encode()).hexdigest()
            if key in seen:
                dupes.append((sid, seen[key]))
            else:
                seen[key] = sid
        if dupes:
            exact_offenders.append((system, dupes))
            total_exact += len(dupes)

    if exact_offenders:
        for system, dupes in exact_offenders:
            print(f"  [{WARN}] {system}: {len(dupes)} exact duplicate(s)")
            for dup_id, orig_id in dupes[:3]:
                print(f"         {dup_id} == {orig_id}")
    else:
        print(f"  [{OK}]  No exact duplicates found across {len(systems)} systems")

    print("\n── Near-duplicate detection (embedding cosine ≥ {}) ────────────────".format(COSINE_THRESHOLD))
    near_offenders = []

    # Only check Gemma-extracted systems (not CSP API systems) — highest risk
    gemma_systems = conn.execute(
        """SELECT system, COUNT(*) n FROM standards
           WHERE system NOT IN ('ccss','ccss-ela','ngss','c3','csta')
             AND source_url NOT LIKE '%commonstandardsproject%'
             AND source_url NOT LIKE '%achieve.org%'
           GROUP BY system HAVING n > 5 ORDER BY n DESC"""
    ).fetchall()

    for system, n in gemma_systems:
        limit = min(n, SAMPLE_MAX)
        rows = conn.execute(
            """SELECT s.id, s.grade, e.vector FROM standards s
               JOIN embeddings e ON e.standard_id = s.id
               WHERE s.system=? LIMIT ?""",
            (system, limit),
        ).fetchall()
        if len(rows) < 2:
            continue

        # Group by grade so cross-grade repeats (ELA CCR anchors, science
        # grade-band standards) don't produce false near-duplicate pairs.
        from collections import defaultdict
        grade_groups: dict[str, list] = defaultdict(list)
        for sid, grade, vec_bytes in rows:
            grade_groups[grade or ""].append((sid, np.frombuffer(vec_bytes, dtype=np.float32)))

        near = []
        for grade, group in grade_groups.items():
            if len(group) < 2:
                continue
            g_ids = [g[0] for g in group]
            g_vecs = np.array([g[1] for g in group])
            norms = np.linalg.norm(g_vecs, axis=1, keepdims=True)
            g_vecs_n = g_vecs / (norms + 1e-9)
            sims = g_vecs_n @ g_vecs_n.T
            for i in range(len(g_ids)):
                for j in range(i + 1, len(g_ids)):
                    if sims[i, j] >= COSINE_THRESHOLD:
                        near.append((g_ids[i], g_ids[j], float(sims[i, j])))

        if near:
            near_offenders.append((system, near))
            total_near += len(near)

    if near_offenders:
        for system, pairs in near_offenders:
            print(f"  [{WARN}] {system}: {len(pairs)} near-duplicate pair(s)")
            for a, b, score in pairs[:2]:
                print(f"         [{score:.3f}] {a}  ≈  {b}")
    else:
        print(f"  [{OK}]  No near-duplicates (≥{COSINE_THRESHOLD}) in {len(gemma_systems)} Gemma-extracted systems")

    print(f"\n  Summary: {total_exact} same-grade exact dupes, {total_near} near-dupes")
    print("  (These reflect source-data characteristics, not ETL bugs — review manually.)\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
