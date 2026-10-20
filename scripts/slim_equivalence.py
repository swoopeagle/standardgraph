"""Record/replay ~60 fixed MCP tool calls so a slimmed DB can be diffed against its source.

  uv run --directory packages/common-core python ../../scripts/slim_equivalence.py gen  SRC.db calls.json
  DB_PATH=X.db uv run --directory packages/common-core python ../../scripts/slim_equivalence.py run calls.json out.json
Query embeddings come from real Ollama once, then are cached next to calls.json so both runs see identical vectors.
"""
import json, os, random, sqlite3, sys, time
from pathlib import Path


def gen(src, out):
    db = sqlite3.connect(f"file:{os.path.expanduser(src)}?mode=ro", uri=True)
    r = random.Random(0)
    q = lambda s, *a: db.execute(s, a).fetchall()
    calls = []
    hubs = ["ccss", "ngss", "ccss-ela", "c3", "csta"]
    systems = [s for (s,) in q("SELECT system FROM standards GROUP BY system HAVING COUNT(*)>200")]
    pick = lambda sql, n, *a: r.sample([x[0] for x in q(sql, *a)], n)
    for sy in hubs + r.sample(systems, 7):  # lookups across systems
        sid = pick("SELECT id FROM standards WHERE system=?", 1, sy)[0]
        calls.append(["lookup_standard", dict(standard_id=sid, system=sy)])
    for sid in pick("SELECT source_id FROM standard_relationships WHERE method='llm_validated' AND relationship='prerequisite'", 6):
        calls.append(["lookup_standard", dict(standard_id=sid, system=sid.split(".")[0].lower().replace("_", "-"), prefer_validated=False)])
        calls.append(["lookup_standard", dict(standard_id=sid, system=sid.split(".")[0].lower().replace("_", "-"))])
    for c in ["fractions", "linear equations", "place value", "ratios", "area", "geometric transformations"]:
        calls.append(["get_progression", dict(concept=c, system="ccss")])
    for c, sy in [("fractions", "sg-moe"), ("algebra", "cambridge"), ("fractions", "tx")]:
        calls.append(["get_progression", dict(concept=c, system=sy, grade_start=3, grade_end=8)])
    lp = [x[0] for x in q("SELECT source_id FROM standard_relationships WHERE method='llm_validated' AND relationship='prerequisite' GROUP BY source_id ORDER BY COUNT(*) DESC LIMIT 60")]
    for sid in r.sample(lp, 8):
        calls.append(["get_learning_path", dict(target=sid, system="ccss")])
    for sid in r.sample(lp, 3):
        calls.append(["get_learning_path", dict(target=sid, system="ccss", include_soft=True, max_depth=3)])
    anc = q("SELECT source_id, target_id FROM standard_relationships WHERE method='llm_validated' AND relationship='successor' LIMIT 3000")
    for a, b in r.sample(anc, 2):  # from_standard path (uses successor edges)
        calls.append(["get_learning_path", dict(target=b, system="ccss", from_standard=a)])
    for fs, ts in [("ccss", "sg-moe"), ("tx", "ccss"), ("ca-on", "uk-nc"), ("ngss", "ca-sci"), ("ccss-ela", "tx-ela"), ("sg-moe", "ccss"), ("au-acara", "ccss"), ("ccss", "ngss")]:
        sid = pick("SELECT id FROM standards WHERE system=?", 1, fs)[0]
        calls.append(["map_standard", dict(standard_id=sid, from_system=fs, to_system=ts)])
    for fs, ts in [("ccss", "jp-mext"), ("ap-calc-ab", "ccss"), ("ccss", "ca-on"), ("c3", "tx-ss"), ("csta", "fl-cs"), ("tx", "cambridge"), ("ngss", "ap-bio")]:
        sid = pick("SELECT id FROM standards WHERE system=?", 1, fs)[0]
        calls.append(["map_standard", dict(standard_id=sid, from_system=fs, to_system=ts, confidence_threshold=0.95, include_flagged=True)])
    for qu, kw in [("adding fractions with unlike denominators", {}), ("photosynthesis", dict(subject="science")), ("argumentative writing", dict(subject="ela", grade="8")),
                   ("causes of the american revolution", dict(subject="social-studies")), ("loops and conditionals", dict(subject="cs")),
                   ("proportional reasoning", dict(system="sg-moe", limit=10)), ("linear equations", dict(system="tx", grade="6-8")),
                   ("ecosystems", {}), ("fractions", dict(subject="mathematics", domain="geometry")), ("drawing", dict(subject="arts")),
                   ("greeting people", dict(subject="world-languages")), ("pythagorean theorem", dict(system="cambridge", limit=20)),
                   ("derivatives", dict(system="ap-calc-ab")), ("poetry analysis", dict(system="ca-on", limit=7)), ("heat transfer", dict(system="ngss", grade="HS"))]:
        calls.append(["search_standards", dict(query=qu, **kw)])
    calls += [["list_systems", {}], ["list_systems", dict(subject="science")], ["list_systems", dict(region="Europe")]]
    json.dump(calls, open(out, "w"), indent=1)
    print(len(calls), "calls")


def run(calls_path, out_path):
    from common_core import server
    cache_p = Path(calls_path).with_suffix(".qvec.json")
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    real = server._embed_query
    import numpy as np

    def cached(text):
        if text not in cache:
            cache[text] = real(text).tolist()
        return np.array(cache[text], dtype=np.float32)

    server._embed_query = cached
    res, timing = [], []
    for name, args in json.load(open(calls_path)):
        t = time.perf_counter()
        try:
            out = getattr(server, name)(**args)
        except Exception as e:
            out = f"EXC {type(e).__name__}: {e}"
        timing.append((name, time.perf_counter() - t))
        res.append([name, args, out])
    cache_p.write_text(json.dumps(cache))
    json.dump(dict(results=res, timing=timing), open(out_path, "w"), indent=1)
    print("ran", len(res), "calls;", sum(t for _, t in timing), "s")


if __name__ == "__main__":
    {"gen": gen, "run": run}[sys.argv[1]](*sys.argv[2:])
