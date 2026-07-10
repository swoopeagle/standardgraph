#!/usr/bin/env python3
"""Phase 1: prerequisite guardrail gate — directional HARD/SOFT/NONE judgment,
validated against a hand-labeled gold set keyed by (target_id, prereq_id).

Binary admission = label==HARD (only HARD edges get inserted by default).
Critical traps: (a) no clearly-spurious pair may be predicted HARD (that's the
relate.py false-positive we exist to prevent); (b) every real cross-domain
prereq must be predicted HARD (the edges relate.py structurally misses).
"""
import json
import httpx

STUDIO = "http://100.77.63.73:11434"
MODEL = "qwen2.5:72b"
SAMPLE = "/private/tmp/claude-501/-Users-ianwang-projects-standardgraph/5e706f47-a543-4d24-9d36-7f015a2c052c/scratchpad/prereq_gold_sample.json"
P = "CCSS.MATH."

# gold labels keyed by (target_suffix, prereq_suffix)
GOLD = {
    # HARD — genuine prerequisites
    ("5.MD.A.1","4.MD.A.2"):"HARD", ("5.NF.B.4","4.NF.B.4.c"):"HARD",
    ("3.NBT.A.1","2.NBT.A.3"):"HARD", ("5.NF.B.6","4.NF.B.4.b"):"HARD",
    ("2.MD.A.3","1.MD.A.2"):"HARD", ("4.OA.A.2","3.OA.A.3"):"HARD",
    ("1.OA.D.7","K.OA.A.1"):"HARD", ("HSA.SSE.A.1","6.EE.9"):"HARD",
    ("5.NF.B.5","3.OA.A.3"):"HARD", ("HSF.BF.B.4","8.F.1"):"HARD",
    ("HSF.BF.B.4.a","7.EE.4.a"):"HARD", ("HSF.LE.A.1.b","8.F.4"):"HARD",
    ("7.G.5","4.MD.C.5"):"HARD", ("HSG.SRT.A.1.a","8.G.1.a"):"HARD",
    ("2.OA.A.1","1.OA.B.4"):"HARD", ("4.G.A.2","1.G.A.1"):"HARD",
    ("4.NF.B.4","3.NF.A.3"):"HARD", ("7.EE.1","6.EE.3"):"HARD",
    ("8.EE.7.b","7.EE.4.a"):"HARD", ("5.NF.B.5.b","3.NF.A.1"):"HARD",
    # SOFT — helpful but not required
    ("7.SP.7","6.SP.1"):"SOFT", ("HSF.BF.A.1.a","6.EE.2.b"):"SOFT",
    ("4.MD.C.5.b","2.G.A.1"):"SOFT", ("1.NBT.C.5","K.OA.A.3"):"SOFT",
    ("6.SP.5","5.NBT.A.3"):"SOFT", ("HSF.LE.A.1.c","6.RP.2"):"SOFT",
    ("HSG.MG.A.1","6.G.4"):"SOFT", ("HSN.Q.A.2","7.EE.4"):"SOFT",
    ("5.NF.B.3","4.NF.B.4.c"):"SOFT", ("8.NS.2","6.NS.7.c"):"SOFT",
    # NONE — not a real prerequisite (traps)
    ("4.MD.C.7","3.MD.C.7.d"):"NONE", ("4.MD.C.6","3.MD.B.4"):"NONE",
    ("3.MD.B.3","2.MD.B.5"):"NONE", ("7.SP.5","6.SP.1"):"NONE",
    ("8.F.3","7.G.3"):"NONE", ("6.RP.3.b","3.MD.A.1"):"NONE",
    ("8.G.7","6.G.1"):"NONE", ("5.NBT.B.4","4.NBT.B.6"):"NONE",
}
# critical: these clearly-spurious pairs must NOT be predicted HARD
MUST_NOT_HARD = {("4.MD.C.7","3.MD.C.7.d"),("4.MD.C.6","3.MD.B.4"),
    ("3.MD.B.3","2.MD.B.5"),("8.F.3","7.G.3"),("6.RP.3.b","3.MD.A.1"),
    ("8.G.7","6.G.1"),("5.NBT.B.4","4.NBT.B.6")}
