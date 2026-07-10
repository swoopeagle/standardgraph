#!/usr/bin/env python3
"""Phase 3 (qwen backstop / second-opinion): classify every candidate prereq pair
on Studio qwen2.5:72b, resumable via a JSONL checkpoint.

This is NOT the primary judge for the pilot — Claude classifies the full set
in-session at higher quality (claude_labels.jsonl). This runs in parallel on
otherwise-idle Studio to (a) provide an independent agreement sample on the
pairs Claude also labels, and (b) insure against a stalled Claude loop. It is
too slow to finish all 2,568 overnight; that's expected.

Prompt is kept byte-identical to prereq_gate.py's validated PROMPT.
"""
import json
import os
import sys
import time
import httpx

STUDIO = "http://100.77.63.73:11434"
MODEL = "qwen2.5:72b"
SCRATCH = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/f868f626-976d-4442-8c22-df9f64ad907b/scratchpad"
CAND = f"{SCRATCH}/prereq_candidates.json"
OUT = f"{SCRATCH}/qwen_labels.jsonl"

# byte-identical to prereq_gate.py PROMPT (the gold-validated rubric)
PROMPT = """You are validating a candidate PREREQUISITE relationship between two math \
standards from the same curriculum (Common Core). Standard B is proposed as a prerequisite \
for standard A. Judge whether B must come before A, using this operational test:

- HARD: B is a genuine building block that A directly depends on. Either performing A's task \
requires invoking B's skill, OR A is explicitly an extension, generalization, or application \
of B's concept. Test: could a coherent curriculum teach A to a student who has NOT yet learned \
B? If not, it is HARD. (Generic examples: adding two fractions HARD-requires understanding what \
a fraction is; solving a multi-step equation HARD-requires solving a single-step equation; any \
standard whose text says it "applies and extends previous understandings of X" HARD-requires X.) \
A real building block counts as HARD even if an exceptional student might improvise around it.

- SOFT: B is helpful background that builds general fluency or a related idea, but A's core \
procedure does not invoke B and A rests on other foundations. A student could be taught A \
successfully without having mastered B first.

- NONE: B is NOT a prerequisite for A. This includes pairs that merely share a topic area or \
key vocabulary, are ANALOGOUS ideas in different domains (e.g. an "is additive" property of one \
quantity vs. the same-sounding property of an unrelated quantity — parallel concepts, not \
dependent), are parallel/sibling skills at similar difficulty, or where the real dependency \
runs the OTHER direction.

Judge actual mathematical dependency, NOT topical or textual similarity. Two standards in the \
same domain, at adjacent grades, or sharing key words are NOT automatically prerequisites. \
Ask specifically: does doing A require having B's skill, or is A built by extending B? \
If yes -> HARD. If B merely helps -> SOFT. If B is only adjacent, parallel, or analogous -> NONE.

Return STRICT JSON {"label": "HARD"|"SOFT"|"NONE", "reason": str}.

TARGET A (grade %s): %s

CANDIDATE PREREQUISITE B (grade %s): %s"""


def key(c):
    return f"{c['target_id']}|{c['prereq_id']}"


def load_done():
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
    return done


def classify(item):
    prompt = PROMPT % (item["target_grade"], item["target_text"],
                       item["prereq_grade"], item["prereq_text"])
    r = httpx.post(f"{STUDIO}/api/generate", json={"model": MODEL, "prompt": prompt,
        "stream": False, "format": "json", "options": {"temperature": 0}}, timeout=300)
    r.raise_for_status()
    d = json.loads(r.json()["response"])
    label = (d.get("label") or "").upper()
    if label not in {"HARD", "SOFT", "NONE"}:
        label = "NONE"
    return label, d.get("reason", "")


def main():
    cands = json.load(open(CAND))
    done = load_done()
    todo = [c for c in cands if key(c) not in done]
    print(f"total={len(cands)} done={len(done)} todo={len(todo)}", flush=True)
    n = 0
    with open(OUT, "a") as f:
        for c in todo:
            t0 = time.time()
            try:
                label, reason = classify(c)
            except Exception as e:
                print(f"ERR {key(c)}: {e}", flush=True)
                time.sleep(5)
                continue
            f.write(json.dumps({"key": key(c), "target_id": c["target_id"],
                "prereq_id": c["prereq_id"], "label": label, "reason": reason,
                "cosine": c["cosine"], "model": MODEL}, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 10 == 0:
                print(f"  {n}/{len(todo)} last={label} {time.time()-t0:.0f}s", flush=True)
    print(f"done, wrote {n} this run", flush=True)


if __name__ == "__main__":
    main()
