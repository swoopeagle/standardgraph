#!/usr/bin/env python3
"""Phase 6 (hardening) — promote SOFT edges to HARD where independent sources agree.

Criteria: a Claude-SOFT edge is promoted iff at least one of
  (a) qwen (blind, gold-validated-prompt, 284-pair overlap sample) labels it HARD, or
  (b) Marble os-taxonomy has the identical directed pair as a 'hard' edge
and NEITHER independent source contradicts it (qwen=NONE, or Marble has the pair
reversed). This is a small, conservative promotion — most SOFT edges have no
independent check at all and are left untouched (no confidence manufactured from
nothing). See docs/prereq_graph_pilot_report.md hardening addendum for the numbers.

Promoted rows: confidence_score 0.5 -> 0.9, notes rewritten with an explicit
'promoted_soft_to_hard' marker + which source(s) confirmed it, method stays
'llm_validated'. Both the prerequisite row and its mirrored successor row are
updated together.

Usage: uv run python scripts/prereq_pilot/prereq_promote.py <db>
"""
import json
import re
import sqlite3
import sys

SCRATCH = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad"
DB = sys.argv[1] if len(sys.argv) > 1 else f"{SCRATCH}/prereq_pilot.db"
MARBLE = f"{SCRATCH}/os-taxonomy"

_CLUSTER = re.compile(r"\.[A-Z](?=\.\d)")
def loose(x: str) -> str:
    return _CLUSTER.sub("", x.upper())


def build_promotion_set(con: sqlite3.Connection):
    claude = {}
    for line in open(f"{SCRATCH}/claude_labels.jsonl"):
        line = line.strip()
        if line:
            o = json.loads(line)
            claude[o["key"]] = o
    qwen = {}
    for line in open(f"{SCRATCH}/qwen_labels.jsonl"):
        line = line.strip()
        if line:
            o = json.loads(line)
            qwen[o["key"]] = o["label"]

    soft_keys = [k for k, o in claude.items() if o["label"] == "SOFT"]
    qwen_hard = {k for k in soft_keys if qwen.get(k) == "HARD"}
    qwen_none = {k for k in soft_keys if qwen.get(k) == "NONE"}

    ids = [r[0] for r in con.execute("SELECT id FROM standards WHERE id LIKE 'CCSS.MATH%'").fetchall()]
    lindex = {}
    for i in ids:
        lindex.setdefault(loose(i), i)
    def to_our_id(code):
        return lindex.get(loose(f"CCSS.MATH.{code}"))

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

    deps = json.load(open(f"{MARBLE}/data/dependencies.json"))["dependencies"]
    marble = {}
    for d in deps:
        a = aligned.get(d["topicId"]); b = aligned.get(d["prerequisiteId"])
        if not a or not b:
            continue
        for li in a:
            for pi in b:
                if li == pi:
                    continue
                if marble.get((li, pi)) != "hard":
                    marble[(li, pi)] = d["strength"]

    marble_hard, marble_reversed = set(), set()
    for k in soft_keys:
        tgt, prereq = k.split("|", 1)
        if marble.get((tgt, prereq)) == "hard":
            marble_hard.add(k)
        elif (prereq, tgt) in marble and (tgt, prereq) not in marble:
            marble_reversed.add(k)

    confirmed = qwen_hard | marble_hard
    contradicted = qwen_none | marble_reversed
    promote = confirmed - contradicted

    sources = {}
    for k in promote:
        s = []
        if k in qwen_hard:
            s.append("qwen")
        if k in marble_hard:
            s.append("marble")
        sources[k] = s
    return promote, sources, claude


def main():
    con = sqlite3.connect(DB)
    promote, sources, claude = build_promotion_set(con)
    print(f"promoting {len(promote)} SOFT->HARD edges")

    cur = con.cursor()
    n = 0
    for k in sorted(promote):
        tgt, prereq = k.split("|", 1)
        o = claude[k]
        src = "+".join(sources[k])
        new_note = (f"llm_prereq cosine={o.get('cosine', '?')} hard "
                    f"[promoted_soft_to_hard via {src}]: {o.get('reason', '')}")
        for s, t in ((tgt, prereq), (prereq, tgt)):
            cur.execute(
                "UPDATE standard_relationships SET confidence_score=0.9, notes=? "
                "WHERE source_id=? AND target_id=? AND method='llm_validated'",
                (new_note, s, t))
        n += 1
    con.commit()

    print(f"updated {n} edges (both directions)")
    dist = con.execute(
        "SELECT confidence_score, COUNT(*) FROM standard_relationships "
        "WHERE method='llm_validated' AND relationship='prerequisite' GROUP BY confidence_score"
    ).fetchall()
    print("post-promotion prerequisite confidence distribution:", dist)
    con.close()


if __name__ == "__main__":
    main()
