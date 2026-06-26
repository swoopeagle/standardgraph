#!/usr/bin/env python3
"""MCP tool test suite — validates all five tools across all subjects.

Tests are run by importing server functions directly (no MCP protocol overhead).
Usage: DB_PATH=~/.standardgraph/common_core.db uv run python scripts/mcp_test.py

Exit 0 = all tests passed. Exit 1 = one or more failures.
"""
import json
import os
import sys
import time
from pathlib import Path

# Point at the user DB unless overridden
os.environ.setdefault("DB_PATH", str(Path.home() / ".standardgraph" / "common_core.db"))

# Insert package onto path for direct import
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "common-core" / "src"))

from common_core.server import (
    lookup_standard,
    search_standards,
    get_progression,
    map_standard,
    list_systems,
)

# ── Colour helpers ─────────────────────────────────────────────────────────────
OK   = "\033[32m PASS \033[0m"
FAIL = "\033[31m FAIL \033[0m"
WARN = "\033[33m WARN \033[0m"
SKIP = "\033[90m SKIP \033[0m"

results: list[tuple[str, str, str]] = []   # (label, status, detail)


def check(label: str, expr: bool, detail: str = "", warn: bool = False) -> bool:
    tag = (WARN if warn else FAIL) if not expr else OK
    results.append((label, tag, detail))
    print(f"  [{tag}] {label}" + (f"  — {detail}" if detail else ""))
    return expr


def section(title: str) -> None:
    print(f"\n── {title} {'─' * (58 - len(title))}")


def parse(raw: str) -> dict | list | None:
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── 1. list_systems ────────────────────────────────────────────────────────────
section("list_systems")

# Unfiltered — should work but may be large
t0 = time.time()
raw_ls = list_systems()
elapsed = time.time() - t0
data_ls = parse(raw_ls)

systems_list = data_ls.get("systems", []) if isinstance(data_ls, dict) else []
system_codes = {s["system"] for s in systems_list if isinstance(s, dict)}
sg_moe = next((s for s in systems_list if s.get("system") == "sg-moe"), {})

check("returns valid JSON",           data_ls is not None)
check("contains 'systems' key",       isinstance(data_ls, dict) and "systems" in data_ls)
check("298+ systems listed",          len(systems_list) >= 298, f"{len(systems_list)} systems")
check("ca-on present",                "ca-on" in system_codes)
check("sg-moe has ≥ 285 standards",   sg_moe.get("standards", 0) >= 285,
      f"{sg_moe.get('standards','?')}")
check("response time < 5s (cold DB)",  elapsed < 5, f"{elapsed:.2f}s", warn=True)
check("unfiltered response size noted", True, f"{len(raw_ls):,} chars (unfiltered)", warn=True)

# Filtered — this is the machine-friendly path; must be small
raw_math = list_systems(subject="mathematics", region="North America")
data_math = parse(raw_math)
math_systems = data_math.get("systems", []) if isinstance(data_math, dict) else []
check("filtered (math + N.America) under 15k chars", len(raw_math) < 15000,
      f"{len(raw_math):,} chars")
check("filtered result contains ccss", any(s["system"] == "ccss" for s in math_systems))
check("filtered result contains ca-on", any(s["system"] == "ca-on" for s in math_systems))
check("filtered result excludes sg-moe", not any(s["system"] == "sg-moe" for s in math_systems))

raw_sci = list_systems(subject="science")
check("science filter returns ngss",
      any(s.get("system") == "ngss"
          for s in (parse(raw_sci) or {}).get("systems", [])))


# ── 2. search_standards — coverage across subjects ─────────────────────────────
section("search_standards — subject coverage")

SEARCH_CASES = [
    # (label, query, system, grade, min_score, expected_keyword)
    ("math CCSS — fractions",          "adding fractions with unlike denominators",      "ccss",    "5",  0.75, "fraction"),
    ("math Ontario K-8",               "adding fractions with unlike denominators",      "ca-on",   None, 0.75, "fraction"),
    ("math Singapore",                 "multiplication of whole numbers",                "sg-moe",  None, 0.65, None),
    ("science NGSS — photosynthesis",  "photosynthesis and cellular respiration",        "ngss",    None, 0.60, None),
    ("ELA CCSS — argument writing",    "writing arguments with evidence",                "ccss-ela","8",  0.60, None),
    ("social studies C3",              "civic participation and democratic institutions","c3",       None, 0.60, None),
    ("CS CSTA — algorithms",           "algorithm design and problem decomposition",     "csta",    None, 0.60, None),
    ("international — Cambridge",      "quadratic equations",                            "cambridge",None,0.60, None),
    ("AP — AP Calculus AB",            "limits and continuity",                          "ap-calc-ab",None,0.60,None),
]

