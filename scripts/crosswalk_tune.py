"""Tune a keep-rule (llm score / |grade delta| / cosine) on half the gold set, report on the other half.
Usage: python scripts/crosswalk_tune.py [--target 0.90]
"""
import sys, itertools, random, statistics, sqlite3, argparse
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import crosswalk_eval as ce

ap = argparse.ArgumentParser(); ap.add_argument("--target", type=float, default=0.90); ap.add_argument("--splits", type=int, default=200)
a = ap.parse_args()
E = ce.edges(); by = {(e["src"], e["tgt"]): e for e in E}
G = ce.add_weights(ce.gold(by), E)
HUB = {"mathematics": "ccss", "science": "ngss", "ela": "ccss-ela", "social-studies": "c3", "cs": "csta"}
c = sqlite3.connect(ce.QUAL)
NSTD = sum(c.execute("select count(*) from standards where subject=? and system<>?", (s, h)).fetchone()[0] for s, h in HUB.items())
served = [e for e in E if not e["base_flag"]]

def rule(l, d, k): return lambda x: (x["llm"] or 0) >= l and abs(x["gd"]) <= d and x["cos"] >= k
GRID = list(itertools.product([0, 3, 4, 5], [99, 3, 2, 1, 0], [0.0, 0.75, 0.80, 0.85]))

def coverage(keep):
    s = {e["src"] for e in served if e["subject"] in HUB and e["tsys"] == HUB[e["subject"]] and keep(e)}
    return len(s) / NSTD

def full_curve():
    base_e, base_c = len(served), coverage(lambda e: True)
    print(f"{'llm>=':>5} {'|gd|<=':>6} {'cos>=':>5} | edges kept | std coverage | strict  lenient (all gold, weighted; in-sample)")
    for l, d, k in GRID:
        r = rule(l, d, k); p = ce.prec(G, r)
        if p["n"] < 15: continue
        print(f"{l:>5} {d:>6} {k:>5} | {sum(r(e) for e in served)/base_e:9.1%} | {coverage(r):11.1%} | {p['strict']:.0%} {p['lenient']:.0%}")
    print("baseline coverage", f"{base_c:.1%}", "of", NSTD)

def split(seed):
    rng = random.Random(seed); strata = {}
    for x in G:
        if not x["base_flag"]: strata.setdefault((x["systype"], x["label"]), []).append(x)
    A, B = [], []
    for v in strata.values():
        rng.shuffle(v); h = len(v) // 2 + (len(v) % 2 and rng.random() < .5); A += v[:h]; B += v[h:]
    return A, B

def reweight(part):  # weights recomputed within the half so each half is a self-contained sample
    pop = {}
    for e in served: pop[ce.cell(e)] = pop.get(ce.cell(e), 0) + 1
    n = {}
    for x in part: n[ce.cell(x)] = n.get(ce.cell(x), 0) + 1
    return [dict(x, w=pop[ce.cell(x)] / n[ce.cell(x)]) for x in part]

def choose(tune):
    best = None
    for l, d, k in GRID:
        p = ce.prec(tune, rule(l, d, k))
        if p["n"] < 10 or p["lenient"] < a.target: continue
        key = (p["kept"], p["strict"])
        if best is None or key > best[0]: best = (key, (l, d, k))
    return best[1] if best else None

if __name__ == "__main__":
    full_curve()
    res = []; picks = []
    for s in range(a.splits):
        A, B = split(s); A, B = reweight(A), reweight(B)
        r = choose(A)
        if r is None: continue
        picks.append(r); res.append((ce.prec(B, rule(*r)), ce.prec(B, lambda x: True)))
    print("\nheld-out over", len(res), "random 50/50 splits (rule tuned on the other half, target lenient >=", a.target, ")")
    m = lambda f: statistics.mean(f(r) for r in res)
    print("  baseline  strict %.0f%% lenient %.0f%%" % (100 * m(lambda r: r[1]["strict"]), 100 * m(lambda r: r[1]["lenient"])))
    print("  tuned     strict %.0f%% lenient %.0f%% (sd %.0f pts) edges kept %.0f%%" % (100 * m(lambda r: r[0]["strict"]), 100 * m(lambda r: r[0]["lenient"]), 100 * statistics.pstdev(r[0]["lenient"] for r in res), 100 * m(lambda r: r[0]["kept"])))
    import collections
    print("  most-picked rules (llm>=, |gd|<=, cos>=):", collections.Counter(picks).most_common(5))

def cos_only(splits=200):
    """1-D family: cosine floor in 0.70..0.86, tuned on one half (max kept s.t. lenient>=target), reported on the other."""
    import collections
    FL = [round(0.70 + 0.01 * i, 2) for i in range(17)]
    out, picks, canon = [], [], None
    for s in range(splits):
        A, B = split(s); A, B = reweight(A), reweight(B)
        ok = [(ce.prec(A, lambda x, f=f: x["cos"] >= f), f) for f in FL]
        ok = [(p["kept"], f) for p, f in ok if p["n"] >= 10 and p["lenient"] >= a.target]
        if not ok: continue
        f = max(ok)[1]; picks.append(f)
        r = (ce.prec(B, lambda x: x["cos"] >= f), ce.prec(B, lambda x: True), f); out.append(r)
        if s == 0: canon = r
    mean = lambda k, i: 100 * statistics.mean(r[i][k] for r in out)
    print("\n1-D cosine floor, %d splits: chosen floor median %.2f (IQR %.2f-%.2f)" % (len(out), statistics.median(picks), *statistics.quantiles(picks, n=4)[::2]))
    print("  held-out baseline strict %.0f%% lenient %.0f%% | tuned strict %.0f%% lenient %.0f%% edges kept %.0f%%" % (mean("strict", 1), mean("lenient", 1), mean("strict", 0), mean("lenient", 0), mean("kept", 0)))
    d = sorted(r[0]["lenient"] - r[1]["lenient"] for r in out); ds = sorted(r[0]["strict"] - r[1]["strict"] for r in out)
    print("  lenient gain 5th-95th pct over splits: %.0f..%.0f pts; strict gain %.0f..%.0f pts" % (100 * d[len(d) // 20], 100 * d[-len(d) // 20], 100 * ds[len(ds) // 20], 100 * ds[-len(ds) // 20]))
    print("  canonical split (seed 0): floor %.2f; held-out baseline strict %.0f%% lenient %.0f%% -> strict %.0f%% lenient %.0f%%, edges kept %.0f%%" % (canon[2], 100 * canon[1]["strict"], 100 * canon[1]["lenient"], 100 * canon[0]["strict"], 100 * canon[0]["lenient"], 100 * canon[0]["kept"]))
    cov = {f: coverage(lambda e, f=f: e["cos"] >= f) for f in FL}
    print("  coverage by floor:", {f: f"{v:.1%}" for f, v in cov.items() if f in (0.70, 0.72, 0.74, 0.75, 0.76, 0.78, 0.80)})

if __name__ == "__main__":
    cos_only(a.splits)
