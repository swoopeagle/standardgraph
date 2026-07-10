#!/usr/bin/env python3
"""Phase 3 DB insert — upsert the Claude-validated prerequisite edges into scratch.

Reads claude_labels.jsonl (the primary judge's full labeling of all 2,568
candidates) joined with prereq_candidates.json (for cosine), and upserts the
HARD + SOFT edges as method='llm_validated'. NONE edges are dropped.

For each validated edge (prereq_id is a prerequisite of target_id):
  - prerequisite row: source_id=target_id (learner), target_id=prereq_id
  - successor   row: source_id=prereq_id, target_id=target_id (mirror)

Existing grade_heuristic rows for the same (source,target,relationship) are
UPSERTED (upgraded to llm_validated) via ON CONFLICT. Cross-domain edges that
relate.py never created are fresh inserts.

Strength encoding (for get_learning_path):
  HARD -> confidence_score=0.9, notes 'llm_prereq cosine=X hard: ...'
  SOFT -> confidence_score=0.5, notes 'llm_prereq cosine=X soft: ...'
flagged_for_review stays 0; HARD vs SOFT is distinguished by confidence_score.

All candidates are CCSS math -> system='ccss'.
"""
import json
import sqlite3
import sys

SCRATCH = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad"
DB = f"{SCRATCH}/prereq_pilot.db"
CAND = f"{SCRATCH}/prereq_candidates.json"
LABELS = f"{SCRATCH}/claude_labels.jsonl"
SYSTEM = "ccss"

CONF = {"HARD": 0.9, "SOFT": 0.5}

UPSERT = """
INSERT INTO standard_relationships
    (source_id, target_id, relationship, system, confidence_score, notes, method, flagged_for_review)
VALUES (?, ?, ?, ?, ?, ?, 'llm_validated', 0)
ON CONFLICT(source_id, target_id, relationship) DO UPDATE SET
    confidence_score = excluded.confidence_score,
    notes            = excluded.notes,
    method           = 'llm_validated',
    flagged_for_review = 0
"""


def main():
    cands = {f"{c['target_id']}|{c['prereq_id']}": c for c in json.load(open(CAND))}
    labels = {}
    with open(LABELS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            labels[o["key"]] = o  # last write wins (resumable file: keys unique here)

    edges = [(k, o) for k, o in labels.items() if o["label"] in ("HARD", "SOFT")]
    print(f"labels total={len(labels)}  validated (HARD+SOFT)={len(edges)}")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    n_pre = n_suc = 0
    for key, o in edges:
        c = cands[key]
        learner = c["target_id"]      # higher-grade standard being learned
        prereq = c["prereq_id"]       # lower-grade prerequisite
        label = o["label"]
        conf = CONF[label]
        note = f"llm_prereq cosine={c['cosine']:.4f} {label.lower()}: {o.get('reason','')}"
        # prerequisite: learner depends on prereq
        cur.execute(UPSERT, (learner, prereq, "prerequisite", SYSTEM, conf, note))
        n_pre += 1
        # successor (mirror): prereq's successor is learner
        cur.execute(UPSERT, (prereq, learner, "successor", SYSTEM, conf, note))
        n_suc += 1
    con.commit()

    print(f"upserted {n_pre} prerequisite + {n_suc} successor rows")
    for lbl in ("HARD", "SOFT"):
        cnt = sum(1 for _, o in edges if o["label"] == lbl)
        print(f"  {lbl}: {cnt} edges")
    tot = cur.execute("SELECT method, COUNT(*) FROM standard_relationships "
                      "WHERE method='llm_validated' GROUP BY method").fetchall()
    print("llm_validated rows in DB:", tot)
    con.close()


if __name__ == "__main__":
    main()
