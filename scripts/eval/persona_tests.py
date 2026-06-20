"""Persona-based evaluation — 5 user archetypes × 4 scenarios each.

Simulates realistic tool calls, uses Gemma as LLM judge.
Deterministic checks run regardless of --no-judge.

Usage:
  uv run python scripts/eval/persona_tests.py               # Mac Studio judge (31B)
  uv run python scripts/eval/persona_tests.py --local-judge # local Mac Mini judge (26B)
  uv run python scripts/eval/persona_tests.py --no-judge    # deterministic checks only
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

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
GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]

_OK   = "\033[32m OK \033[0m"
_PART = "\033[33mPART\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"


# ── DB / embed helpers ────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _embed(text: str) -> np.ndarray:
    resp = httpx.post(
        EMBED_URL,
        json={"model": EMBED_MODEL, "input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def _rank(qvec: np.ndarray, vecs: np.ndarray) -> np.ndarray:
    q = qvec / (np.linalg.norm(qvec) + 1e-9)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return (vecs / norms) @ q


def _load_system(system: str, grade: str | None = None) -> tuple[list[sqlite3.Row], np.ndarray]:
    conn = _db()
    params: tuple = (system,)
    grade_clause = ""
    if grade:
        grade_clause = " AND s.grade=?"
        params += (grade,)
    rows = conn.execute(
        f"SELECT s.id, s.grade, s.domain, s.standard_text, e.vector "
        f"FROM standards s JOIN embeddings e ON e.standard_id=s.id "
        f"WHERE s.system=?{grade_clause}",
        params,
    ).fetchall()
    conn.close()
    if not rows:
        return [], np.empty((0, 768), dtype=np.float32)
    vecs = np.array([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    return rows, vecs


# ── Tool simulations ──────────────────────────────────────────────────────────

def tool_search(query: str, system: str,
                grade: str | None = None, limit: int = 5) -> dict:
    rows, vecs = _load_system(system, grade)
    if not rows:
        return {"error": "no_standards_found", "system": system}
    scores = _rank(_embed(query), vecs)
    top = np.argsort(scores)[::-1][:limit]
    return {
        "query": query, "system": system, "grade": grade,
        "results": [
            {
                "id": rows[i]["id"],
                "grade": rows[i]["grade"],
                "domain": rows[i]["domain"],
                "standard_text": rows[i]["standard_text"],
                "score": round(float(scores[i]), 4),
            }
            for i in top
        ],
    }


def tool_lookup(standard_id: str) -> dict:
    conn = _db()
    row = conn.execute("SELECT * FROM standards WHERE id=?", (standard_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": "not_found", "id": standard_id}
    std = dict(row)
    subs = conn.execute(
        "SELECT id, text FROM sub_standards WHERE parent_id=? ORDER BY position",
        (standard_id,),
    ).fetchall()
    prereqs = [r[0] for r in conn.execute(
        "SELECT target_id FROM standard_relationships "
        "WHERE source_id=? AND relationship='prerequisite'", (standard_id,),
    ).fetchall()]
    succs = [r[0] for r in conn.execute(
        "SELECT target_id FROM standard_relationships "
        "WHERE source_id=? AND relationship='successor'", (standard_id,),
    ).fetchall()]
    conn.close()
    return {
        "id": std["id"], "system": std["system"], "grade": std["grade"],
        "domain": std["domain"], "cluster": std["cluster"],
        "standard_text": std["standard_text"],
        "sub_standards": [f"{r['id']} — {r['text']}" for r in subs],
        "prerequisites": prereqs, "successors": succs,
    }


def tool_progression(concept: str, system: str,
                     grade_start: int | None = None,
                     grade_end: int | None = None) -> dict:
    rows, vecs = _load_system(system)
    if not rows:
        return {"error": "no_standards", "system": system}
    scores = _rank(_embed(concept), vecs)
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
            by_grade[g] = {
                "id": r["id"], "grade": g,
                "text": r["standard_text"], "score": round(s, 4),
            }
    stages = sorted(
        by_grade.values(),
        key=lambda x: GRADE_ORDER.index(x["grade"]) if x["grade"] in GRADE_ORDER else 99,
    )
    return {"concept": concept, "system": system, "stages": stages}


def tool_map(source_id: str, from_system: str, to_system: str) -> dict:
    conn = _db()
    src = conn.execute("SELECT * FROM standards WHERE id=?", (source_id,)).fetchone()
    if not src:
        conn.close()
        return {"error": "source_not_found", "id": source_id}
    rows = conn.execute(
        """SELECT cm.target_id, cm.confidence_score, cm.grade_delta, s.standard_text, s.grade
           FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.target_id
           WHERE cm.source_id=? AND cm.target_system=?
           ORDER BY cm.confidence_score DESC LIMIT 5""",
        (source_id, to_system),
    ).fetchall()
    conn.close()
    return {
        "source_id": source_id,
        "source_text": src["standard_text"],
        "from_system": from_system, "to_system": to_system,
        "found": len(rows) > 0,
        "mappings": [
            {
                "target_id": r["target_id"],
                "target_text": r["standard_text"],
                "confidence": round(r["confidence_score"], 4),
                "grade_delta": r["grade_delta"],
            }
            for r in rows
        ],
    }


def tool_list_systems() -> dict:
    conn = _db()
    rows = conn.execute(
        "SELECT system, COUNT(*) AS n FROM standards GROUP BY system ORDER BY system"
    ).fetchall()
    conn.close()
    systems = {r["system"]: r["n"] for r in rows}
    return {
        "total_systems": len(systems),
        "total_standards": sum(systems.values()),
        "systems": systems,
    }


# ── Gemma judge ───────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating an educational standards database tool.

User: {persona}
Goal: {goal}
Tool: {tool}
Result (first 900 chars):
{output}

Does this result satisfy the user's goal?
Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _summarize_for_judge(result: dict, tool: str) -> str:
    """Return a judge-readable summary — avoids blind truncation of large outputs."""
    if tool == "list_systems" and "systems" in result:
        systems = result["systems"]
        key_present = {k: ("yes" if k in systems else "no")
                       for k in ("ccss", "sg-moe", "cambridge", "ib-myp", "ngss", "csta", "c3", "ccss-ela")}
        sample = dict(list(systems.items())[:30])
        return (
            f"total_systems: {result['total_systems']}, total_standards: {result['total_standards']}\n"
            f"Key systems present: {key_present}\n"
            f"First 30 systems (sample): {sample}"
        )
    return json.dumps(result, indent=2)[:1800]


def _call_judge(persona: str, goal: str, tool: str, result: dict,
                url: str = GEMMA_STUDIO_URL, model: str = GEMMA_STUDIO_MODEL) -> tuple[str, str]:
    snippet = _summarize_for_judge(result, tool)
    try:
        resp = httpx.post(url, json={
            "model": model,
            "prompt": _JUDGE_PROMPT.format(
                persona=persona, goal=goal, tool=tool, output=snippet,
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
    if first.startswith("YES"):
        return "YES", reason
    if first.startswith("PARTIAL"):
        return "PARTIAL", reason
    if first.startswith("NO"):
        return "NO", reason
    return "PARTIAL", raw  # ambiguous response


# ── Scenario definitions ──────────────────────────────────────────────────────

def _scenarios() -> list[dict]:
    return [
        # ── Alice: Texas Grade 4 math teacher ─────────────────────────────────
        {
            "persona": "Alice, a 4th-grade math teacher in Texas",
            "goal": "Find Grade 4 multiplication standards she needs to teach in TX TEKS",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "whole number multiplication arrays", "system": "tx", "grade": "4"},
            "check": lambda r: len(r.get("results", [])) >= 3,
            "check_desc": "≥3 TX Grade 4 results",
        },
        {
            "persona": "Alice, a 4th-grade math teacher in Texas",
            "goal": "Read the full text and sub-standards for TX.MATH.4.4.B",
            "tool": "lookup_standard",
            "fn": tool_lookup,
            "kwargs": {"standard_id": "TX.MATH.4.4.B"},
            "check": lambda r: "standard_text" in r and "error" not in r,
            "check_desc": "standard found with text",
        },
        {
            "persona": "Alice, a 4th-grade math teacher in Texas",
            "goal": "See how multiplication develops from Grade 3–5 in TX TEKS to plan her unit arc",
            "tool": "get_progression",
            "fn": tool_progression,
            "kwargs": {"concept": "multiplication whole numbers", "system": "tx",
                       "grade_start": 3, "grade_end": 5},
            "check": lambda r: len(r.get("stages", [])) >= 2,
            "check_desc": "progression spans ≥2 grades",
        },
        {
            "persona": "Alice, a 4th-grade math teacher in Texas",
            "goal": "Find the CCSS equivalent of TX.MATH.4.4.B to compare national alignment",
            "tool": "map_standard",
            "fn": tool_map,
            "kwargs": {"source_id": "TX.MATH.4.4.B", "from_system": "tx", "to_system": "ccss"},
            "check": lambda r: r.get("found", False),
            "check_desc": "crosswalk returns ≥1 CCSS match",
        },

        # ── Bob: Singapore EdTech PM ───────────────────────────────────────────
        {
            "persona": "Bob, a product manager at a Singapore EdTech company",
            "goal": "See all systems in the database including Singapore and international frameworks",
            "tool": "list_systems",
            "fn": tool_list_systems,
            "kwargs": {},
            "check": lambda r: "sg-moe" in r.get("systems", {}) and "cambridge" in r.get("systems", {}),
            "check_desc": "sg-moe and cambridge both present",
        },
        {
            "persona": "Bob, a product manager at a Singapore EdTech company",
            "goal": "Find Singapore Grade 7 ratio and proportion standards to tag his content library",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "ratio proportion rate speed", "system": "sg-moe", "grade": "7"},
            "check": lambda r: len(r.get("results", [])) >= 2,
            "check_desc": "≥2 SG Grade 7 ratio standards",
        },
        {
            "persona": "Bob, a product manager at a Singapore EdTech company",
            "goal": "Map SG_MOE.MATH.7.N7.7.2 to CCSS for US market alignment (expects conf ≥ 0.80)",
            "tool": "map_standard",
            "fn": tool_map,
            "kwargs": {"source_id": "SG_MOE.MATH.7.N7.7.2", "from_system": "sg-moe", "to_system": "ccss"},
            "check": lambda r: r.get("found") and r["mappings"][0]["confidence"] >= 0.80,
            "check_desc": "CCSS crosswalk with confidence ≥ 0.80",
        },
        {
            "persona": "Bob, a product manager at a Singapore EdTech company",
            "goal": "Understand how Singapore introduces algebra in Grades 6–8 to plan a content roadmap",
            "tool": "get_progression",
            "fn": tool_progression,
            "kwargs": {"concept": "algebra linear equations variables expressions", "system": "sg-moe",
                       "grade_start": 6, "grade_end": 8},
            "check": lambda r: len(r.get("stages", [])) >= 2,
            "check_desc": "progression spans ≥2 SG secondary grades",
        },

        # ── Carol: Comparative education researcher ────────────────────────────
        {
            "persona": "Carol, an education researcher comparing international curricula",
            "goal": "Find how Japan MEXT teaches fractions in Grade 4",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "fractions part whole division", "system": "jp-mext", "grade": "4"},
            "check": lambda r: len(r.get("results", [])) >= 1,
            "check_desc": "≥1 JP Grade 4 fraction standard",
        },
        {
            "persona": "Carol, an education researcher comparing international curricula",
            "goal": "Find how India NCERT teaches fractions in Grade 4",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "fractions part whole division", "system": "in-ncert", "grade": "4"},
            "check": lambda r: len(r.get("results", [])) >= 1,
            "check_desc": "≥1 IN Grade 4 fraction standard",
        },
        {
            "persona": "Carol, an education researcher comparing international curricula",
            "goal": "Find how Ghana NACCA teaches fractions (secondary level, DB has Gr 10-HS)",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "fractions decimals percentages", "system": "gh-nacca"},
            "check": lambda r: len(r.get("results", [])) >= 1,
            "check_desc": "≥1 GH fraction standard",
        },
        {
            "persona": "Carol, an education researcher comparing international curricula",
            "goal": "Get CCSS fractions progression Grades 3–5 as reference baseline for her comparison",
            "tool": "get_progression",
            "fn": tool_progression,
            "kwargs": {"concept": "fractions", "system": "ccss", "grade_start": 3, "grade_end": 5},
            "check": lambda r: len(r.get("stages", [])) >= 3,
            "check_desc": "CCSS progression covers all 3 grades (3, 4, 5)",
        },

        # ── Dave: Science curriculum coordinator ───────────────────────────────
        {
            "persona": "Dave, a K-12 science curriculum coordinator",
            "goal": "Find NGSS Grade 5 standards on food webs and energy flow in ecosystems",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "food webs energy flow ecosystems organisms", "system": "ngss", "grade": "5"},
            "check": lambda r: len(r.get("results", [])) >= 2,
            "check_desc": "≥2 NGSS Grade 5 life science standards",
        },
        {
            "persona": "Dave, a K-12 science curriculum coordinator",
            "goal": "See how evolution and natural selection builds K–12 in NGSS",
            "tool": "get_progression",
            "fn": tool_progression,
            "kwargs": {"concept": "evolution natural selection heredity traits", "system": "ngss"},
            "check": lambda r: len(r.get("stages", [])) >= 3,
            "check_desc": "evolution progression spans ≥3 grade bands",
        },
        {
            "persona": "Dave, a K-12 science curriculum coordinator",
            "goal": "Find AP Environmental Science standards on climate change to assess rigor",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "climate change greenhouse gases environmental impact", "system": "ap-env"},
            "check": lambda r: len(r.get("results", [])) >= 2,
            "check_desc": "≥2 AP Env Sci climate standards",
        },
        {
            "persona": "Dave, a K-12 science curriculum coordinator",
            "goal": "Map California Grade 5 science standard CA.SCI.5-PS3-1 to its NGSS equivalent",
            "tool": "map_standard",
            "fn": tool_map,
            "kwargs": {"source_id": "CA.SCI.5-PS3-1", "from_system": "ca-sci", "to_system": "ngss"},
            "check": lambda r: r.get("found", False),
            "check_desc": "CA→NGSS crosswalk returns a match",
        },

        # ── Emma: CS educator ──────────────────────────────────────────────────
        {
            "persona": "Emma, a middle school CS educator designing curriculum",
            "goal": "Find CSTA Grade 6-8 standards on loops, iteration, and algorithms",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "loops iteration algorithms programming", "system": "csta", "grade": "6"},
            "check": lambda r: len(r.get("results", [])) >= 2,
            "check_desc": "≥2 CSTA Grade 6-8 standards on programming",
        },
        {
            "persona": "Emma, a middle school CS educator designing curriculum",
            "goal": "See how computational thinking and decomposition builds K–12 in CSTA",
            "tool": "get_progression",
            "fn": tool_progression,
            "kwargs": {"concept": "computational thinking problem decomposition abstraction", "system": "csta"},
            "check": lambda r: len(r.get("stages", [])) >= 3,
            "check_desc": "CT progression spans ≥3 grade bands",
        },
        {
            "persona": "Emma, a middle school CS educator designing curriculum",
            "goal": "Map New Hampshire CS standard nh-cs.1A-CS-01 to its CSTA equivalent",
            "tool": "map_standard",
            "fn": tool_map,
            "kwargs": {"source_id": "nh-cs.1A-CS-01", "from_system": "nh-cs", "to_system": "csta"},
            "check": lambda r: r.get("found") and r["mappings"][0]["confidence"] >= 0.95,
            "check_desc": "NH→CSTA crosswalk with confidence ≥ 0.95",
        },
        {
            "persona": "Emma, a middle school CS educator designing curriculum",
            "goal": "Find Wisconsin CS standards on data privacy and cybersecurity",
            "tool": "search_standards",
            "fn": tool_search,
            "kwargs": {"query": "data privacy security personal information", "system": "wi-cs"},
            "check": lambda r: len(r.get("results", [])) >= 1,
            "check_desc": "≥1 WI CS privacy standard",
        },
    ]


# ── Runner ────────────────────────────────────────────────────────────────────

def main(no_judge: bool = False, local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL
    judge_label = f"gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"

    tests = _scenarios()
    n_yes = n_partial = n_no = n_llm_err = n_det_fail = n_tool_err = 0

    print("\n── Persona tests ────────────────────────────────────────────────────")
    if not no_judge:
        print(f"  Judge: {judge_label}")
    print(f"  {'#':<3} {'Persona':<30} {'Tool':<18} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*30} {'-'*18} {'----':>4} {'----':>4}")

    for i, t in enumerate(tests, 1):
        result: dict[str, Any] = {}
        error_msg = ""
        try:
            result = t["fn"](**t["kwargs"])
        except Exception as e:
            error_msg = str(e)

        det_pass = not error_msg and t["check"](result)
        det_tag = _OK if det_pass else (_ERR if error_msg else _FAIL)

        llm_verdict = ""
        llm_reason = ""
        llm_tag = _SKIP
        if not no_judge and not error_msg:
            llm_verdict, llm_reason = _call_judge(
                t["persona"], t["goal"], t["tool"], result,
                url=judge_url, model=judge_model,
            )
            llm_tag = (
                _OK   if llm_verdict == "YES"  else
                _PART if llm_verdict == "PARTIAL" else
                _ERR  if llm_verdict == "ERR"  else
                _FAIL
            )

        short_persona = t["persona"][:28] + ".." if len(t["persona"]) > 30 else t["persona"]
        print(f"  {i:<3} {short_persona:<30} {t['tool']:<18} [{det_tag}] [{llm_tag}]")

        if not det_pass or (llm_verdict and llm_verdict not in ("YES", "PARTIAL")):
            if error_msg:
                print(f"       ERROR: {error_msg}")
            elif not det_pass:
                print(f"       FAIL (det): {t['check_desc']}")
            if llm_reason:
                print(f"       LLM:  {llm_reason[:100]}")

        if error_msg:
            n_tool_err += 1
        elif not det_pass:
            n_det_fail += 1
        elif llm_verdict == "NO":
            n_no += 1
        elif llm_verdict == "PARTIAL":
            n_partial += 1
        elif llm_verdict == "ERR":
            n_llm_err += 1
        else:
            n_yes += 1  # YES or SKIP (no-judge)

    total = len(tests)
    if no_judge:
        print(f"\n  {total} tests — {n_yes} passed, {n_det_fail} det-fail, {n_tool_err} errors")
    else:
        print(f"\n  {total} tests — {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_llm_err} LLM-err")
        print(f"  Deterministic: {n_det_fail} fail, {n_tool_err} tool-errors")
    print()
    return 0 if (n_det_fail + n_tool_err) == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Persona-based eval with optional Gemma judge")
    p.add_argument("--no-judge", action="store_true", help="Skip LLM scoring (deterministic checks only)")
    p.add_argument("--local-judge", action="store_true", help="Use local Ollama (gemma4:26b) instead of Mac Studio")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
