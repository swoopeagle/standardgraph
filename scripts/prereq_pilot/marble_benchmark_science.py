#!/usr/bin/env python3
"""Science (NGSS) opportunity-sizing study vs Marble os-taxonomy.

IMPORTANT — this is NOT the same kind of check as marble_benchmark.py. We have no
LLM-validated science prerequisite graph (the pilot was CCSS-math only). This script
compares our EXISTING grade_heuristic NGSS edges (relate.py's grade-adjacency
heuristic, same one whose CCSS-math weaknesses motivated the math pilot) against
Marble's hand-curated NGSS edges. Purpose: size the opportunity for a future science
prereq-validation pilot, the same way relate.py's 0% cross-domain rate motivated this
one for math — not to validate anything we've built for science.

Marble's NGSS curricula (ngss-k5, ngss-ms) are codesOnlySources: no topic text,
codes only. Codes already match our ID scheme almost exactly (Marble '1-ESS1-1' <->
our 'NGSS.1-ESS1-1'), so no cluster-letter normalisation is needed here.

Usage: uv run python scripts/prereq_pilot/marble_benchmark_science.py <db> <os-taxonomy-dir>
"""
import json
import sqlite3
import sys
from collections import defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "data/common_core.db"
MARBLE = sys.argv[2] if len(sys.argv) > 2 else "os-taxonomy"
SLUGS = ("ngss-k5", "ngss-ms")


def main():
    con = sqlite3.connect(DB)
    ids = {r[0] for r in con.execute("SELECT id FROM standards WHERE system='ngss'").fetchall()}
    print(f"our NGSS standards: {len(ids)}")

    def to_our_id(code: str):
        cand = f"NGSS.{code}"
        return cand if cand in ids else None

    # our existing edges (relate.py grade_heuristic — no llm_validated exists for science)
    our = [(s, t) for s, t in con.execute(
        "SELECT source_id, target_id FROM standard_relationships "
        "WHERE relationship='prerequisite' AND method='grade_heuristic' "
        "AND source_id LIKE 'NGSS%'").fetchall()]
    our_set = set(our)
    print(f"our grade_heuristic NGSS prerequisite edges: {len(our)}")
    domains = {r[0]: r[1] for r in con.execute(
        "SELECT id, domain FROM standards WHERE system='ngss'").fetchall()}
    xdom = sum(1 for s, t in our if domains.get(s) and domains.get(t) and domains[s] != domains[t])
    print(f"  cross-domain share: {xdom}/{len(our)} = {100*xdom/len(our):.1f}%" if our else "  n/a")
    con.close()

    # Marble concept -> our NGSS ids, across both ngss-k5 and ngss-ms
    topics = {t["id"]: t for t in json.load(open(f"{MARBLE}/data/topics.json"))["topics"]}
    def science_ids(t):
        out = []
        for s in t.get("standards", []):
            if isinstance(s, str) and any(s.startswith(f"{slug}:") for slug in SLUGS):
                code = s.split(":", 1)[1]
                oid = to_our_id(code)
                if oid:
                    out.append(oid)
        return list(dict.fromkeys(out))
    aligned = {tid: science_ids(t) for tid, t in topics.items()}
    aligned = {tid: c for tid, c in aligned.items() if c}
    mnodes = {oid for codes in aligned.values() for oid in codes}
    print(f"\nMarble concepts aligned to NGSS (k5+ms): {len(aligned)}")
    print(f"Marble NGSS nodes (our ids)             : {len(mnodes)}")

    deps = json.load(open(f"{MARBLE}/data/dependencies.json"))["dependencies"]
    marble = {}
    used = 0
    for d in deps:
        a = aligned.get(d["topicId"]); b = aligned.get(d["prerequisiteId"])
        if not a or not b:
            continue
        used += 1
        for li in a:
            for pi in b:
                if li == pi:
                    continue
                if marble.get((li, pi)) != "hard":
                    marble[(li, pi)] = d["strength"]
    print(f"Marble concept-edges w/ both ends NGSS  : {used}")
    print(f"Marble implied standard-level NGSS edges: {len(marble)} "
          f"({sum(1 for v in marble.values() if v=='hard')} hard / "
          f"{sum(1 for v in marble.values() if v=='soft')} soft)")

    # transitive closure for corroboration
    madj = defaultdict(set)
    for (l, p) in marble:
        madj[l].add(p)
    def ancestors(l):
        seen, stack = set(), list(madj.get(l, ()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(madj.get(n, ()))
        return seen
    manc = {l: ancestors(l) for l in madj}

    our_in = [(s, t) for s, t in our if s in mnodes and t in mnodes]
    print(f"\nShared region (our edges with both endpoints in Marble's node set): {len(our_in)}")
    if our_in:
        hit = sum(1 for l, p in our_in if (l, p) in marble)
        thit = sum(1 for l, p in our_in if p in manc.get(l, set()))
        contra = sum(1 for l, p in our_in if (p, l) in marble and (l, p) not in marble)
        print(f"  direct: {hit}/{len(our_in)} = {100*hit/len(our_in):.1f}%   "
              f"| transitive: {thit}/{len(our_in)} = {100*thit/len(our_in):.1f}%   "
              f"| reversed: {contra}")
    else:
        print("  (no overlap — grade_heuristic same-domain-only heuristic likely has near-zero"
              " overlap with Marble's cross-domain science concept graph)")

    marble_in = [(l, p) for (l, p) in marble if l in ids and p in ids]
    have = sum(1 for l, p in marble_in if (l, p) in our_set)
    print(f"\nRecall of Marble NGSS edges by our grade_heuristic graph: "
          f"{have}/{len(marble_in)} = {100*have/len(marble_in):.1f}%" if marble_in else "n/a")

    # cross-domain share of Marble's implied edges — the opportunity signal
    mxd = sum(1 for l, p in marble if domains.get(l) and domains.get(p) and domains[l] != domains[p])
    print(f"Marble's implied NGSS edges are cross-domain: {mxd}/{len(marble)} = "
          f"{100*mxd/len(marble):.1f}%  (our grade_heuristic graph is structurally 0%)")


if __name__ == "__main__":
    main()
