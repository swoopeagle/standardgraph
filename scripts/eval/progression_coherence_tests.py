"""Eval: Progression coherence — does get_progression return pedagogically sound sequences?

Cosine similarity finds relevant standards per grade, but can it tell us if the
*teaching sequence* makes sense? Gemma judges whether each progression shows
appropriate increasing complexity and grade-appropriate scaffolding.

Usage:
  uv run python scripts/eval/progression_coherence_tests.py
  uv run python scripts/eval/progression_coherence_tests.py --local-judge
  uv run python scripts/eval/progression_coherence_tests.py --no-judge
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import numpy as np

ROOT        = Path(__file__).parent.parent.parent
DB_PATH     = ROOT / "data" / "common_core.db"
EMBED_URL   = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]
GEMMA_STUDIO_URL   = "http://169.254.1.1:11434/api/generate"
GEMMA_STUDIO_MODEL = "gemma4:31b-it-q8_0"
GEMMA_LOCAL_URL    = "http://localhost:11434/api/generate"
GEMMA_LOCAL_MODEL  = "gemma4:26b"

_OK   = "\033[32m OK \033[0m"
_PART = "\033[33mPART\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"


# ── Tool helper ───────────────────────────────────────────────────────────────

def _embed(text: str) -> np.ndarray:
    resp = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [text]}, timeout=30)
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def tool_progression(concept: str, system: str,
                     grade_start: int | None = None,
                     grade_end: int | None = None) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT s.id, s.grade, s.standard_text, e.vector "
        "FROM standards s JOIN embeddings e ON e.standard_id=s.id WHERE s.system=?",
        (system,),
    ).fetchall()
    conn.close()
    if not rows:
        return {"error": "no_standards", "system": system, "stages": []}

    qvec = _embed(concept)
    vecs = np.array([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    scores = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)) @ q

    by_grade: dict[str, dict] = {}
    for i, r in enumerate(rows):
        g = r["grade"]
        gi = GRADE_ORDER.index(g) if g in GRADE_ORDER else 99
        if grade_start is not None and gi < grade_start:
            continue
        if grade_end is not None and gi > grade_end:
            continue
        s = float(scores[i])
        if s < 0.40:
            continue
        if g not in by_grade or s > by_grade[g]["score"]:
            by_grade[g] = {"id": r["id"], "grade": g,
                           "text": r["standard_text"], "score": round(s, 4)}

    stages = sorted(
        by_grade.values(),
        key=lambda x: GRADE_ORDER.index(x["grade"]) if x["grade"] in GRADE_ORDER else 99,
    )
    return {"concept": concept, "system": system, "stages": stages}


# ── Test scenarios ─────────────────────────────────────────────────────────────

PROGRESSIONS = [
    {
        "name": "CCSS: fractions (Gr 3–5)",
        "description": "Core fraction progression — introduce, extend, operate",
        "kwargs": {"concept": "fractions equal parts numerator denominator", "system": "ccss",
                   "grade_start": 3, "grade_end": 5},
        "min_stages": 3,
        "check_desc": "≥3 grade stages returned",
    },
    {
        "name": "CCSS: place value (Gr K–3)",
        "description": "Foundation number sense — ones/tens/hundreds/thousands",
        "kwargs": {"concept": "place value ones tens hundreds digits", "system": "ccss",
                   "grade_start": 0, "grade_end": 3},
        "min_stages": 3,
        "check_desc": "≥3 grade stages returned",
    },
    {
        "name": "CCSS: algebra & linear equations (Gr 6–HS)",
        "description": "Algebraic reasoning ramp — expressions to functions",
        "kwargs": {"concept": "algebra linear equations variables expressions functions", "system": "ccss",
                   "grade_start": 6, "grade_end": 9},
        "min_stages": 3,
        "check_desc": "≥3 grade stages returned",
    },
    {
        "name": "NGSS: evolution & natural selection (K–HS)",
        "description": "Life science progression — traits to heredity to natural selection",
        "kwargs": {"concept": "evolution natural selection heredity traits variation", "system": "ngss"},
        "min_stages": 3,
        "check_desc": "≥3 grade band stages returned",
    },
    {
        "name": "CSTA: computational thinking (K–12)",
        "description": "CS progression — concrete to abstract problem solving",
        "kwargs": {"concept": "computational thinking decomposition abstraction algorithms", "system": "csta"},
        "min_stages": 3,
        "check_desc": "≥3 grade band stages returned",
    },
    {
        "name": "SG-MOE: algebra (Gr 6–HS)",
        "description": "Singapore algebra progression — equations through calculus",
        "kwargs": {"concept": "algebra equations expressions functions", "system": "sg-moe",
                   "grade_start": 6, "grade_end": 9},
        "min_stages": 2,
        "check_desc": "≥2 grade stages returned",
    },
    {
        "name": "CCSS-ELA: informational reading (Gr K–5)",
        "description": "Early literacy to complex text — key ideas and details",
        "kwargs": {"concept": "informational text main idea key details evidence", "system": "ccss-ela",
                   "grade_start": 0, "grade_end": 5},
        "min_stages": 4,
        "check_desc": "≥4 grade stages returned",
    },
    {
        "name": "C3: civic participation (Gr K–8)",
        "description": "Civics progression — classroom to democratic participation",
        "kwargs": {"concept": "civic participation government democracy rights responsibilities", "system": "c3",
                   "grade_start": 0, "grade_end": 8},
        "min_stages": 3,
        "check_desc": "≥3 grade stages returned",
    },
]

# ── Judge ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are an expert K-12 curriculum designer.

Concept: "{concept}"
Curriculum system: {system}
Grade progression:
{stages}

Does this represent a coherent pedagogical sequence where:
1. Standards appear in a sensible grade order
2. The content becomes more sophisticated or complex at higher grades
3. Each stage meaningfully builds on the prior one

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining what specifically works or doesn't in this progression.
"""


