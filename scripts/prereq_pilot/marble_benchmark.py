#!/usr/bin/env python3
"""Benchmark our LLM-validated CCSS-math prereq edges against Marble's hand-curated
os-taxonomy dependency edges — an EXTERNAL, human-curated gold set.

Marble stores concept->concept prereqs (mt_ ids, hard/soft) and aligns each concept
to curriculum standard codes via topic['standards'] = ['ccss-math:5.NF.1', ...]. We
translate each Marble concept-edge into standard-level edges via the CCSS-math
alignment (cross-product of aligned codes), normalise codes to our ID space
(cluster-letter tolerant), and compare on the shared node region.

Caveats (reported, not hidden):
  - Marble is primary-focused (age ~5-11) => the shared region is ~K-6 CCSS math.
  - Marble concept<->standard is many-to-many => implied standard edges are noisier
    than direct standard-level curation; a concept aligned to N codes fans out to N^2.
  - Our edges only exist for standards that were pilot candidates (had a lower-grade
    prereq in top-6 cosine), which bounds recall of Marble edges.

Usage:
    DB_PATH ignored; pass the scratch DB path + os-taxonomy dir as constants below,
    or run:  uv run python scripts/prereq_pilot/marble_benchmark.py <db> <os-taxonomy-dir>
"""
import json
import re
import sqlite3
import sys
from collections import Counter

DB = sys.argv[1] if len(sys.argv) > 1 else "data/common_core.db"
MARBLE = sys.argv[2] if len(sys.argv) > 2 else "os-taxonomy"

_CLUSTER = re.compile(r"\.[A-Z](?=\.\d)")
def loose(x: str) -> str:
    return _CLUSTER.sub("", x.upper())


