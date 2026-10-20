"""World-coverage report for StandardGraph: the number that measures "how much of the world".

(a) countries covered per subject
(b) share of world K-12 pupils (primary + secondary) whose country has >=1 national/state
    curriculum in the DB  -- enrollment: data/world_enrollment.csv (World Bank WDI
    SE.PRM.ENRL + SE.SEC.ENRL, sourced from UNESCO UIS; latest year per country)
(c) crosswalk coverage: % of a system's standards with >=1 crosswalk to the subject hub
(d) crosswalk quality: precision on the hand-checked sample data/crosswalk_gold.csv

Usage:
  DB_PATH=~/.standardgraph/common_core.db uv run --directory packages/common-core \
      python ../../scripts/coverage_report.py [--json out.json]
"""
import argparse
import csv
import json
import os
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from common_core.server import _meta

ROOT = Path(__file__).resolve().parent.parent
DB = os.path.expanduser(os.getenv("DB_PATH", "~/.standardgraph/common_core.db"))
HUB = {"mathematics": "ccss", "science": "ngss", "ela": "ccss-ela", "social-studies": "c3", "cs": "csta"}
SUBJECTS = ["mathematics", "science", "ela", "social-studies", "cs", "arts", "world-languages"]
# Countries where the DB holds only part of the national system (flagged in the output, not weighted).
PARTIAL = {
    "CA": "7 of 13 provinces/territories", "GB": "England + Scotland only (no Wales/N. Ireland)",
    "IN": "NCERT only (state boards not covered)", "DE": "KMK Bildungsstandards (Laender curricula not covered)",
    "ES": "108 standards, partial grades", "CZ": "36 standards", "PE": "32 standards", "FI": "46 standards",
}


