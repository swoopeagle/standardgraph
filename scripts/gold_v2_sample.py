"""Draw the stratified gold-v2 sample + write the BLIND labeling file.

Strata: subject x system type (us_state / ap / intl), spread evenly over LLM score
(2..5; flagged edges are their own stratum), random cosine within. Seeded.
Writes data/crosswalk_gold_v2_pairs.csv (metadata, NOT shown to labelers) and
<out>/blind.json (id, source/target text+grade+system name only - no scores).
Usage: DB_PATH=... python scripts/gold_v2_sample.py <outdir>
"""
import zlib, csv, json, os, random, re, sqlite3, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = os.path.expanduser(os.environ["DB_PATH"])
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
# cell -> n unflagged pairs
CELLS = {("mathematics","us_state"):14, ("mathematics","intl"):24, ("mathematics","ap"):6,
         ("science","us_state"):16, ("science","ap"):6, ("ela","us_state"):16, ("ela","ap"):6,
         ("social-studies","us_state"):16, ("social-studies","ap"):6, ("cs","us_state"):10,
         ("science","intl"):4, ("ela","intl"):4}
N_FLAGGED = 16

def systype(s):
    if s.startswith("ap-"): return "ap"
    if re.fullmatch(r"[a-z]{2}(-(sci|ela|ss|cs))?", s) or s in ("dc",): return "us_state"
    return "intl"

def llm(notes):
    m = re.match(r"\[(?:LLM|exact-match) score (\d)|\[exact-match (\d)", notes or "")
    return int(m.group(1) or m.group(2)) if m else None

c = sqlite3.connect(DB)
done = {(r["source_id"], r["target_id"]) for r in csv.DictReader(open(ROOT/"data/crosswalk_gold.csv"))}
rows = c.execute("""select cm.id,cm.source_id,cm.target_id,cm.source_system,cm.target_system,cm.confidence_score,
  cm.grade_delta,cm.notes,cm.flagged_for_review,s.subject,s.standard_text,s.grade,s.domain,t.standard_text,t.grade,t.domain
  from crosswalk_mappings cm join standards s on s.id=cm.source_id join standards t on t.id=cm.target_id""").fetchall()
rng = random.Random(20261019)
pools = collections.defaultdict(lambda: collections.defaultdict(list))
flagged = []
for r in rows:
    if (r[1], r[2]) in done or llm(r[7]) is None: continue
    if r[8]: flagged.append(r); continue
    pools[(r[9], systype(r[3]))][llm(r[7])].append(r)
pick = []
for cell, n in CELLS.items():
    b = pools[cell]; keys = sorted(b)
    for k in keys: rng.shuffle(b[k])
    i = 0
    while n and any(b.values()):
        k = keys[i % len(keys)]; i += 1
        if b[k]: pick.append((r:=b[k].pop(), "unflagged")); n -= 1
rng.shuffle(flagged)
by = collections.defaultdict(list)
for r in flagged: by[r[9]].append(r)
subs = list(by); i = 0
while len([p for p in pick if p[1]=="flagged"]) < N_FLAGGED:
    s = subs[i % len(subs)]; i += 1
    if by[s]: pick.append((by[s].pop(), "flagged"))
rng.shuffle(pick)
meta, blind = [], []
for k, (r, st) in enumerate(pick):
    pid = f"g{k:03d}"
    meta.append(dict(pair_id=pid, source_id=r[1], target_id=r[2], source_system=r[3], target_system=r[4], subject=r[9],
                     systype=systype(r[3]), cosine=round(r[5],4), llm_score=llm(r[7]), grade_delta=r[6], stratum=st))
    blind.append(dict(id=pid, subject=r[9], source_system=r[3], source_grade=r[11], source_domain=r[12], source_text=r[10],
                      target_system=r[4], target_grade=r[14], target_domain=r[15], target_text=r[13]))
for j, r in enumerate(csv.DictReader(open(ROOT/"data/crosswalk_gold.csv"))):   # original 65, re-labelled blind
    x = c.execute("""select cm.source_system,cm.target_system,cm.confidence_score,cm.grade_delta,cm.notes,s.subject,s.standard_text,s.grade,s.domain,t.standard_text,t.grade,t.domain
      from crosswalk_mappings cm join standards s on s.id=cm.source_id join standards t on t.id=cm.target_id where cm.source_id=? and cm.target_id=?""",
      (r["source_id"], r["target_id"])).fetchone()
    pid = f"o{j:03d}"
    meta.append(dict(pair_id=pid, source_id=r["source_id"], target_id=r["target_id"], source_system=x[0], target_system=x[1], subject=x[5],
                     systype=systype(x[0]), cosine=round(x[2],4), llm_score=llm(x[4]), grade_delta=x[3], stratum="orig65", orig_label=r["label"]))
    blind.append(dict(id=pid, subject=x[5], source_system=x[0], source_grade=x[7], source_domain=x[8], source_text=x[6],
                      target_system=x[1], target_grade=x[10], target_domain=x[11], target_text=x[9]))
rng.shuffle(blind)
(OUT/"blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False))
w = csv.DictWriter(open(ROOT/"data/crosswalk_gold_v2_pairs.csv","w",newline=""), fieldnames=list(meta[0].keys())|{"orig_label"} if False else ["pair_id","source_id","target_id","source_system","target_system","subject","systype","cosine","llm_score","grade_delta","stratum","orig_label"])
w.writeheader(); w.writerows(meta)
print(len(meta), collections.Counter(m["stratum"] for m in meta), collections.Counter((m["subject"],m["systype"]) for m in meta))
