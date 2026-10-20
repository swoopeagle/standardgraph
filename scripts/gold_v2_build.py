"""Merge blind labels (A, B, adjudicated) into data/crosswalk_gold_v2.csv; print kappa + shift vs original labels."""
import csv, json, collections, sys
from pathlib import Path
S = Path(sys.argv[1]); R = Path(__file__).resolve().parents[1]
ld = lambda p: {k: v for i in range(5) for k, v in json.load(open(S/f"lab{p}_{i}.json")).items()}
A, B = ld("A"), ld("B"); adj = json.load(open(S/"adjudicated.json"))
def kappa(a, b):
    n = len(a); po = sum(x == y for x, y in zip(a, b))/n
    ca, cb = collections.Counter(a), collections.Counter(b)
    return po, (po - sum(ca[k]*cb[k] for k in set(ca)|set(cb))/n/n)/(1 - sum(ca[k]*cb[k] for k in set(ca)|set(cb))/n/n)
rows = list(csv.DictReader(open(R/"data/crosswalk_gold_v2_pairs.csv")))
ids = [r["pair_id"] for r in rows]
a = [A[i]["label"] for i in ids]; b = [B[i]["label"] for i in ids]
print("3-class agree/kappa", kappa(a, b)); print("strict Y-vs-not", kappa([x=="Y" for x in a], [x=="Y" for x in b]))
print("lenient N-vs-not", kappa([x!="N" for x in a], [x!="N" for x in b]))
for r in rows:
    i = r["pair_id"]; r["label_a"], r["label_b"] = A[i]["label"], B[i]["label"]
    r["adjudicated"] = int(r["label_a"] != r["label_b"])
    r["label"] = adj[i]["label"] if r["adjudicated"] else r["label_a"]
w = csv.DictWriter(open(R/"data/crosswalk_gold_v2.csv", "w", newline=""), fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
o = [r for r in rows if r["stratum"] == "orig65"]
print("orig65 shift (old -> blind):", collections.Counter((r["orig_label"], r["label"]) for r in o))
def prec(rs): n = len(rs); return f"strict {sum(r['label']=='Y' for r in rs)}/{n}={sum(r['label']=='Y' for r in rs)/n:.0%} lenient {sum(r['label']!='N' for r in rs)}/{n}={sum(r['label']!='N' for r in rs)/n:.0%}"
print("orig65 old strict", sum(r["orig_label"]=="Y" for r in o), "lenient", sum(r["orig_label"]!="N" for r in o), "; blind:", prec(o))
print("agree old vs blind", sum(r["orig_label"]==r["label"] for r in o), "/65; kappa", kappa([r["orig_label"] for r in o], [r["label"] for r in o]))
print("all", prec(rows)); print("unflagged", prec([r for r in rows if r["stratum"]!="flagged"])); print("flagged", prec([r for r in rows if r["stratum"]=="flagged"]))