# critical: these real cross-domain prereqs (relate.py misses them) must be HARD
MUST_HARD = {("HSA.SSE.A.1","6.EE.9"),("5.NF.B.5","3.OA.A.3"),
    ("HSF.BF.B.4","8.F.1"),("HSF.BF.B.4.a","7.EE.4.a"),
    ("HSF.LE.A.1.b","8.F.4"),("7.G.5","4.MD.C.5"),("HSG.SRT.A.1.a","8.G.1.a")}

PROMPT = """You are validating a candidate PREREQUISITE relationship between two math \
standards from the same curriculum (Common Core). Standard B is proposed as a prerequisite \
for standard A. Judge it:

- HARD: a student genuinely needs the skill/understanding in B BEFORE they can succeed at A. \
B is a real mathematical building block for A.
- SOFT: B is helpful background for A, but a student could reasonably succeed at A without \
first mastering B.
- NONE: B is NOT a prerequisite for A — they are unrelated, merely share topic area or \
vocabulary, are parallel skills rather than dependent, or the real dependency runs the OTHER \
direction.

Judge actual mathematical dependency, NOT topical or textual similarity. Two standards in the \
same domain at adjacent grades are NOT automatically prerequisites — a real prerequisite means \
the target genuinely cannot be learned without the candidate's skill first.

Return STRICT JSON {"label": "HARD"|"SOFT"|"NONE", "reason": str}.

TARGET A (grade %s): %s

CANDIDATE PREREQUISITE B (grade %s): %s"""


def classify(item):
    prompt = PROMPT % (item["target_grade"], item["target_text"],
                       item["prereq_grade"], item["prereq_text"])
    r = httpx.post(f"{STUDIO}/api/generate", json={"model": MODEL, "prompt": prompt,
        "stream": False, "format": "json", "options": {"temperature": 0}}, timeout=180)
    r.raise_for_status()
    d = json.loads(r.json()["response"])
    return (d.get("label") or "").upper(), d.get("reason", "")


def suffix(sid): return sid.replace(P, "")


def main():
    sample = json.load(open(SAMPLE))
    binary_agree = total = 0
    exact_agree = 0
    spurious_accepted = []
    missed_crossdomain = []
    disagreements = []

    for item in sample:
        key = (suffix(item["target_id"]), suffix(item["prereq_id"]))
        gold = GOLD.get(key)
        if gold is None:
            continue
        total += 1
        pred, reason = classify(item)
        if pred not in {"HARD","SOFT","NONE"}:
            pred = "NONE"
        if pred == gold:
            exact_agree += 1
        # binary: HARD vs not-HARD (what actually gets inserted)
        if (pred == "HARD") == (gold == "HARD"):
            binary_agree += 1
        else:
            disagreements.append((key, gold, pred, reason))
        if key in MUST_NOT_HARD and pred == "HARD":
            spurious_accepted.append((key, reason))
        if key in MUST_HARD and pred != "HARD":
            missed_crossdomain.append((key, pred, reason))

    print(f"binary agreement (HARD vs not): {binary_agree}/{total} ({100*binary_agree/total:.0f}%)")
    print(f"exact 3-way agreement: {exact_agree}/{total} ({100*exact_agree/total:.0f}%)")
    print(f"CRITICAL — spurious pairs accepted as HARD: {len(spurious_accepted)}")
    for k, r in spurious_accepted: print(f"   !! {k}: {r[:90]}")
    print(f"CRITICAL — real cross-domain prereqs missed: {len(missed_crossdomain)}")
    for k, p, r in missed_crossdomain: print(f"   !! {k} -> {p}: {r[:90]}")
    print("\ndisagreements (binary):")
    for k, g, p, r in disagreements:
        print(f"   {k[0]} <- {k[1]}: gold={g} pred={p} | {r[:80]}")

    ok = (binary_agree/total >= 0.85) and not spurious_accepted and not missed_crossdomain
    print(f"\n=== GATE: {'PASS' if ok else 'FAIL'} ===")


if __name__ == "__main__":
    main()
