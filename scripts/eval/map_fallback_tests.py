"""Eval: map_standard semantic embedding fallback (strategy 3).

When no precomputed crosswalk and no two-hop bridge exists between a source and
target system, map_standard falls back to embedding the source text and finding
nearest-neighbor standards in the target system by cosine similarity.

This tests African/developing-world systems that have no direct crosswalk link
to each other (only to CCSS/NGSS hubs) and where the two-hop bridge is absent.

Usage:
  uv run python scripts/eval/map_fallback_tests.py
  uv run python scripts/eval/map_fallback_tests.py --local-judge
  uv run python scripts/eval/map_fallback_tests.py --no-judge
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
GEMMA_STUDIO_URL   = "http://169.254.1.1:11434/api/generate"
GEMMA_STUDIO_MODEL = "gemma4:31b-it-q8_0"
GEMMA_LOCAL_URL    = "http://localhost:11434/api/generate"
GEMMA_LOCAL_MODEL  = "gemma4:26b"

_OK   = "\033[32m OK \033[0m"
_PART = "\033[33mPART\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"


# ── Embedding fallback (mirrors server's map_standard strategy 3) ─────────────

def _embed(text: str) -> np.ndarray:
    resp = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [text]}, timeout=30)
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def tool_map_fallback(source_id: str, from_system: str, to_system: str,
                      limit: int = 3) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    src = conn.execute("SELECT * FROM standards WHERE id=?", (source_id,)).fetchone()
    if not src:
        conn.close()
        return {"error": "source_not_found", "id": source_id}

    # Verify no direct crosswalk exists (to confirm fallback path is being tested)
    direct = conn.execute(
        "SELECT COUNT(*) FROM crosswalk_mappings WHERE source_id=? AND target_system=?",
        (source_id, to_system)
    ).fetchone()[0]

    # Verify no two-hop path via CCSS
    two_hop_check = conn.execute("""
        SELECT COUNT(*) FROM crosswalk_mappings cm1
        JOIN crosswalk_mappings cm2 ON cm2.target_id=cm1.target_id
        JOIN standards s ON s.id=cm2.source_id
        WHERE cm1.source_id=? AND cm1.target_system='ccss'
          AND s.system=?
    """, (source_id, to_system)).fetchone()[0]

    src_dict = dict(src)
    src_text = src_dict["standard_text"]

    # Embedding fallback: embed source, find nearest in target system
    qvec = _embed(src_text)
    tgt_rows = conn.execute(
        "SELECT s.id, s.grade, s.standard_text, e.vector "
        "FROM standards s JOIN embeddings e ON e.standard_id=s.id "
        "WHERE s.system=?", (to_system,)
    ).fetchall()
    conn.close()

    if not tgt_rows:
        return {"error": "no_standards_in_target", "to_system": to_system}

    vecs = np.array([np.frombuffer(r["vector"], dtype=np.float32) for r in tgt_rows])
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    scores = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)) @ q

    top_idx = np.argsort(scores)[::-1][:limit]
    results = [
        {
            "target_id":   tgt_rows[i]["id"],
            "target_grade": tgt_rows[i]["grade"],
            "target_text": tgt_rows[i]["standard_text"],
            "similarity":  round(float(scores[i]), 4),
        }
        for i in top_idx if scores[i] >= 0.35
    ]

    return {
        "source_id":       source_id,
        "source_text":     src_text,
        "from_system":     from_system,
        "to_system":       to_system,
        "method":          "semantic_embedding_fallback",
        "direct_crosswalk_exists": direct > 0,
        "two_hop_exists":  two_hop_check > 0,
        "results":         results,
    }


# ── Test cases ────────────────────────────────────────────────────────────────

TESTS = [
    {
        "name": "rw-reb → jp-mext (place value)",
        "description": "Rwanda Gr4 place value → Japan; no precomputed crosswalk or two-hop path",
        "kwargs": {"source_id": "RW_REB.MATH.4.36213", "from_system": "rw-reb", "to_system": "jp-mext"},
        "min_similarity": 0.50,
        "expect_concept": "numbers place value read write",
    },
    {
        "name": "za-caps → sg-moe (repeated addition)",
        "description": "South Africa Gr2 repeated addition → Singapore; no direct crosswalk",
        "kwargs": {"source_id": "ZA_CAPS.MATH.2.42790", "from_system": "za-caps", "to_system": "sg-moe"},
        "min_similarity": 0.50,
        "expect_concept": "addition multiplication repeated",
    },
    {
        "name": "gh-nacca → au-acara (rational numbers)",
        "description": "Ghana Gr10 rational numbers → Australia; no direct crosswalk",
        "kwargs": {"source_id": "GH_NACCA.MATH.10.1.1.1.LO.1", "from_system": "gh-nacca", "to_system": "au-acara"},
        "min_similarity": 0.45,
        "expect_concept": "rational numbers relationships",
    },
    {
        "name": "rw-reb → cambridge (place value)",
        "description": "Rwanda Gr4 → Cambridge; different region, no two-hop",
        "kwargs": {"source_id": "RW_REB.MATH.4.36213", "from_system": "rw-reb", "to_system": "cambridge"},
        "min_similarity": 0.50,
        "expect_concept": "numbers read write place value",
    },
    {
        "name": "za-caps → nz-moe (repeated addition)",
        "description": "South Africa → New Zealand; tests Southern Hemisphere cross-system fallback",
        "kwargs": {"source_id": "ZA_CAPS.MATH.2.42790", "from_system": "za-caps", "to_system": "nz-moe"},
        "min_similarity": 0.50,
        "expect_concept": "addition multiplication",
    },
]


# ── Judge ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are a K-12 curriculum specialist.

Source standard ({from_system}):
"{source_text}"

Best match found in {to_system} via semantic embedding fallback:
"{target_text}"
Similarity score: {similarity}

Do these two standards teach the same or closely related mathematical concept?
- YES: same concept, appropriate for the grade levels
- PARTIAL: related concept but scope or grade differs noticeably
- NO: different concepts — embedding fallback returned an incorrect result

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _judge(test: dict, result: dict, url: str, model: str) -> tuple[str, str]:
    top = result["results"][0] if result.get("results") else None
    if not top:
        return "NO", "no results returned by fallback"

    prompt = _JUDGE_PROMPT.format(
        from_system=result["from_system"],
        source_text=result["source_text"][:250],
        to_system=result["to_system"],
        target_text=top["target_text"][:250],
        similarity=top["similarity"],
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

    print(f"\n── Embedding fallback tests ({len(TESTS)} pairs) ────────────────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'#':<3} {'Test':<40} {'Sim':>5} {'2hop':>5} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*40} {'-'*5} {'-'*5} {'----':>4} {'----':>4}")

    for i, t in enumerate(TESTS, 1):
        result = {}
        error_msg = ""
        try:
            result = tool_map_fallback(**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        top = result.get("results", [{}])[0] if not error_msg else {}
        top_sim = top.get("similarity", 0.0)
        two_hop = result.get("two_hop_exists", False)

        det_pass = (
            not error_msg
            and "error" not in result
            and not result.get("direct_crosswalk_exists", True)
            and len(result.get("results", [])) >= 1
            and top_sim >= t["min_similarity"]
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

        short = t["name"][:38] + ".." if len(t["name"]) > 40 else t["name"]
        sim_str  = f"{top_sim:.3f}" if top_sim else " — "
        hop_str  = "yes" if two_hop else "no"
        print(f"  {i:<3} {short:<40} {sim_str:>5} {hop_str:>5} [{det_tag}] [{llm_tag}]")

        if not det_pass:
            if error_msg:
                print(f"       ERROR: {error_msg}")
            elif result.get("direct_crosswalk_exists"):
                print(f"       SKIP: direct crosswalk exists — not testing fallback path")
            elif not result.get("results"):
                print(f"       FAIL: no results above threshold {t['min_similarity']}")
            else:
                print(f"       FAIL: top sim={top_sim:.3f} < {t['min_similarity']}")

        if det_pass and top:
            print(f"       src: {result['source_text'][:65]}")
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