for label, query, system, grade, min_score, keyword in SEARCH_CASES:
    raw = search_standards(query=query, system=system, grade=grade)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []

    has_results = len(results_list) > 0
    top_score   = results_list[0].get("relevance_score", 0) if results_list else 0
    has_ids     = all("id" in r and "standard_text" in r for r in results_list)
    kw_found    = keyword is None or any(
        keyword.lower() in r.get("standard_text", "").lower() for r in results_list
    )

    check(f"{label} — returns results",    has_results, f"{len(results_list)} results")
    check(f"{label} — top score ≥ {min_score}", top_score >= min_score,
          f"{top_score:.3f}", warn=True)
    check(f"{label} — has id + text",      has_ids)
    if keyword:
        check(f"{label} — keyword '{keyword}' present", kw_found)


# ── 3. search_standards — edge cases ──────────────────────────────────────────
section("search_standards — edge cases")

# Unknown system
raw = search_standards(query="fractions", system="xx-fake")
data = parse(raw)
check("invalid system returns error or empty list",
      isinstance(data, dict) and "error" in data or data == [],
      f"got: {str(data)[:80]}")

# Grade filter respected
raw = search_standards(query="fractions", system="ccss", grade="3")
data = parse(raw)
results_list = data if isinstance(data, list) else []
grade_ok = all(r.get("grade") == "3" for r in results_list) if results_list else False
check("grade filter returns grade-3 only", grade_ok,
      f"grades: {[r.get('grade') for r in results_list]}")

# FTS fallback (no Ollama needed — test with a very specific phrase)
raw = search_standards(query="equivalent fractions number line", system="ccss", grade="3")
data = parse(raw)
check("FTS fallback returns ≥1 result",
      isinstance(data, list) and len(data) >= 1,
      f"{len(data) if isinstance(data, list) else 'error'} results")


# ── 4. get_progression ────────────────────────────────────────────────────────
section("get_progression")

PROGRESSION_CASES = [
    ("fractions CCSS gr 3-6",  "fractions",         "ccss",    3, 6, ["3","4","5","6"]),
    ("place value CCSS K-5",   "place value",        "ccss",    None, 5, ["K","1","2","3","4","5"]),
    ("Ontario fractions",       "fractions",         "ca-on",   3, 7, ["3","4","5","6","7"]),
    ("linear equations CCSS",  "linear equations",   "ccss",    6, 8, ["6","7","8"]),
    ("writing CCSS-ELA",       "argumentative writing","ccss-ela",6,8, ["6","7","8"]),
]

for label, concept, system, g_start, g_end, expected_grades in PROGRESSION_CASES:
    raw = get_progression(concept=concept, system=system, grade_start=g_start, grade_end=g_end)
    data = parse(raw)

    has_stages = isinstance(data, dict) and "stages" in data and len(data["stages"]) > 0
    actual_grades = [s["grade"] for s in data.get("stages", [])] if has_stages else []
    has_expected = any(g in actual_grades for g in expected_grades) if has_stages else False

    check(f"{label} — has stages", has_stages, f"{len(actual_grades)} grades")
    check(f"{label} — expected grades present", has_expected,
          f"got {actual_grades}, expected some of {expected_grades}")
    if has_stages:
        has_text = all("standards" in s and s["standards"] for s in data["stages"])
        check(f"{label} — each stage has standards", has_text)


# ── 5. lookup_standard ────────────────────────────────────────────────────────
section("lookup_standard")

LOOKUP_CASES = [
    ("CCSS fractions shortform",  "5.NF.A.1",                  "ccss",    True),
    ("CCSS full ID",              "CCSS.MATH.5.NF.A.1",        "ccss",    True),
    ("Texas math",                "TX.MATH.5.3.K",             "tx",      True),
    ("Ontario K-8",               "CA-ON.MATH.5.5.B2.5",       "ca-on",   True),
    ("Ontario HS",                "CA-ON.MATH.HS.9.E1.4",      "ca-on",   True),
    ("Singapore",                 "SG_MOE.MATH.5.NA",          "sg-moe",  None),  # may not exist exactly
    ("ELA standard",              "CCSS.ELA.3.W.1",            "ccss-ela",None),  # try
    ("invalid ID",                "ZZZZ.FAKE.9.9.9",           "ccss",    False),
]