def main():
    con = sqlite3.connect(DB)

    # --- our validated edges (prerequisite rows) ---
    our = [(s, t, "hard" if c >= 0.9 else "soft") for s, t, c in con.execute(
        "SELECT source_id, target_id, confidence_score FROM standard_relationships "
        "WHERE relationship='prerequisite' AND method='llm_validated'").fetchall()]
    our_set = {(l, p): st for l, p, st in our}

    # --- loose index of our CCSS-math ids for code normalisation ---
    ids = [r[0] for r in con.execute("SELECT id FROM standards WHERE id LIKE 'CCSS.MATH%'").fetchall()]
    con.close()
    lindex = {}
    for i in ids:
        lindex.setdefault(loose(i), i)

    def to_our_id(code: str):
        return lindex.get(loose(f"CCSS.MATH.{code}"))

    # --- Marble concept -> ccss-math our-ids ---
    topics = {t["id"]: t for t in json.load(open(f"{MARBLE}/data/topics.json"))["topics"]}
    def cm_ids(t):
        out = []
        for s in t.get("standards", []):
            if isinstance(s, str) and s.startswith("ccss-math:"):
                oid = to_our_id(s.split(":", 1)[1])
                if oid:
                    out.append(oid)
        return list(dict.fromkeys(out))
    aligned = {tid: cm_ids(t) for tid, t in topics.items()}
    aligned = {tid: c for tid, c in aligned.items() if c}
    mnodes = {oid for codes in aligned.values() for oid in codes}

    # --- Marble implied standard-level edges ---
    deps = json.load(open(f"{MARBLE}/data/dependencies.json"))["dependencies"]
    marble = {}  # (learner, prereq) -> strength ('hard' wins over 'soft')
    used_edges = 0
    for d in deps:
        a = aligned.get(d["topicId"]); b = aligned.get(d["prerequisiteId"])
        if not a or not b:
            continue
        used_edges += 1
        for li in a:
            for pi in b:
                if li == pi:
                    continue
                st = d["strength"]
                if marble.get((li, pi)) != "hard":
                    marble[(li, pi)] = st

    print("=" * 64)
    print("MARBLE BENCHMARK — our validated edges vs Marble hand-curated edges")
    print("=" * 64)
    print(f"Marble concepts aligned to CCSS-math : {len(aligned)}")
    print(f"Marble CCSS-math nodes (our ids)     : {len(mnodes)}")
    print(f"Marble concept-edges w/ both ends CCSS-math: {used_edges}")
    print(f"Marble implied standard-level edges  : {len(marble)}  "
          f"({sum(1 for v in marble.values() if v=='hard')} hard / "
          f"{sum(1 for v in marble.values() if v=='soft')} soft)")
    print(f"Our validated edges (total)          : {len(our)} "
          f"({sum(1 for _,_,s in our if s=='hard')} hard / {sum(1 for _,_,s in our if s=='soft')} soft)")

    # --- shared region: our edges whose BOTH endpoints are Marble-aligned nodes ---
    our_in = [(l, p, st) for l, p, st in our if l in mnodes and p in mnodes]
    print(f"\nShared region (our edges with both endpoints in Marble's node set): {len(our_in)}")

    # Transitive closure of Marble's prereq graph: anc[L] = set of standards reachable
    # as prerequisites of L (direct or via intermediates). Controls for grain mismatch —
    # Marble may encode L<-X<-P where we encode L<-P directly.
    from collections import defaultdict
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

    def corr(edges, want_strength=None):
        pool = [e for e in edges if want_strength is None or e[2] == want_strength]
        if not pool:
            return (0, 0, 0.0)
        hit = sum(1 for l, p, _ in pool if (l, p) in marble)
        return (hit, len(pool), 100 * hit / len(pool))

    for label, st in [("our HARD", "hard"), ("our SOFT", "soft"), ("our ALL", None)]:
        hit, n, pct = corr(our_in, st)
        pool = [e for e in our_in if st is None or e[2] == st]
        contra = sum(1 for l, p, _ in pool if (p, l) in marble and (l, p) not in marble)
        # transitive corroboration: P is an ancestor of L in Marble (any path)
        thit = sum(1 for l, p, _ in pool if p in manc.get(l, set()))
        print(f"  {label:<9} direct: {hit}/{n} = {pct:.1f}%   "
              f"| transitive(ancestor): {thit}/{n} = {100*thit/n:.1f}%   "
              f"| reversed: {contra}")

    # --- strength agreement on matched edges ---
    matched = [(l, p, st) for l, p, st in our_in if (l, p) in marble]
    if matched:
        agree = sum(1 for l, p, st in matched if marble[(l, p)] == st)
        conf = Counter((st, marble[(l, p)]) for l, p, st in matched)
        print(f"\nStrength agreement on {len(matched)} matched edges: "
              f"{agree}/{len(matched)} = {100*agree/len(matched):.1f}%")
        print("  (our_strength, marble_strength):", dict(conf))

    # --- reverse: Marble edges we cover / miss (recall), within our node universe ---
    our_ids_all = set(ids)
    marble_in = [(l, p, st) for (l, p), st in marble.items() if l in our_ids_all and p in our_ids_all]
    have = sum(1 for l, p, _ in marble_in if (l, p) in our_set)
    print(f"\nRecall of Marble edges (both endpoints are real standards): "
          f"{have}/{len(marble_in)} = {100*have/len(marble_in):.1f}%" if marble_in else "n/a")

    # --- breadth: our edges entirely OUTSIDE Marble's node set (our reach beyond primary) ---
    beyond = [e for e in our if e[0] not in mnodes or e[1] not in mnodes]
    print(f"\nBreadth: our validated edges touching ≥1 node Marble doesn't cover: "
          f"{len(beyond)}/{len(our)} = {100*len(beyond)/len(our):.1f}%")

    # --- eyeball: our HARD edges Marble contradicts (reverse), if any ---
    flips = [(l, p) for l, p, st in our_in if st == "hard" and (p, l) in marble and (l, p) not in marble]
    if flips:
        print(f"\n⚠ our-HARD / Marble-reverse ({len(flips)}):")
        for l, p in flips[:10]:
            print(f"    us: {l} <- {p}   |  Marble: {p} <- {l}")


if __name__ == "__main__":
    main()
