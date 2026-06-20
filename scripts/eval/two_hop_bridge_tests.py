"""Eval: map_standard two-hop bridge — international-to-international crosswalks.

The precomputed crosswalk only links each system directly to its subject hub (CCSS, NGSS, etc).
For any-to-any comparison (e.g. sg-moe → cambridge), map_standard routes through the hub:
  source → CCSS → target

This script tests 8 international-to-international pairs to verify the bridge returns
conceptually correct results when no direct crosswalk exists.

Usage:
  uv run python scripts/eval/two_hop_bridge_tests.py
  uv run python scripts/eval/two_hop_bridge_tests.py --local-judge
  uv run python scripts/eval/two_hop_bridge_tests.py --no-judge
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


# ── Two-hop bridge (mirrors map_standard strategy 2 in server.py) ─────────────

def tool_map_two_hop(source_id: str, from_system: str, to_system: str,
                     min_conf: float = 0.70) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    src = conn.execute("SELECT * FROM standards WHERE id=?", (source_id,)).fetchone()
    if not src:
        conn.close()
        return {"error": "source_not_found", "id": source_id}

    # Forward two-hop: source → CCSS intermediary → target
    ccss_rows = conn.execute("""
        SELECT target_id, confidence_score FROM crosswalk_mappings
        WHERE source_id=? AND target_system='ccss'
        ORDER BY confidence_score DESC LIMIT 3
    """, (source_id,)).fetchall()

    raw: list[dict] = []
    for cr in ccss_rows:
        ccss_id, ccss_conf = cr["target_id"], cr["confidence_score"]
        target_rows = conn.execute("""
            SELECT cm.source_id, cm.confidence_score,
                   s.standard_text, s.grade, s.domain
            FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.source_id
            WHERE cm.target_id=? AND s.system=?
            ORDER BY cm.confidence_score DESC LIMIT 5
        """, (ccss_id, to_system)).fetchall()
        for tr in target_rows:
            raw.append({
                "target_id":            tr["source_id"],
                "target_text":          tr["standard_text"],
                "target_grade":         tr["grade"],
                "via_ccss":             ccss_id,
                "hop1_confidence":      round(ccss_conf, 4),
                "hop2_confidence":      round(tr["confidence_score"], 4),
                "combined_confidence":  round(ccss_conf * tr["confidence_score"], 4),
            })

    seen: set[str] = set()
    results: list[dict] = []
    for r in sorted(raw, key=lambda x: -x["combined_confidence"]):
        if r["target_id"] not in seen and r["combined_confidence"] >= min_conf:
            seen.add(r["target_id"])
            results.append(r)
            if len(results) >= 5:
                break

    src_dict = dict(src)
    conn.close()
    return {
        "source_id":   source_id,
        "source_text": src_dict["standard_text"],
        "source_grade": src_dict["grade"],
        "from_system": from_system,
        "to_system":   to_system,
        "method":      "two_hop_via_ccss",
        "results":     results,
    }


# ── Test cases ────────────────────────────────────────────────────────────────

TESTS = [
    {
        "name": "sg-moe → cambridge (circles)",
        "description": "SG Gr7 area/circumference of circle → closest Cambridge equivalent",
        "kwargs": {"source_id": "SG_MOE.MATH.7.G4.4.2", "from_system": "sg-moe", "to_system": "cambridge"},
        "min_combined": 0.75,
        "expect_concept": "area circumference circle",
    },
    {
        "name": "jp-mext → cambridge (circles)",
        "description": "JP Gr6 area of circles → Cambridge; grade delta expected (JP 6, Cam 8)",
        "kwargs": {"source_id": "JP_MEXT.MATH.6.B.2.a", "from_system": "jp-mext", "to_system": "cambridge"},
        "min_combined": 0.70,
        "expect_concept": "area circle",
    },
    {
        "name": "in-ncert → cambridge (measurement)",
        "description": "India Gr3 standard units of length → Cambridge equivalent",
        "kwargs": {"source_id": "IN_NCERT.MATH.3.3646", "from_system": "in-ncert", "to_system": "cambridge"},
        "min_combined": 0.70,
        "expect_concept": "length measurement centimetres metres",
    },
    {
        "name": "in-ncert → uk-nc (addition/subtraction)",
        "description": "India Gr2 addition/subtraction → UK National Curriculum",
        "kwargs": {"source_id": "IN_NCERT.MATH.2.60213", "from_system": "in-ncert", "to_system": "uk-nc"},
        "min_combined": 0.70,
        "expect_concept": "addition subtraction problems",
    },
    {
        "name": "sg-moe → uk-nc (addition algorithms)",
        "description": "SG Gr3 addition/subtraction algorithm → UK NC equivalent",
        "kwargs": {"source_id": "SG_MOE.MATH.3.2.2.1", "from_system": "sg-moe", "to_system": "uk-nc"},
        "min_combined": 0.68,
        "expect_concept": "add subtract whole numbers digits",
    },
    {
        "name": "uk-nc → cambridge (multi-digit addition)",
        "description": "UK NC Gr5 addition >4 digits → Cambridge equivalent",
        "kwargs": {"source_id": "UK_NC.MATH.5.Nas.1", "from_system": "uk-nc", "to_system": "cambridge"},
        "min_combined": 0.70,
        "expect_concept": "add subtract whole numbers",
    },
    {
        "name": "cambridge → uk-nc (reverse of above)",
        "description": "Cambridge Gr4 addition → UK NC; tests bidirectionality",
        "kwargs": {"source_id": "CAMBRIDGE.MATH.4Ni.02", "from_system": "cambridge", "to_system": "uk-nc"},
        "min_combined": 0.70,
        "expect_concept": "add subtract whole numbers",
    },
    {
        "name": "jp-mext → au-acara (area of rectangles)",
        "description": "JP Gr4 area of squares/rectangles → Australian Curriculum",
        "kwargs": {"source_id": "JP_MEXT.MATH.4.B.1.b", "from_system": "jp-mext", "to_system": "au-acara"},
        "min_combined": 0.68,
        "expect_concept": "area rectangles triangles",
    },
]


# ── Judge ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are a K-12 curriculum specialist reviewing a crosswalk between two international curricula.

Source standard ({from_system}):
"{source_text}"

Best match found in {to_system} (via two-hop bridge through CCSS):
"{target_text}"
Combined confidence: {combined_conf}

Do these two standards teach the same or closely related mathematical concept?
- YES: same concept, appropriate for the grade levels involved
- PARTIAL: related concept but scope, depth, or grade level differs noticeably
- NO: different concepts — the mapping is incorrect

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _judge(test: dict, result: dict, url: str, model: str) -> tuple[str, str]:
    top = result["results"][0] if result.get("results") else None
    if not top:
        return "NO", "no results returned"

    prompt = _JUDGE_PROMPT.format(
        from_system=result["from_system"],
        source_text=result["source_text"][:250],
        to_system=result["to_system"],
        target_text=top["target_text"][:250],
        combined_conf=top["combined_confidence"],
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

    print(f"\n── Two-hop bridge tests ({len(TESTS)} international pairs) ──────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'#':<3} {'Test':<42} {'Conf':>6} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*42} {'-'*6} {'----':>4} {'----':>4}")

    for i, t in enumerate(TESTS, 1):
        result = {}
        error_msg = ""
        try:
            result = tool_map_two_hop(**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        top = result.get("results", [{}])[0] if not error_msg else {}
        top_conf = top.get("combined_confidence", 0.0)

        det_pass = (
            not error_msg
            and "error" not in result
            and len(result.get("results", [])) >= 1
            and top_conf >= t["min_combined"]
        )
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        verdict = reason = ""
        llm_tag = _SKIP
        if not no_judge and det_pass:
            verdict, reason = _judge(t, result, judge_url, judge_model)
            llm_tag = (
                _OK   if verdict == "YES"     else
                _PART if verdict == "PARTIAL" else
                _ERR  if verdict == "ERR"     else
                _FAIL
            )

        short = t["name"][:40] + ".." if len(t["name"]) > 42 else t["name"]
        conf_str = f"{top_conf:.3f}" if top_conf else " —   "
        print(f"  {i:<3} {short:<42} {conf_str:>6} [{det_tag}] [{llm_tag}]")

        if not det_pass:
            if error_msg:
                print(f"       ERROR: {error_msg}")
            elif "error" in result:
                print(f"       FAIL: {result['error']}")
            elif not result.get("results"):
                print(f"       FAIL: no two-hop results found (threshold={t['min_combined']})")
            else:
                print(f"       FAIL: top combined_conf={top_conf:.3f} < {t['min_combined']}")

        if det_pass and top:
            via = top.get("via_ccss", "?")
            h1, h2 = top.get("hop1_confidence", 0), top.get("hop2_confidence", 0)
            print(f"       via {via} (hop1={h1:.3f} × hop2={h2:.3f})")
            print(f"       → {top.get('target_id')} Gr{top.get('target_grade')}: {top.get('target_text','')[:65]}")

        if verdict and verdict != "YES" and reason:
            print(f"       LLM: {reason[:100]}")

        if error_msg:              n_tool_err += 1
        elif not det_pass:         n_det_fail += 1
        elif verdict == "NO":      n_no += 1
        elif verdict == "PARTIAL": n_partial += 1
        elif verdict == "ERR":     n_err += 1
        elif verdict == "YES":     n_yes += 1

    print(f"\n  {len(TESTS)} tests — {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_err} LLM-err")
    print(f"  Deterministic: {n_det_fail} fail, {n_tool_err} tool-errors")
    print()
    return 0 if (n_det_fail + n_tool_err) == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--local-judge", action="store_true")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
