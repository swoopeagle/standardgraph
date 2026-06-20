"""Eval: lookup_standard correctness.

Tests structural integrity of lookup results: field presence, sub-standard links,
prerequisite/successor validity, shortform ID expansion, international IDs,
and error handling. Gemma judges whether returned standard text is accurate.

Usage:
  uv run python scripts/eval/lookup_standard_tests.py
  uv run python scripts/eval/lookup_standard_tests.py --local-judge
  uv run python scripts/eval/lookup_standard_tests.py --no-judge
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT    = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "common_core.db"
GEMMA_STUDIO_URL   = "http://169.254.1.1:11434/api/generate"
GEMMA_STUDIO_MODEL = "gemma4:31b-it-q8_0"
GEMMA_LOCAL_URL    = "http://localhost:11434/api/generate"
GEMMA_LOCAL_MODEL  = "gemma4:26b"

_OK   = "\033[32m OK \033[0m"
_PART = "\033[33mPART\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


# ── Tool implementation (mirrors server's lookup_standard) ────────────────────

def tool_lookup(standard_id: str, system: str = "ccss") -> dict:
    sid = _expand_id(standard_id, system)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    row = conn.execute("SELECT * FROM standards WHERE id=?", (sid,)).fetchone()
    if not row:
        suggestions = [r[0] for r in conn.execute(
            "SELECT id FROM standards WHERE system=? LIMIT 5", (system,)
        ).fetchall()]
        conn.close()
        return {"error": "standard_not_found", "queried_id": sid, "suggestions": suggestions}

    std = dict(row)
    sub_stds = conn.execute(
        "SELECT id, text FROM sub_standards WHERE parent_id=? ORDER BY position", (sid,)
    ).fetchall()
    prerequisites = [r[0] for r in conn.execute(
        "SELECT target_id FROM standard_relationships WHERE source_id=? AND relationship='prerequisite'", (sid,)
    ).fetchall()]
    successors = [r[0] for r in conn.execute(
        "SELECT target_id FROM standard_relationships WHERE source_id=? AND relationship='successor'", (sid,)
    ).fetchall()]

    # Validate all referenced IDs actually exist
    all_ref_ids = prerequisites + successors
    invalid_refs = []
    for ref_id in all_ref_ids:
        exists = conn.execute("SELECT 1 FROM standards WHERE id=?", (ref_id,)).fetchone()
        if not exists:
            invalid_refs.append(ref_id)

    conn.close()
    return {
        "id":            std["id"],
        "system":        std["system"],
        "grade":         std["grade"],
        "domain":        std["domain"],
        "cluster":       std["cluster"],
        "standard_text": std["standard_text"],
        "sub_standards": [f"{r['id']} — {r['text']}" for r in sub_stds],
        "prerequisites": prerequisites,
        "successors":    successors,
        "source_url":    std["source_url"],
        "_invalid_refs": invalid_refs,
    }


def _expand_id(standard_id: str, system: str = "ccss") -> str:
    sid = standard_id.strip()
    upper = sid.upper()
    if upper.startswith("CCSS."):
        return sid
    if ".MATH." in upper:
        return sid
    if system == "ccss":
        return f"CCSS.MATH.{sid}"
    return sid


# ── Test cases ────────────────────────────────────────────────────────────────

TESTS = [
    # ── Shortform expansion ───────────────────────────────────────────────────
    {
        "name": "Shortform ID expansion (6.EE.2)",
        "description": "Shortform '6.EE.2' should expand to CCSS.MATH.6.EE.2",
        "kwargs": {"standard_id": "6.EE.2", "system": "ccss"},
        "check": lambda r: r.get("id") == "CCSS.MATH.6.EE.2" and "error" not in r,
        "check_desc": "id == CCSS.MATH.6.EE.2",
        "judge": False,
    },

    # ── CCSS standard with sub-standards ─────────────────────────────────────
    {
        "name": "CCSS sub-standards (CCSS.MATH.6.EE.2)",
        "description": "Standard with 3 sub-standards; successors should all resolve",
        "kwargs": {"standard_id": "CCSS.MATH.6.EE.2", "system": "ccss"},
        "check": lambda r: (
            "error" not in r
            and r.get("grade") == "6"
            and len(r.get("sub_standards", [])) == 3
            and len(r.get("successors", [])) >= 1
            and len(r.get("_invalid_refs", [])) == 0
        ),
        "check_desc": "grade=6, 3 sub-standards, successors valid",
        "judge": True,
        "judge_check": "expressions letters numbers",
    },

    # ── CCSS standard with many sub-standards ─────────────────────────────────
    {
        "name": "CCSS fractions with sub-standards (CCSS.MATH.3.NF.A.3)",
        "description": "Has 4 sub-standards and 7 successors",
        "kwargs": {"standard_id": "CCSS.MATH.3.NF.A.3", "system": "ccss"},
        "check": lambda r: (
            "error" not in r
            and r.get("grade") == "3"
            and len(r.get("sub_standards", [])) == 4
            and len(r.get("successors", [])) >= 1
            and len(r.get("_invalid_refs", [])) == 0
        ),
        "check_desc": "grade=3, 4 sub-standards, successors resolve",
        "judge": True,
        "judge_check": "equivalence fractions",
    },

    # ── International: Singapore ──────────────────────────────────────────────
    {
        "name": "Singapore lookup (SG_MOE.MATH.7.N7.7.2)",
        "description": "International ID; has prerequisites stored as relationships",
        "kwargs": {"standard_id": "SG_MOE.MATH.7.N7.7.2", "system": "sg-moe"},
        "check": lambda r: (
            "error" not in r
            and r.get("system") == "sg-moe"
            and r.get("grade") == "7"
            and len(r.get("prerequisites", [])) >= 1
            and len(r.get("_invalid_refs", [])) == 0
        ),
        "check_desc": "system=sg-moe, grade=7, prerequisites resolve",
        "judge": True,
        "judge_check": "linear equations variable",
    },

    # ── International: Japan ──────────────────────────────────────────────────
    {
        "name": "Japan lookup (JP_MEXT.MATH.1.A.1.a)",
        "description": "Japan Grade 1 standard; has successors",
        "kwargs": {"standard_id": "JP_MEXT.MATH.1.A.1.a", "system": "jp-mext"},
        "check": lambda r: (
            "error" not in r
            and r.get("system") == "jp-mext"
            and r.get("grade") == "1"
            and len(r.get("_invalid_refs", [])) == 0
        ),
        "check_desc": "system=jp-mext, grade=1, refs resolve",
        "judge": True,
        "judge_check": "compare numbers objects",
    },

    # ── International: Cambridge ──────────────────────────────────────────────
    {
        "name": "Cambridge lookup (CAMBRIDGE.MATH.9Gg.01)",
        "description": "Cambridge secondary geometry standard",
        "kwargs": {"standard_id": "CAMBRIDGE.MATH.9Gg.01", "system": "cambridge"},
        "check": lambda r: (
            "error" not in r
            and r.get("system") == "cambridge"
            and r.get("grade") in GRADE_ORDER
        ),
        "check_desc": "system=cambridge, grade valid",
        "judge": True,
        "judge_check": "area circumference circle",
    },

    # ── Grade validity ────────────────────────────────────────────────────────
    {
        "name": "Grade code is valid (CCSS.MATH.6.EE.2)",
        "description": "grade field must be one of K 1 2 3 4 5 6 7 8 HS",
        "kwargs": {"standard_id": "CCSS.MATH.6.EE.2"},
        "check": lambda r: r.get("grade") in GRADE_ORDER,
        "check_desc": "grade in GRADE_ORDER",
        "judge": False,
    },

    # ── Not-found error ───────────────────────────────────────────────────────
    {
        "name": "Nonexistent ID returns structured error",
        "description": "CCSS.MATH.99.XX.Y.99 does not exist",
        "kwargs": {"standard_id": "CCSS.MATH.99.XX.Y.99"},
        "check": lambda r: r.get("error") == "standard_not_found",
        "check_desc": "error == standard_not_found",
        "judge": False,
    },

    # ── source_url ────────────────────────────────────────────────────────────
    {
        "name": "source_url field present (CCSS.MATH.3.NF.A.3)",
        "description": "source_url should be a non-empty string or None (not missing key)",
        "kwargs": {"standard_id": "CCSS.MATH.3.NF.A.3"},
        "check": lambda r: "source_url" in r,
        "check_desc": "source_url key present",
        "judge": False,
    },

    # ── Domain and cluster ────────────────────────────────────────────────────
    {
        "name": "Domain and cluster populated (CCSS.MATH.6.EE.2)",
        "description": "domain and cluster should be non-empty strings",
        "kwargs": {"standard_id": "CCSS.MATH.6.EE.2"},
        "check": lambda r: bool(r.get("domain")) and bool(r.get("cluster")),
        "check_desc": "domain and cluster non-empty",
        "judge": False,
    },
]


# ── Judge ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are a K-12 curriculum specialist verifying that a database record matches a real standard.

Standard ID: {standard_id}
Returned text: "{standard_text}"

The standard text should clearly relate to: {expected_keywords}

Is the returned text accurate and relevant to those keywords?
- YES: text clearly covers the expected topic
- PARTIAL: text is related but vague or incomplete
- NO: text is wrong or unrelated

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _judge(test: dict, result: dict, url: str, model: str) -> tuple[str, str]:
    prompt = _JUDGE_PROMPT.format(
        standard_id=result.get("id", "?"),
        standard_text=result.get("standard_text", "")[:300],
        expected_keywords=test["judge_check"],
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
    if first.startswith("YES"):     return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):      return "NO", reason
    return "PARTIAL", raw


# ── Runner ────────────────────────────────────────────────────────────────────

def main(no_judge: bool = False, local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL

    n_yes = n_partial = n_no = n_err = n_det_fail = n_tool_err = 0

    print(f"\n── lookup_standard tests ({len(TESTS)} cases) ──────────────────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'#':<3} {'Test':<46} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*46} {'----':>4} {'----':>4}")

    for i, t in enumerate(TESTS, 1):
        result = {}
        error_msg = ""
        try:
            result = tool_lookup(**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        det_pass = not error_msg and t["check"](result)
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        verdict = reason = ""
        llm_tag = _SKIP
        needs_judge = t.get("judge", False) and not no_judge and not error_msg and "error" not in result
        if needs_judge:
            verdict, reason = _judge(t, result, judge_url, judge_model)
            llm_tag = (
                _OK   if verdict == "YES"     else
                _PART if verdict == "PARTIAL" else
                _ERR  if verdict == "ERR"     else
                _FAIL
            )

        short = t["name"][:44] + ".." if len(t["name"]) > 46 else t["name"]
        print(f"  {i:<3} {short:<46} [{det_tag}] [{llm_tag}]")

        if not det_pass:
            if error_msg:
                print(f"       ERROR: {error_msg}")
            else:
                print(f"       FAIL (det): {t['check_desc']}")
                if result.get("_invalid_refs"):
                    print(f"       invalid_refs: {result['_invalid_refs'][:3]}")
        if verdict and verdict != "YES" and reason:
            print(f"       LLM: {reason[:100]}")

        if error_msg:              n_tool_err += 1
        elif not det_pass:         n_det_fail += 1
        elif verdict == "NO":      n_no += 1
        elif verdict == "PARTIAL": n_partial += 1
        elif verdict == "ERR":     n_err += 1
        elif verdict == "YES":     n_yes += 1
        # no-judge or skip: not counted in llm tallies

    judge_tests = sum(1 for t in TESTS if t.get("judge", False))
    skip_tests  = len(TESTS) - judge_tests
    print(f"\n  {len(TESTS)} tests ({skip_tests} det-only, {judge_tests} judged)")
    if not no_judge:
        print(f"  LLM: {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_err} ERR")
    print(f"  Deterministic: {n_det_fail} fail, {n_tool_err} tool-errors")
    print()
    return 0 if (n_det_fail + n_tool_err) == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--local-judge", action="store_true")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
