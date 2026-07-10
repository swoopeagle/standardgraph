#!/usr/bin/env python3
"""Phase 0: generate candidate prerequisite pairs for CCSS-math content standards.

For each TARGET standard A, a candidate prerequisite B must be at a LOWER-OR-EQUAL
grade within 3 grades (prereqs go down in grade), cosine >= 0.45, top-8 per target,
CROSS-DOMAIN allowed (unlike relate.py). Same-grade candidates are emitted in both
directions (a target A finds same-grade B; when B is the target it finds A) — the
gate decides which direction is the real prerequisite.
"""
import json
import sqlite3
import numpy as np

DB = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad/prereq_pilot.db"
FLOOR = 0.45
GRADE_WINDOW = 3
TOP_K = 6
# nlp_pass convention: HS sits right after grade 8.
GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]
gkey = lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT s.id, s.grade, s.domain, s.standard_text, e.vector, e.dimensions
        FROM standards s JOIN embeddings e ON e.standard_id = s.id
        WHERE s.system='ccss' AND s.subject='mathematics' AND s.id NOT LIKE '%.MP.%'
    """).fetchall()
    ids     = [r[0] for r in rows]
    grades  = [r[1] for r in rows]
    domains = [r[2] for r in rows]
    texts   = [r[3] for r in rows]
    dim = rows[0][5]
    mat = np.frombuffer(b"".join(r[4] for r in rows), dtype=np.float32).reshape(len(rows), dim)
    mat_u = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    S = mat_u @ mat_u.T
    np.fill_diagonal(S, -1.0)
    n = len(ids)
    print(f"CCSS-math content nodes: {n}")

    candidates = []
    for i in range(n):           # i = TARGET (the standard being reached)
        gi = gkey(grades[i])
        row = S[i]
        # eligible prereqs: STRICTLY LOWER grade within window (pilot scope —
        # same-grade intra-ordering is a documented follow-up; the learning path
        # is grade-increasing so horizontal edges add little here).
        elig = [j for j in range(n)
                if gkey(grades[j]) < gi and (gi - gkey(grades[j])) <= GRADE_WINDOW
                and row[j] >= FLOOR]
        elig.sort(key=lambda j: -row[j])
        for j in elig[:TOP_K]:
            candidates.append({
                "target_id": ids[i], "target_grade": grades[i],
                "target_domain": domains[i], "target_text": texts[i],
                "prereq_id": ids[j], "prereq_grade": grades[j],
                "prereq_domain": domains[j], "prereq_text": texts[j],
                "cosine": round(float(row[j]), 4),
                "same_grade": grades[i] == grades[j],
                "cross_domain": domains[i] != domains[j],
            })

    out = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad/prereq_candidates.json"
    json.dump(candidates, open(out, "w"), ensure_ascii=False)

    same = sum(c["same_grade"] for c in candidates)
    cross = sum(c["cross_domain"] for c in candidates)
    print(f"candidate pairs: {len(candidates)}")
    print(f"  same-grade: {same} ({100*same/len(candidates):.0f}%)")
    print(f"  cross-domain: {cross} ({100*cross/len(candidates):.0f}%)")
    import collections
    cd = collections.Counter(f"{int(c['cosine']*20)/20:.2f}" for c in candidates)
    print("  cosine distribution:")
    for b in sorted(cd): print(f"    {b}: {cd[b]}")

    # sanity: known real cross-domain prereqs present?
    print("\n  known cross-domain prereq spot-check (want these to appear):")
    def has(t_pat, p_pat):
        return any(t_pat in c["target_id"] and p_pat in c["prereq_id"] for c in candidates)
    for tp, pp, label in [("6.RP", "5.NF", "ratios <- fractions"),
                           ("5.NBT", "4.NBT", "decimals <- place value"),
                           ("6.RP", "4.NF", "ratios <- early fractions")]:
        print(f"    {label}: {'FOUND' if has(tp, pp) else 'absent'}")
    print(f"\n  written to {out}")
    conn.close()


if __name__ == "__main__":
    main()