for label, sid, system, expect_found in LOOKUP_CASES:
    raw = lookup_standard(standard_id=sid, system=system)
    data = parse(raw)

    if expect_found is True:
        found = isinstance(data, dict) and "id" in data and "error" not in data
        has_text = found and bool(data.get("standard_text"))
        has_grade = found and bool(data.get("grade"))
        check(f"{label} — found",           found,    sid)
        if found:
            check(f"{label} — has text",    has_text)
            check(f"{label} — has grade",   has_grade)
    elif expect_found is False:
        error_returned = isinstance(data, dict) and "error" in data
        check(f"{label} — returns error",   error_returned,
              f"got: {str(data)[:80]}")
    else:
        found = isinstance(data, dict) and "error" not in data
        check(f"{label} — handled gracefully (found={found})", True,
              f"{'found' if found else 'not found'}", warn=True)


# ── 6. map_standard ───────────────────────────────────────────────────────────
section("map_standard")

MAP_CASES = [
    # (label, standard_id, from_system, to_system, expect_mapping)
    ("CCSS→Ontario (fraction)",   "CCSS.MATH.5.NF.A.1", "ccss", "ca-on",   True),
    ("CCSS→Singapore",            "CCSS.MATH.5.NF.A.1", "ccss", "sg-moe",  True),
    ("CCSS→Cambridge",            "CCSS.MATH.8.EE.5",  "ccss", "cambridge",True),
    ("Texas→Ontario (any-to-any)","TX.MATH.5.3.K",      "tx",   "ca-on",   True),
    ("CCSS→NGSS (cross-subject)", "CCSS.MATH.5.NF.A.1", "ccss", "ngss",    None),
    ("invalid ID",                "ZZZZ.FAKE.9.9.9",    "ccss", "ca-on",   False),
]

for label, sid, from_sys, to_sys, expect_mapping in MAP_CASES:
    raw = map_standard(standard_id=sid, from_system=from_sys, to_system=to_sys)
    data = parse(raw)

    if expect_mapping is False:
        error_or_empty = (
            isinstance(data, dict) and (
                "error" in data or
                not (data.get("two_hop_via_ccss") or data.get("nearest_by_concept"))
            )
        )
        check(f"{label} — graceful failure", error_or_empty, f"{str(data)[:80]}")
        continue

    if expect_mapping is None:
        handled = isinstance(data, dict) and "source_id" in data
        check(f"{label} — handled (result may be empty)", handled,
              str(data.get("result", ""))[:60], warn=True)
        continue

    has_source = isinstance(data, dict) and data.get("source_id") == sid
    any_mapping = bool(
        data.get("two_hop_via_ccss") or
        data.get("nearest_by_concept") or
        (data.get("result") not in (None, "no_precomputed_mapping_above_threshold"))
    ) if has_source else False

    check(f"{label} — source_id present",   has_source)
    check(f"{label} — at least one match",  any_mapping,
          f"result={data.get('result','?') if isinstance(data,dict) else '?'}")

    if has_source and any_mapping:
        # Validate top result has expected fields
        candidates = (
            data.get("two_hop_via_ccss") or data.get("nearest_by_concept") or []
        )
        top = candidates[0] if candidates else {}
        has_target_id = bool(top.get("target_id") or top.get("id"))
        has_confidence = (
            "combined_confidence" in top or
            "confidence" in top or
            "semantic_similarity" in top
        )
        check(f"{label} — top result has target_id",  has_target_id)
        check(f"{label} — top result has confidence", has_confidence,
              f"{top.get('combined_confidence') or top.get('semantic_similarity','?')}")


# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═' * 64}")
passed  = sum(1 for _, tag, _ in results if "PASS" in tag)
failed  = sum(1 for _, tag, _ in results if "FAIL" in tag)
warned  = sum(1 for _, tag, _ in results if "WARN" in tag)
total   = len(results)

print(f"  Results: {passed} passed  |  {failed} failed  |  {warned} warnings  |  {total} total")

if failed:
    print(f"\n  Failed checks:")
    for label, tag, detail in results:
        if "FAIL" in tag:
            print(f"    ✗  {label}" + (f" — {detail}" if detail else ""))

print()
sys.exit(1 if failed else 0)
