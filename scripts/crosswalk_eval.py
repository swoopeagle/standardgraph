"""Crosswalk-quality eval: features for gold-v2 pairs + population weights + rule evaluation.

Population = edges NOT flagged in the baseline DB (what the server serves by default).
Weights: each gold pair stands for pop(cell)/n_gold(cell), cell=(subject, systype, llm score), so the
deliberately balanced sample is re-weighted to the real edge mix.
"""
import csv, os, re, sqlite3, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BASE = os.path.expanduser("~/.standardgraph/common_core_world-coverage.db")   # pre-change state
QUAL = os.path.expanduser("~/.standardgraph/common_core_quality.db")           # + France scores

def systype(s):
    if s.startswith("ap-"): return "ap"
    if re.fullmatch(r"[a-z]{2}(-(sci|ela|ss|cs))?", s): return "us_state"
    return "intl"

def llm(notes):
    m = re.match(r"\[(?:LLM|exact-match) score (\d)|\[exact-match (\d)", notes or "")
    return int(m.group(1) or m.group(2)) if m else None

_W = re.compile(r"[a-z]{4,}")
def toks(t): return set(_W.findall((t or "").lower()))

def edges(conn_path=QUAL, base_path=BASE):
    """All edges with features; `base_flag` = flagged in the pre-change DB."""
    b = sqlite3.connect(base_path)
    flag0 = {(r[0], r[1]): r[2] for r in b.execute("select source_id,target_id,flagged_for_review from crosswalk_mappings")}
    c = sqlite3.connect(conn_path)
    out = []
    for r in c.execute("""select cm.source_id,cm.target_id,cm.source_system,cm.confidence_score,cm.grade_delta,cm.notes,
        s.subject,s.standard_text,t.standard_text,s.grade,t.grade,cm.target_system from crosswalk_mappings cm
        join standards s on s.id=cm.source_id join standards t on t.id=cm.target_id"""):
        out.append(dict(src=r[0], tgt=r[1], system=r[2], cos=r[3], gd=r[4], llm=llm(r[5]), subject=r[6], systype=systype(r[2]),
                        stext=r[7], ttext=r[8], base_flag=flag0[(r[0], r[1])], sgrade=r[9], tgrade=r[10], tsys=r[11]))
    return out

def gold(by_pair):
    rows = list(csv.DictReader(open(ROOT / "data/crosswalk_gold_v2.csv")))
    g = []
    for r in rows:
        e = by_pair[(r["source_id"], r["target_id"])]
        g.append(dict(e, label=r["label"], Y=r["label"] == "Y", U=r["label"] != "N", stratum=r["stratum"], pair_id=r["pair_id"]))
    return g

def cell(e): return (e["subject"], e["systype"], e["llm"])

def add_weights(g, all_edges):
    pop = collections.Counter(cell(e) for e in all_edges if not e["base_flag"])
    n = collections.Counter(cell(x) for x in g if not x["base_flag"])
    for x in g: x["w"] = pop[cell(x)] / n[cell(x)] if not x["base_flag"] else 0.0
    return g

def prec(g, keep=lambda x: True, weighted=True):
    k = [x for x in g if not x["base_flag"] and keep(x)]
    if not k: return dict(n=0, strict=float("nan"), lenient=float("nan"), kept=0.0)
    w = [x["w"] if weighted else 1 for x in k]; W = sum(w)
    tot = sum(x["w"] if weighted else 1 for x in g if not x["base_flag"])
    return dict(n=len(k), strict=sum(a * x["Y"] for a, x in zip(w, k)) / W, lenient=sum(a * x["U"] for a, x in zip(w, k)) / W, kept=W / tot)