def _format_stages(stages: list[dict]) -> str:
    lines = []
    for s in stages:
        lines.append(f"  Grade {s['grade']}: {s['text'][:120]}")
    return "\n".join(lines) if lines else "  (no stages returned)"


def _judge(test: dict, result: dict, url: str, model: str) -> tuple[str, str]:
    stages_text = _format_stages(result.get("stages", []))
    prompt = _JUDGE_PROMPT.format(
        concept=result.get("concept", test["kwargs"]["concept"]),
        system=result.get("system", test["kwargs"]["system"]),
        stages=stages_text,
    )
    try:
        resp = httpx.post(url, json={
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0},
        }, timeout=90)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
    except Exception as e:
        return "ERR", str(e)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    first = lines[0].upper() if lines else ""
    reason = lines[1] if len(lines) > 1 else raw
    if first.startswith("YES"):    return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):     return "NO", reason
    return "PARTIAL", raw


# ── Runner ────────────────────────────────────────────────────────────────────

def main(no_judge: bool = False, local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL

    n_yes = n_partial = n_no = n_err = n_det_fail = n_tool_err = 0

    print(f"\n── Progression coherence tests ({len(PROGRESSIONS)} sequences) ────────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'#':<3} {'Progression':<40} {'Stages':>6} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*40} {'-'*6} {'----':>4} {'----':>4}")

    for i, t in enumerate(PROGRESSIONS, 1):
        result: dict = {}
        error_msg = ""
        try:
            result = tool_progression(**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        n_stages = len(result.get("stages", []))
        det_pass = not error_msg and n_stages >= t["min_stages"]
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        verdict = reason = ""
        llm_tag = _SKIP
        if not no_judge and not error_msg and n_stages > 0:
            verdict, reason = _judge(t, result, judge_url, judge_model)
            llm_tag = (
                _OK   if verdict == "YES"     else
                _PART if verdict == "PARTIAL" else
                _ERR  if verdict == "ERR"     else
                _FAIL
            )

        short_name = t["name"][:38] + ".." if len(t["name"]) > 40 else t["name"]
        print(f"  {i:<3} {short_name:<40} {n_stages:>6} [{det_tag}] [{llm_tag}]")

        if not det_pass or (verdict and verdict not in ("YES", "PARTIAL")):
            if error_msg:
                print(f"       ERROR: {error_msg}")
            elif not det_pass:
                print(f"       FAIL (det): {t['check_desc']} (got {n_stages})")
            if reason:
                print(f"       LLM: {reason[:100]}")

        if verdict == "YES" and det_pass:
            # Print a brief summary of the progression
            stages = result.get("stages", [])
            grade_labels = " → ".join(f"Gr{s['grade']}" for s in stages)
            print(f"       arc: {grade_labels}")

        if error_msg:         n_tool_err += 1
        elif not det_pass:    n_det_fail += 1
        elif verdict == "NO": n_no += 1
        elif verdict == "PARTIAL": n_partial += 1
        elif verdict == "ERR": n_err += 1
        else:                 n_yes += 1

    total = len(PROGRESSIONS)
    if no_judge:
        print(f"\n  {total} tests — {n_yes} passed, {n_det_fail} det-fail, {n_tool_err} errors")
    else:
        print(f"\n  {total} tests — {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_err} LLM-err")
        print(f"  Deterministic: {n_det_fail} fail, {n_tool_err} tool-errors")
    print()
    return 0 if (n_det_fail + n_tool_err) == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--local-judge", action="store_true")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
