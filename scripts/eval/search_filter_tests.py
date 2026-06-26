"""Eval: search_standards filter accuracy.

Tests that grade and domain filters in search_standards produce correctly filtered
results — all returned standards must match the requested grade/domain/range.
Also tests the grade range parser (e.g. "6-8") and edge grades (K, HS).

All checks are deterministic — no LLM judge needed.

Usage:
  uv run python scripts/eval/search_filter_tests.py
"""
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

_OK   = "\033[32m OK \033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"


# ── Tool implementation (mirrors server's search_standards) ───────────────────

def _embed(text: str) -> np.ndarray:
    resp = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [text]}, timeout=30)
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def _parse_grade_filter(grade: str) -> set[str]:
    if "-" in grade and not grade.startswith("K"):
        parts = grade.split("-")
        try:
            lo, hi = int(parts[0]), int(parts[1])
            return {str(g) for g in range(lo, hi + 1)}
        except ValueError:
            pass
    return {grade}


def tool_search(query: str, system: str, grade: str | None = None,
                domain: str | None = None, limit: int = 5) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT s.id, s.grade, s.domain, s.standard_text, e.vector "
        "FROM standards s JOIN embeddings e ON e.standard_id=s.id "
        "WHERE s.system=?", (system,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "no_standards_found", "system": system, "results": []}

    qvec = _embed(query)
    vecs = np.array([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    scores = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)) @ q

    results = []
    for i in np.argsort(scores)[::-1]:
        if len(results) >= limit:
            break
        r = rows[i]
        if grade is not None and r["grade"] not in _parse_grade_filter(grade):
            continue
        if domain is not None and domain.lower() not in r["domain"].lower():
            continue
        results.append({
            "id":    r["id"],
            "grade": r["grade"],
            "domain": r["domain"],
            "standard_text": r["standard_text"][:100],
            "score": round(float(scores[i]), 4),
        })

    return {"query": query, "system": system, "grade": grade, "domain": domain, "results": results}


# ── Test cases ────────────────────────────────────────────────────────────────

TESTS = [
    # ── Single grade filter ───────────────────────────────────────────────────
    {
        "name": "Grade=5 filter returns only grade 5",
        "kwargs": {"query": "fractions multiplication", "system": "ccss", "grade": "5", "limit": 10},
        "check": lambda r: all(s["grade"] == "5" for s in r["results"]) and len(r["results"]) > 0,
        "check_desc": "all results grade=5",
    },
    {
        "name": "Grade=K filter returns only kindergarten",
        "kwargs": {"query": "counting numbers", "system": "ccss", "grade": "K", "limit": 10},
        "check": lambda r: all(s["grade"] == "K" for s in r["results"]) and len(r["results"]) > 0,
        "check_desc": "all results grade=K",
    },
    {
        "name": "Grade=HS filter returns only high school",
        "kwargs": {"query": "quadratic equations functions", "system": "ccss", "grade": "HS", "limit": 10},
        "check": lambda r: all(s["grade"] == "HS" for s in r["results"]) and len(r["results"]) > 0,
        "check_desc": "all results grade=HS",
    },

    # ── Grade range filter ────────────────────────────────────────────────────
    {
        "name": "Grade=6-8 range returns only grades 6, 7, 8",
        "kwargs": {"query": "proportional reasoning ratios", "system": "ccss", "grade": "6-8", "limit": 10},
        "check": lambda r: (
            all(s["grade"] in {"6", "7", "8"} for s in r["results"])
            and len(r["results"]) > 0
        ),
        "check_desc": "all results in {6,7,8}",
    },
    {
        "name": "Grade=3-5 range returns only grades 3, 4, 5",
        "kwargs": {"query": "fractions place value", "system": "ccss", "grade": "3-5", "limit": 10},
        "check": lambda r: (
            all(s["grade"] in {"3", "4", "5"} for s in r["results"])
            and len(r["results"]) > 0
        ),
        "check_desc": "all results in {3,4,5}",
    },

    # ── Domain filter ─────────────────────────────────────────────────────────
    {
        "name": "Domain=geometry filter (CCSS)",
        "kwargs": {"query": "shapes angles area", "system": "ccss", "domain": "geometry", "limit": 10},
        "check": lambda r: (
            all("geometry" in s["domain"].lower() for s in r["results"])
            and len(r["results"]) > 0
        ),
        "check_desc": "all results contain 'geometry' in domain",
    },

    # ── Combined grade + domain ───────────────────────────────────────────────
    {
        "name": "Grade=4 + domain=fractions filter",
        "kwargs": {"query": "fractions equivalent", "system": "ccss",
                   "grade": "4", "domain": "fraction", "limit": 10},
        "check": lambda r: (
            all(s["grade"] == "4" and "fraction" in s["domain"].lower() for s in r["results"])
        ),
        "check_desc": "all results grade=4 AND domain contains 'fraction'",
    },

    # ── International system with grade filter ────────────────────────────────
    {
        "name": "Singapore grade=7 filter",
        "kwargs": {"query": "algebra equations", "system": "sg-moe", "grade": "7", "limit": 5},
        "check": lambda r: all(s["grade"] == "7" for s in r["results"]) and len(r["results"]) > 0,
        "check_desc": "all results grade=7 for sg-moe",
    },

    # ── No grade filter: should return results across grades ──────────────────
    {
        "name": "No grade filter returns mixed grades",
        "kwargs": {"query": "fractions", "system": "ccss", "limit": 10},
        "check": lambda r: len({s["grade"] for s in r["results"]}) >= 2,
        "check_desc": "results span ≥2 different grades (unfilitered)",
    },

    # ── Limit respected ───────────────────────────────────────────────────────
    {
        "name": "limit=3 returns exactly 3 results",
        "kwargs": {"query": "multiplication", "system": "ccss", "limit": 3},
        "check": lambda r: len(r["results"]) == 3,
        "check_desc": "exactly 3 results returned",
    },
]


def main() -> int:
    n_pass = n_fail = n_err = 0

    print(f"\n── search_standards filter tests ({len(TESTS)} cases) ──────────────────")
    print(f"  {'#':<3} {'Test':<50} {'Det':>4}")
    print(f"  {'-'*3} {'-'*50} {'----':>4}")

    for i, t in enumerate(TESTS, 1):
        result = {}
        error_msg = ""
        try:
            result = tool_search(**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        det_pass = not error_msg and t["check"](result)
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        short = t["name"][:48] + ".." if len(t["name"]) > 50 else t["name"]
        print(f"  {i:<3} {short:<50} [{det_tag}]")

        if not det_pass:
            if error_msg:
                print(f"       ERROR: {error_msg}")
            else:
                print(f"       FAIL: {t['check_desc']}")
                grades = {s["grade"] for s in result.get("results", [])}
                domains = {s["domain"] for s in result.get("results", [])}
                print(f"       returned grades={grades} domains={domains} n={len(result.get('results', []))}")

        if error_msg:    n_err += 1
        elif det_pass:   n_pass += 1
        else:            n_fail += 1

    print(f"\n  {len(TESTS)} tests — {n_pass} pass / {n_fail} fail / {n_err} error")
    print()
    return 0 if (n_fail + n_err) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
