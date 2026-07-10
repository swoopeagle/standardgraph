#!/usr/bin/env python3
"""Phase 3 primary judge harness — Claude labels the candidate pairs in-session.

Two modes:
  next N        print the next N unlabeled candidates compactly (by key)
  add FILE      append a JSON array of {key,label,reason} to claude_labels.jsonl
  stats         show progress + label distribution

Resumable: `next` skips any key already present in claude_labels.jsonl.
Label must be HARD | SOFT | NONE.
"""
import json
import os
import sys

SCRATCH = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad"
CAND = f"{SCRATCH}/prereq_candidates.json"
OUT = f"{SCRATCH}/claude_labels.jsonl"


def key(c):
    return f"{c['target_id']}|{c['prereq_id']}"


def load_done():
    done = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                done[o["key"]] = o["label"]
    return done


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    cands = json.load(open(CAND))
    done = load_done()

    if cmd == "next":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        todo = [c for c in cands if key(c) not in done]
        print(f"# remaining={len(todo)} done={len(done)}/{len(cands)}")
        for c in todo[:n]:
            xd = "X-DOM" if c["cross_domain"] else "same-dom"
            print(f"\n[{key(c)}] cos={c['cosine']} {xd}")
            print(f"  A g{c['target_grade']} {c['target_domain']}: {c['target_text']}")
            print(f"  B g{c['prereq_grade']} {c['prereq_domain']}: {c['prereq_text']}")
        return

    if cmd == "add":
        arr = json.load(open(sys.argv[2]))
        valid_keys = {key(c) for c in cands}
        added = 0
        with open(OUT, "a") as f:
            for o in arr:
                if o["key"] not in valid_keys:
                    print(f"  WARN unknown key {o['key']}", file=sys.stderr)
                    continue
                if o["label"] not in {"HARD", "SOFT", "NONE"}:
                    print(f"  WARN bad label {o}", file=sys.stderr)
                    continue
                f.write(json.dumps({"key": o["key"], "label": o["label"],
                    "reason": o.get("reason", "")}, ensure_ascii=False) + "\n")
                added += 1
        done2 = load_done()
        print(f"added {added}; total done {len(done2)}/{len(cands)}")
        return

    # stats
    from collections import Counter
    dist = Counter(done.values())
    print(f"done {len(done)}/{len(cands)}  dist={dict(dist)}")


if __name__ == "__main__":
    main()