def enrollment():
    with open(ROOT / "data" / "world_enrollment.csv") as f:
        rows = list(csv.DictReader(f))
    return {r["iso2"]: (r["country"], int(r["primary"] or 0) + int(r["secondary"] or 0)) for r in rows}, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write machine-readable results here")
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    enr, enr_rows = enrollment()
    world = sum(v[1] for v in enr.values())
    yrs = [int(y) for r in enr_rows for y in (r["primary_year"], r["secondary_year"]) if y]
    old = sum(y < 2018 for y in yrs)

    # system/subject -> country
    ss = conn.execute("SELECT system, subject, COUNT(*) FROM standards GROUP BY 1,2").fetchall()
    by_subj = defaultdict(set)   # subject -> {iso2}
    any_subj = set()
    intl_only = set()
    for system, subject, n in ss:
        cc = _meta(system).get("country_code")
        if not cc:
            intl_only.add(system)
            continue
        by_subj[subject].add(cc)
        any_subj.add(cc)
    unmapped = sorted(c for c in any_subj if c not in enr)
    out = {"world_pupils": world}

    print("# StandardGraph world-coverage report\n")
    n_std = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    n_sys = conn.execute("SELECT COUNT(DISTINCT system) FROM standards").fetchone()[0]
    n_cw = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    print(f"DB: {n_std:,} standards / {n_sys} systems / {n_cw:,} crosswalks\n")

    print("## (a)+(b) Countries and K-12 pupils covered, by subject\n")
    print(f"Enrollment: World Bank WDI SE.PRM.ENRL + SE.SEC.ENRL (primary + secondary pupils; UNESCO UIS), "
          f"latest available year per country (median {int(statistics.median(yrs))}; {old} of {len(yrs)} country-levels predate 2018); world total = {world:,} pupils "
          f"across {len(enr)} countries. Source: https://data.worldbank.org/indicator/SE.PRM.ENRL , CC BY 4.0.\n")
    print("| Subject | Countries | Pupils covered | % of world K-12 pupils |\n|---|---:|---:|---:|")
    out["subjects"] = {}
    for label, cset in [("ANY SUBJECT", any_subj)] + [(s, by_subj[s]) for s in SUBJECTS]:
        pup = sum(enr[c][1] for c in cset if c in enr)
        out["subjects"][label] = {"countries": len(cset), "pupils": pup, "pct": round(100 * pup / world, 2)}
        print(f"| {label} | {len(cset)} | {pup:,} | {100 * pup / world:.1f}% |")
    print(f"\nHeadline: **{out['subjects']['mathematics']['pct']}%** of world K-12 pupils live in a country with a "
          f"math curriculum in the DB ({out['subjects']['mathematics']['countries']} countries); "
          f"**{out['subjects']['ANY SUBJECT']['pct']}%** for any subject.")
    print("Country counts treat the US (50 states + DC) as one country, and ignore depth: see partial list below. "
          f"International/exam-board systems with no country ({len(intl_only)}) are excluded.")
    if unmapped:
        print(f"Country codes with no enrollment row (excluded): {unmapped}")
    print("\nPartial coverage (counted as fully covered above, so (b) is an upper bound): "
          + "; ".join(f"{c} ({PARTIAL[c]})" for c in sorted(any_subj) if c in PARTIAL) + "\n")

    top_missing = sorted(((v[1], c, v[0]) for c, v in enr.items() if c not in by_subj["mathematics"]), reverse=True)[:15]
    print("Largest math gaps (pupils): " + ", ".join(f"{n} {p / 1e6:.0f}M" for p, c, n in top_missing) + "\n")
    out["top_math_gaps"] = [(n, p) for p, c, n in top_missing]

    print("## (c) Crosswalk coverage: standards with >=1 crosswalk to the subject hub\n")
    rows = []
    for subject, hub in HUB.items():
        for system, n, c_any, c_ok in conn.execute(
            """SELECT s.system, COUNT(*),
                      SUM(EXISTS(SELECT 1 FROM crosswalk_mappings m WHERE m.source_id=s.id AND m.target_system=?1)),
                      SUM(EXISTS(SELECT 1 FROM crosswalk_mappings m WHERE m.source_id=s.id AND m.target_system=?1
                                 AND m.flagged_for_review=0))
               FROM standards s WHERE s.subject=?2 AND s.system<>?1 GROUP BY s.system""", (hub, subject)):
            rows.append((subject, system, n, c_any, c_ok))
    print("| Subject | Systems | Standards | >=1 hub crosswalk | >=1 unflagged hub crosswalk | median system % |\n|---|---:|---:|---:|---:|---:|")
    out["crosswalk"] = {}
    for subject in HUB:
        r = [x for x in rows if x[0] == subject]
        N, A, K = sum(x[2] for x in r), sum(x[3] for x in r), sum(x[4] for x in r)
        med = statistics.median(100 * x[3] / x[2] for x in r)
        out["crosswalk"][subject] = {"systems": len(r), "standards": N, "pct_any": round(100 * A / N, 1),
                                     "pct_unflagged": round(100 * K / N, 1), "median_system_pct": round(med, 1)}
        print(f"| {subject} (hub {HUB[subject]}) | {len(r)} | {N:,} | {100 * A / N:.1f}% | {100 * K / N:.1f}% | {med:.0f}% |")
    N, A = sum(x[2] for x in rows), sum(x[3] for x in rows)
    out["crosswalk_all_pct"] = round(100 * A / N, 1)
    print(f"\nAll hub-able subjects: {100 * A / N:.1f}% of {N:,} standards have >=1 hub crosswalk "
          "(arts and world-languages have no hub; excluded). Hub-system standards excluded.")
    print("\nLowest-covered non-US systems (math/science/ela/ss/cs, >=50 standards):")
    low = sorted((x for x in rows if x[2] >= 50 and _meta(x[1]).get("country_code") not in (None, "US")),
                 key=lambda x: x[3] / x[2])[:12]
    print("| System | Subject | Standards | % with hub crosswalk |\n|---|---|---:|---:|")
    for s, sy, n, a, _ in low:
        print(f"| {sy} | {s} | {n} | {100 * a / n:.0f}% |")

    print("\n## (d) Crosswalk quality: precision on hand-checked sample\n")
    gold = ROOT / "data" / "crosswalk_gold.csv"
    if gold.exists():
        g = list(csv.DictReader(open(gold)))
        # label: Y = same/near-same concept, grade-appropriate; P = partial (related, different scope); N = wrong
        y = sum(r["label"] == "Y" for r in g)
        p = sum(r["label"] == "P" for r in g)
        n = len(g)
        print(f"Sample n={n} ({len(set(r['source_system'] for r in g))} systems: "
              f"{', '.join(sorted(set(r['source_system'] for r in g)))}), single rater (Claude, not blind to cosine score), random unflagged top-1 math->ccss edges, 13 per system, seed 20261019.")
        print(f"- strict precision (Y only): **{100 * y / n:.0f}%** ({y}/{n})")
        print(f"- lenient precision (Y + partial): **{100 * (y + p) / n:.0f}%** ({y + p}/{n})")
        by = defaultdict(lambda: [0, 0, 0])
        for r in g:
            b = by[r["source_system"]]; b[0] += 1; b[1] += r["label"] == "Y"; b[2] += r["label"] in "YP"
        for s, (t, yy, pp) in sorted(by.items()):
            print(f"  - {s}: strict {yy}/{t}, lenient {pp}/{t}")
        out["precision"] = {"n": n, "strict": round(100 * y / n, 1), "lenient": round(100 * (y + p) / n, 1)}
    else:
        print("No gold sample at data/crosswalk_gold.csv")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
