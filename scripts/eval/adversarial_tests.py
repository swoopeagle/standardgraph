"""Eval: Adversarial / edge-case tests — graceful degradation.

Tests how the tools behave when users ask impossible, out-of-scope, or cross-subject
questions. Checks two things:
  (det) Does the tool return structurally correct output (not crash, right shape)?
  (LLM) Does the response handle the edge case gracefully — not returning junk?

Usage:
  uv run python scripts/eval/adversarial_tests.py
  uv run python scripts/eval/adversarial_tests.py --local-judge
  uv run python scripts/eval/adversarial_tests.py --no-judge
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


# ── Tool helpers ──────────────────────────────────────────────────────────────

def _embed(text: str) -> np.ndarray:
    resp = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [text]}, timeout=30)
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def tool_search(query: str, system: str, grade: str | None = None, limit: int = 5) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    params: tuple = (system,)
    grade_clause = ""
    if grade:
        grade_clause = " AND s.grade=?"
        params += (grade,)
    rows = conn.execute(
        f"SELECT s.id, s.grade, s.domain, s.standard_text, e.vector "
        f"FROM standards s JOIN embeddings e ON e.standard_id=s.id "
        f"WHERE s.system=?{grade_clause}", params,
    ).fetchall()
    conn.close()
    if not rows:
        return {"error": "no_standards_found", "system": system, "grade": grade, "results": []}
    qvec = _embed(query)
    vecs = np.array([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    scores = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)) @ q
    top = np.argsort(scores)[::-1][:limit]
    return {
        "query": query, "system": system, "grade": grade,
        "results": [
            {"id": rows[i]["id"], "grade": rows[i]["grade"],
             "standard_text": rows[i]["standard_text"][:120],
             "score": round(float(scores[i]), 4)}
            for i in top
        ],
    }


def tool_lookup(standard_id: str) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM standards WHERE id=?", (standard_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": "not_found", "id": standard_id}
    std = dict(row)
    return {"id": std["id"], "system": std["system"], "grade": std["grade"],
            "standard_text": std["standard_text"]}


def tool_map(source_id: str, to_system: str) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    src = conn.execute("SELECT * FROM standards WHERE id=?", (source_id,)).fetchone()
    if not src:
        conn.close()
        return {"error": "source_not_found", "id": source_id}
    rows = conn.execute(
        """SELECT cm.target_id, cm.confidence_score, s.standard_text
           FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.target_id
           WHERE cm.source_id=? AND cm.target_system=?
           ORDER BY cm.confidence_score DESC LIMIT 5""",
        (source_id, to_system),
    ).fetchall()
    conn.close()
    return {
        "source_id": source_id,
        "source_text": src["standard_text"],
        "to_system": to_system,
        "found": len(rows) > 0,
        "mappings": [{"target_id": r["target_id"], "confidence": round(r["confidence_score"], 4),
                      "text": r["standard_text"][:100]} for r in rows],
    }


# ── Test scenarios ─────────────────────────────────────────────────────────────

def _scenarios():
    return [
        # ── Out-of-range grade ─────────────────────────────────────────────────
        {
            "name": "jp-mext Grade 9 (DB only has 1–6)",
            "description": "Search jp-mext grade 9 — this grade doesn't exist in the DB",
            "expected_behavior": "Returns empty results or a no-standards error, not junk results",
            "fn": tool_search,
            "kwargs": {"query": "algebra linear functions", "system": "jp-mext", "grade": "9"},
            "check": lambda r: len(r.get("results", [])) == 0,
            "check_desc": "empty results for out-of-range grade",
        },
        {
            "name": "gh-nacca Grade 4 (DB only has Gr 10–HS)",
            "description": "Search Ghana NACCA grade 4 — DB only has secondary (Gr 10+)",
            "expected_behavior": "Returns empty results because primary grades aren't in the DB",
            "fn": tool_search,
            "kwargs": {"query": "fractions", "system": "gh-nacca", "grade": "4"},
            "check": lambda r: len(r.get("results", [])) == 0,
            "check_desc": "empty results for missing grade band",
        },

        # ── Nonexistent IDs ────────────────────────────────────────────────────
        {
            "name": "Lookup nonexistent standard ID",
            "description": "Look up a standard ID that doesn't exist in the DB",
            "expected_behavior": "Returns a structured error, not a crash or empty dict",
            "fn": tool_lookup,
            "kwargs": {"standard_id": "CCSS.MATH.99.XX.Y.99"},
            "check": lambda r: "error" in r and r["error"] == "not_found",
            "check_desc": "returns not_found error",
        },
        {
            "name": "Map from nonexistent source ID",
            "description": "Try to crosswalk a standard ID that doesn't exist",
            "expected_behavior": "Returns a structured error explaining the source wasn't found",
            "fn": tool_map,
            "kwargs": {"source_id": "FAKE.STANDARD.0.0.0", "to_system": "ccss"},
            "check": lambda r: "error" in r,
            "check_desc": "returns error for missing source",
        },

        # ── Cross-subject false positives ──────────────────────────────────────
        {
            "name": "Photosynthesis in CCSS math",
            "description": "Search for a science concept in a math-only system",
            "expected_behavior": "Returns low relevance scores (< 0.60) — science query shouldn't strongly match math standards",
            "fn": tool_search,
            "kwargs": {"query": "photosynthesis chlorophyll plant cells light energy", "system": "ccss"},
            "check": lambda r: not r.get("results") or r["results"][0]["score"] < 0.60,
            "check_desc": "top score < 0.60 for science query in math system",
        },
        {
            "name": "Constitutional amendments in CCSS math",
            "description": "Search for a social studies concept in a math-only system",
            "expected_behavior": "Returns low relevance scores — social studies content doesn't match math standards",
            "fn": tool_search,
            "kwargs": {"query": "constitutional amendments bill of rights civil rights history", "system": "ccss"},
            "check": lambda r: not r.get("results") or r["results"][0]["score"] < 0.50,
            "check_desc": "top score < 0.50 for SS query in math system",
        },
        {
            "name": "Literary fiction in NGSS science",
            "description": "Search for a purely literary ELA concept in a science-only system",
            "expected_behavior": "Returns low relevance scores — narrative fiction has no overlap with science phenomena",
            "fn": tool_search,
            "kwargs": {"query": "narrative fiction protagonist character development plot setting theme", "system": "ngss"},
            "check": lambda r: not r.get("results") or r["results"][0]["score"] < 0.55,
            "check_desc": "top score < 0.55 for literary fiction in science system",
        },

        # ── Out-of-scope topics ────────────────────────────────────────────────
        {
            "name": "Quantum entanglement in CSTA K-12 CS",
            "description": "Search for a university-level quantum computing topic in K-12 CS standards",
            "expected_behavior": "Returns low scores — quantum computing is not in K-12 CSTA scope",
            "fn": tool_search,
            "kwargs": {"query": "quantum entanglement superposition qubits decoherence", "system": "csta"},
            "check": lambda r: not r.get("results") or r["results"][0]["score"] < 0.60,
            "check_desc": "top score < 0.60 for quantum computing in K-12 CSTA",
        },

        # ── Broad/trivial queries (should still work) ──────────────────────────
        {
            "name": "Very broad query: 'mathematics'",
            "description": "Extremely broad single-word query — should still return results without crashing",
            "expected_behavior": "Returns 5 relevant math standards without crashing or returning an error",
            "fn": tool_search,
            "kwargs": {"query": "mathematics", "system": "ccss", "limit": 5},
            "check": lambda r: len(r.get("results", [])) == 5,
            "check_desc": "returns 5 results for broad query",
        },
        {
            "name": "Very long nonsense query",
            "description": "A nonsensical long string — should not crash, should return low scores",
            "expected_behavior": "Doesn't crash, returns results (embeddings will find something) but scores are low",
            "fn": tool_search,
            "kwargs": {"query": "zzz xyz foo bar baz qux quux corge grault garply waldo fred plugh xyzzy thud",
                       "system": "ccss"},
            "check": lambda r: "results" in r,
            "check_desc": "returns results dict without crashing",
        },
    ]


# ── Judge ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating how a K-12 curriculum standards tool handles an edge-case query.

Edge case: {name}
Expected behavior: {expected_behavior}
Tool result:
{result}

Did the tool handle this appropriately?
- YES: handled correctly (graceful empty, informative error, or appropriately low scores)
- PARTIAL: somewhat handled but could be clearer or more helpful
- NO: poor handling (returned junk/false positives, crashed, or gave misleading output)

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _judge(test: dict, result: dict, url: str, model: str) -> tuple[str, str]:
    snippet = json.dumps(result, indent=2)[:600]
    try:
        resp = httpx.post(url, json={
            "model": model,
            "prompt": _JUDGE_PROMPT.format(
                name=test["name"],
                expected_behavior=test["expected_behavior"],
                result=snippet,
            ),
            "stream": False,
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

    tests = _scenarios()
    n_yes = n_partial = n_no = n_err = n_det_fail = n_tool_err = 0

    print(f"\n── Adversarial / edge-case tests ({len(tests)} scenarios) ──────────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'#':<3} {'Test':<42} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*42} {'----':>4} {'----':>4}")

    for i, t in enumerate(tests, 1):
        result: dict = {}
        error_msg = ""
        try:
            result = t["fn"](**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        det_pass = not error_msg and t["check"](result)
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        verdict = reason = ""
        llm_tag = _SKIP
        if not no_judge and not error_msg:
            verdict, reason = _judge(t, result, judge_url, judge_model)
            llm_tag = (
                _OK   if verdict == "YES"     else
                _PART if verdict == "PARTIAL" else
                _ERR  if verdict == "ERR"     else
                _FAIL
            )

        short_name = t["name"][:40] + ".." if len(t["name"]) > 42 else t["name"]
        print(f"  {i:<3} {short_name:<42} [{det_tag}] [{llm_tag}]")

        if not det_pass or (verdict and verdict not in ("YES", "PARTIAL")):
            if error_msg:
                print(f"       ERROR: {error_msg}")
            elif not det_pass:
                print(f"       FAIL (det): {t['check_desc']}")
                if result.get("results"):
                    top = result["results"][0]
                    print(f"       top result: score={top['score']} — {top['standard_text'][:60]}")
            if reason:
                print(f"       LLM: {reason[:100]}")

        if error_msg:         n_tool_err += 1
        elif not det_pass:    n_det_fail += 1
        elif verdict == "NO": n_no += 1
        elif verdict == "PARTIAL": n_partial += 1
        elif verdict == "ERR": n_err += 1
        else:                 n_yes += 1

    total = len(tests)
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
