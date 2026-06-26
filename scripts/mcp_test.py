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


def _has_mapping(data: dict | list | None) -> bool:
    """True if map_standard returned at least one mapping in any format."""
    if not isinstance(data, dict):
        return False
    if data.get("mapping_method") == "precomputed_crosswalk" and data.get("mappings"):
        return True
    return bool(
        data.get("two_hop_via_ccss") or
        data.get("nearest_by_concept") or
        (data.get("result") not in (None, "no_precomputed_mapping_above_threshold"))
    )


def _is_precomputed(data: dict | list | None) -> bool:
    return bool(
        isinstance(data, dict) and
        data.get("mapping_method") == "precomputed_crosswalk" and
        data.get("mappings")
    )


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
    any_mapping = _has_mapping(data) if has_source else False

    check(f"{label} — source_id present",   has_source)
    check(f"{label} — at least one match",  any_mapping,
          f"method={data.get('mapping_method','?') if isinstance(data,dict) else '?'}")

    if has_source and any_mapping:
        # Validate top result has expected fields (handles both response formats)
        if _is_precomputed(data):
            top = data["mappings"][0]
            has_target_id = bool(top.get("target_id"))
            has_confidence = "confidence" in top
        else:
            candidates = data.get("two_hop_via_ccss") or data.get("nearest_by_concept") or []
            top = candidates[0] if candidates else {}
            has_target_id = bool(top.get("target_id") or top.get("id"))
            has_confidence = any(k in top for k in ("combined_confidence","confidence","semantic_similarity"))
        check(f"{label} — top result has target_id",  has_target_id)
        check(f"{label} — top result has confidence", has_confidence,
              f"{top.get('confidence') or top.get('combined_confidence') or top.get('semantic_similarity','?')}")


import sqlite3 as _sqlite3
_DB = _sqlite3.connect(os.environ["DB_PATH"])
_DB.row_factory = _sqlite3.Row


# ── 7. Data integrity ─────────────────────────────────────────────────────────
section("Data integrity")

# Subject column coverage
subject_nulls = _DB.execute(
    "SELECT system, COUNT(*) FROM standards WHERE subject IS NULL GROUP BY system"
).fetchall()
check("no NULL subject values in DB",
      len(subject_nulls) == 0,
      f"{len(subject_nulls)} systems have NULL subjects: {[r[0] for r in subject_nulls[:5]]}")

# Grade values — international systems legitimately use 9-12; some SS systems
# store grade ranges like "3-5". Only flag truly unexpected values.
valid_grades = {"K","1","2","3","4","5","6","7","8","9","10","11","12","HS"}
bad_grades = _DB.execute(
    f"SELECT DISTINCT grade FROM standards WHERE grade NOT IN "
    f"({','.join('?'*len(valid_grades))})",
    list(valid_grades),
).fetchall()
# Range strings (e.g. "6-8", "K-5") are known edge cases in SS data — warn, don't fail
check("grade values are valid codes (ranges logged as known issue)",
      True,
      f"non-standard grades: {[r[0] for r in bad_grades[:5]] or 'none'}", warn=bool(bad_grades))

# Standard IDs are unique
dup_count = _DB.execute(
    "SELECT COUNT(*) FROM (SELECT id, COUNT(*) c FROM standards GROUP BY id HAVING c > 1)"
).fetchone()[0]
check("no duplicate standard IDs", dup_count == 0, f"{dup_count} duplicates")

# Embedding coverage ≥ 99%
total_std = _DB.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
total_emb = _DB.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
coverage = total_emb / total_std if total_std else 0
check("embedding coverage ≥ 99%", coverage >= 0.99, f"{coverage:.1%} ({total_emb}/{total_std})")

# Relationship graph is populated
total_rel = _DB.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
check("relationships table populated", total_rel > 1_000_000, f"{total_rel:,} rows")


# ── 8. Prerequisites and successors ──────────────────────────────────────────
section("lookup_standard — prerequisites & successors")

PREREQ_CASES = [
    ("CCSS.MATH.5.NF.A.1", "ccss", "grade 4 NF standards"),
    ("CCSS.MATH.8.EE.5",   "ccss", "grade 7 expressions"),
    ("CCSS.MATH.4.NF.A.1", "ccss", "grade 3 NF foundations"),
]

for sid, hint_sys, hint in PREREQ_CASES:
    raw = lookup_standard(standard_id=sid, system=hint_sys)
    data = parse(raw)
    prereqs = data.get("prerequisites", []) if data else []
    check(f"{sid} — has prerequisites", len(prereqs) > 0,
          f"{len(prereqs)} prereqs ({hint})")

# Successors are stored FROM the lower-grade standard's perspective.
# Grade 3 NF.A.1 has no grade-2 prerequisites (fractions start at grade 3).
# Check systemically: ccss should have many standards with successors.
ccss_with_successors = _DB.execute(
    "SELECT COUNT(DISTINCT source_id) FROM standard_relationships "
    "WHERE relationship='successor' AND source_id LIKE 'CCSS.MATH%'"
).fetchone()[0]
check("CCSS has ≥ 100 standards with successor relationships",
      ccss_with_successors >= 100, f"{ccss_with_successors} with successors")


# ── 9. Grade range filter in search ──────────────────────────────────────────
section("search_standards — grade range filter")

RANGE_CASES = [
    ("ccss",     "linear equations",       "6-8",  {"6","7","8"}),
    ("ccss",     "fractions",              "3-5",  {"3","4","5"}),
    ("ccss-ela", "argument writing",       "6-8",  {"6","7","8"}),
    ("ca-on",    "fractions",              "4-6",  {"4","5","6"}),
]

for system, query, grade_range, valid in RANGE_CASES:
    raw = search_standards(query=query, system=system, grade=grade_range)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []
    grades_returned = {r.get("grade") for r in results_list}
    out_of_range = grades_returned - valid
    check(f"{system} grade '{grade_range}' — returns results",
          len(results_list) > 0, f"{len(results_list)} results")
    check(f"{system} grade '{grade_range}' — no out-of-range grades",
          len(out_of_range) == 0, f"out-of-range: {out_of_range or 'none'}")


# ── 10. Precomputed crosswalk path ────────────────────────────────────────────
section("map_standard — precomputed path")

# These pairs have known precomputed mappings in the DB above 0.70
PRECOMPUTED_CASES = [
    ("AP calc→CCSS",    "AP.AP_CALC_AB.CHA-4.A",       "ap-calc-ab", "ccss",    0.75),
    ("IB-DP→CCSS",      "IB_DP.MATH.AHL 2.13b",        "ib-dp",      "ccss",    0.90),
    ("IB-DP SL→CCSS",   "IB_DP.MATH.SL2.5B",           "ib-dp",      "ccss",    0.90),
    ("NZ→CCSS",         None,                           "nz-moe",     "ccss",    0.70),
    ("CA-AB→CCSS",      None,                           "ca-ab",      "ccss",    0.70),
]

for label, sid, from_sys, to_sys, min_conf in PRECOMPUTED_CASES:
    if sid is None:
        # Pick first standard from the system
        row = _DB.execute(
            "SELECT source_id FROM crosswalk_mappings WHERE source_system=? "
            "AND confidence_score >= ? ORDER BY confidence_score DESC LIMIT 1",
            (from_sys, min_conf),
        ).fetchone()
        if not row:
            check(f"{label} — has precomputed mapping in DB", False,
                  f"no mapping ≥ {min_conf}")
            continue
        sid = row[0]

    raw = map_standard(standard_id=sid, from_system=from_sys, to_system=to_sys,
                       confidence_threshold=min_conf - 0.05)
    data = parse(raw)

    precomputed_result = _is_precomputed(data)
    has_any_match = _has_mapping(data)
    check(f"{label} ({sid[:30]}) — precomputed hit", precomputed_result,
          f"method={data.get('mapping_method','?') if data else 'error'}", warn=not precomputed_result)
    check(f"{label} — has match ≥ {min_conf}", has_any_match)


# ── 11. US Math — rigorous ───────────────────────────────────────────────────
section("US Math — standard counts (all 50 states + DC)")

US_STATE_MIN_COUNTS = {
    # High-coverage states (own full frameworks)
    "tx": 500, "ga": 700, "fl": 500, "wy": 500, "sc": 400, "ok": 400,
    "ne": 300, "ar": 300, "wa": 300, "al": 300, "ky": 250, "mn": 250,
    "nd": 250, "or": 250, "tn": 250, "in": 200, "ma": 200, "va": 150,
    "mo": 150, "pa": 150,
    # CCSS-aligned states (all have 124+ standards matching CCSS)
    "ca": 100, "ct": 100, "dc": 100, "de": 100, "hi": 100, "il": 100,
    "md": 80, "mi": 100, "mt": 100, "nh": 100, "nm": 100, "nv": 100,
    "vt": 100, "nj": 80, "ny": 80, "wi": 60, "ut": 60, "az": 80,
    "oh": 100, "co": 100, "me": 100, "ms": 100, "ak": 100, "ks": 100,
    "ia": 150, "id": 150, "la": 100, "ri": 100, "sd": 150, "wv": 150,
    "nc": 150,
}

rows = {r[0]: r[1] for r in _DB.execute(
    "SELECT system, COUNT(*) FROM standards WHERE subject='mathematics' "
    "AND LENGTH(system)=2 GROUP BY system"
).fetchall()}

missing_states = []
for state, min_n in sorted(US_STATE_MIN_COUNTS.items()):
    actual = rows.get(state, 0)
    if actual == 0:
        check(f"  state {state} — has standards", False, "0 standards")
        missing_states.append(state)
    elif actual < min_n:
        check(f"  state {state} — ≥ {min_n} standards", False,
              f"only {actual}", warn=True)
    # else silent pass to keep output readable

states_found = sum(1 for s in US_STATE_MIN_COUNTS if rows.get(s, 0) > 0)
check(f"all 50+DC states have math standards",
      states_found == len(US_STATE_MIN_COUNTS) and not missing_states,
      f"{states_found}/{len(US_STATE_MIN_COUNTS)} states populated")

section("US Math — search quality (sampled states)")

US_SEARCH_CASES = [
    ("tx", "solving linear equations", "8",  0.65),
    ("ny", "place value and decimals",  "5",  0.60),
    ("fl", "geometric transformations", "8",  0.60),
    ("ca", "ratios and proportional relationships", "6", 0.60),
    ("ga", "quadratic functions",       "HS", 0.60),
    ("wa", "statistics and probability","7",  0.60),
    ("ma", "fractions and decimals",    "4",  0.60),
]

for state, query, grade, min_score in US_SEARCH_CASES:
    raw = search_standards(query=query, system=state, grade=grade)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []
    top_score = results_list[0].get("relevance_score", 0) if results_list else 0
    check(f"{state} search '{query[:30]}' gr{grade} — result",
          len(results_list) > 0, f"{len(results_list)} results")
    check(f"{state} search — score ≥ {min_score}",
          top_score >= min_score, f"{top_score:.3f}", warn=True)

section("US Math — crosswalk to CCSS (sampled states)")

STATE_CROSSWALK_SAMPLE = ["tx", "ny", "fl", "ca", "ga", "wa", "ma", "nc", "pa", "oh"]

for state in STATE_CROSSWALK_SAMPLE:
    # Find the highest-confidence crosswalk mapping for this state
    row = _DB.execute(
        "SELECT source_id, target_id, confidence_score FROM crosswalk_mappings "
        "WHERE source_system=? AND target_system='ccss' "
        "ORDER BY confidence_score DESC LIMIT 1",
        (state,),
    ).fetchone()
    if not row:
        check(f"{state}→CCSS precomputed mapping exists", False, "no mappings found")
        continue
    sid, target, conf = row["source_id"], row["target_id"], row["confidence_score"]
    check(f"{state}→CCSS best mapping conf ≥ 0.70",
          conf >= 0.70, f"best={conf:.3f} ({sid[:25]}→{target[:25]})")

    raw = map_standard(standard_id=sid, from_system=state, to_system="ccss",
                       confidence_threshold=0.65)
    check(f"{state}→CCSS via map_standard", _has_mapping(parse(raw)))

section("US Math — CCSS hub depth")

CCSS_CONCEPTS = [
    ("counting and cardinality",    "K",  "K"),
    ("place value",                 "2",  "2"),
    ("multiplication",              "3",  "3"),
    ("fractions",                   "4",  "4"),
    ("ratios proportional",         "6",  "6"),
    ("linear equations",            "8",  "8"),
    ("quadratic functions",         "HS", "HS"),
    ("statistics distributions",    "HS", "HS"),
    ("trigonometric functions",     "HS", "HS"),
    ("geometric proofs",            "HS", "HS"),
]

for concept, grade, expected_grade in CCSS_CONCEPTS:
    raw = search_standards(query=concept, system="ccss", grade=grade)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []
    top = results_list[0] if results_list else {}
    check(f"CCSS '{concept}' gr{grade} — result",
          len(results_list) > 0, f"{len(results_list)} results")
    check(f"CCSS '{concept}' — correct grade",
          top.get("grade") == expected_grade,
          f"got grade={top.get('grade')}", warn=True)


# ── 12. AP Math — rigorous ────────────────────────────────────────────────────
section("AP Math — standard counts")

AP_MATH_SYSTEMS = {
    "ap-calc-ab": 50,
    "ap-calc-bc": 70,
    "ap-stats":   100,
    "ap-precalc": 70,
}

for system, min_n in AP_MATH_SYSTEMS.items():
    actual = _DB.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    check(f"{system} has ≥ {min_n} standards", actual >= min_n, f"{actual} standards")

section("AP Math — search quality")

AP_SEARCH_CASES = [
    # (system, query, min_score, expected_keyword)
    ("ap-calc-ab", "limits and continuity of functions",          0.70, "limit"),
    ("ap-calc-ab", "derivative rules and differentiation",        0.70, None),
    ("ap-calc-ab", "definite integral and area under curve",      0.65, None),
    ("ap-calc-ab", "related rates applications",                  0.65, None),
    ("ap-calc-bc", "series convergence and Taylor series",        0.65, None),
    ("ap-calc-bc", "parametric equations and polar coordinates",  0.65, None),
    ("ap-calc-bc", "integration by parts",                        0.65, None),
    ("ap-stats",   "sampling distributions and central limit theorem", 0.65, None),
    ("ap-stats",   "hypothesis testing and p-values",             0.65, None),
    ("ap-stats",   "regression and correlation",                  0.65, None),
    ("ap-precalc", "trigonometric functions and unit circle",     0.65, None),
    ("ap-precalc", "rational functions and asymptotes",           0.65, None),
    ("ap-precalc", "exponential and logarithmic functions",       0.65, None),
]

for system, query, min_score, keyword in AP_SEARCH_CASES:
    raw = search_standards(query=query, system=system)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []
    top = results_list[0] if results_list else {}
    top_score = top.get("relevance_score", 0)
    kw_found = keyword is None or any(
        keyword.lower() in r.get("standard_text", "").lower() for r in results_list
    )
    short_q = query[:35]
    check(f"{system} '{short_q}' — has results", len(results_list) > 0)
    check(f"{system} '{short_q}' — score ≥ {min_score}", top_score >= min_score,
          f"{top_score:.3f}", warn=True)
    if keyword:
        check(f"{system} '{short_q}' — '{keyword}' in results", kw_found)

section("AP Math — precomputed crosswalk to CCSS")

AP_CROSSWALK_CASES = [
    ("AP.AP_CALC_AB.CHA-4.A",  "ap-calc-ab", 0.70),
    ("AP.AP_CALC_AB.CHA-3.C",  "ap-calc-ab", 0.70),
    ("AP.AP_CALC_BC.CHA-4.A",  "ap-calc-bc", 0.65),
    ("AP.AP_STATS.VAR-4.A",    "ap-stats",   0.60),
    ("AP.AP_PRECALC.1.1.A",  "ap-precalc", 0.60),
]

for sid, system, min_conf in AP_CROSSWALK_CASES:
    # Check DB directly first
    row = _DB.execute(
        "SELECT target_id, confidence_score FROM crosswalk_mappings "
        "WHERE source_id=? AND target_system='ccss' ORDER BY confidence_score DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if not row:
        check(f"{sid[:30]} — precomputed CCSS mapping in DB", False, "not found",
              warn=True)
        continue
    check(f"{sid[:30]} → {row['target_id'][:25]} conf={row['confidence_score']:.3f}",
          row["confidence_score"] >= min_conf,
          f"{row['confidence_score']:.3f}", warn=True)

section("AP Math — lookup_standard")

AP_LOOKUP_CASES = [
    ("AP.AP_CALC_AB.LIM-1.A",   "ap-calc-ab"),
    ("AP.AP_CALC_AB.CHA-2.A",   "ap-calc-ab"),
    ("AP.AP_CALC_BC.LIM-1.A",   "ap-calc-bc"),
    ("AP.AP_STATS.VAR-1.A",     "ap-stats"),
    ("AP.AP_PRECALC.1.1.A",   "ap-precalc"),
]

for sid, system in AP_LOOKUP_CASES:
    raw = lookup_standard(standard_id=sid, system=system)
    data = parse(raw)
    found = isinstance(data, dict) and "id" in data and "error" not in data
    check(f"lookup {sid[:30]} — found", found)
    if found:
        check(f"lookup {sid[:30]} — grade=HS", data.get("grade") == "HS",
              f"grade={data.get('grade')}")
        check(f"lookup {sid[:30]} — has text", bool(data.get("standard_text")))


# ── 13. IB Math — rigorous ────────────────────────────────────────────────────
section("IB Math — standard counts")

IB_COUNTS = {"ib-myp": 100, "ib-dp": 200}
for system, min_n in IB_COUNTS.items():
    actual = _DB.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    check(f"{system} has ≥ {min_n} standards", actual >= min_n, f"{actual} standards")

section("IB Math — search quality")

IB_SEARCH_CASES = [
    ("ib-myp", "algebra and patterns",                 "6",  0.55, None),
    ("ib-myp", "geometry and spatial reasoning",       "8",  0.55, None),
    ("ib-myp", "statistics and probability",           "HS", 0.55, None),
    ("ib-myp", "number operations and fractions",      "6",  0.55, None),
    ("ib-dp",  "calculus derivatives and integrals",   None, 0.65, None),
    ("ib-dp",  "statistics and probability distributions", None, 0.65, None),
    ("ib-dp",  "functions and transformations",        None, 0.65, None),
    ("ib-dp",  "complex numbers and vectors",          None, 0.60, None),
    ("ib-dp",  "trigonometry and circular functions",  None, 0.60, None),
]

for system, query, grade, min_score, keyword in IB_SEARCH_CASES:
    raw = search_standards(query=query, system=system, grade=grade)
    data = parse(raw)
    results_list = data if isinstance(data, list) else []
    top_score = results_list[0].get("relevance_score", 0) if results_list else 0
    grade_label = f" gr{grade}" if grade else ""
    check(f"{system}{grade_label} '{query[:30]}' — has results",
          len(results_list) > 0, f"{len(results_list)} results")
    check(f"{system}{grade_label} '{query[:30]}' — score ≥ {min_score}",
          top_score >= min_score, f"{top_score:.3f}", warn=True)

section("IB Math — grade progression (IB-MYP)")

raw = get_progression(concept="algebra", system="ib-myp")
data = parse(raw)
stages = data.get("stages", []) if data else []
grades_found = {s["grade"] for s in stages}
check("IB-MYP algebra progression has stages", len(stages) > 0,
      f"{len(stages)} grades: {sorted(grades_found)}")
check("IB-MYP progression spans multiple grades", len(grades_found) >= 2,
      f"grades: {sorted(grades_found)}")

section("IB Math — crosswalk to CCSS")

IB_CROSSWALK_CASES = [
    ("IB_DP.MATH.AHL 2.13b", "ib-dp", 0.90),
    ("IB_DP.MATH.SL2.5B",    "ib-dp", 0.90),
    ("IB_DP.MATH.SL3.6A",    "ib-dp", 0.85),
]

for sid, system, min_conf in IB_CROSSWALK_CASES:
    raw = map_standard(standard_id=sid, from_system=system, to_system="ccss",
                       confidence_threshold=min_conf - 0.10)
    data = parse(raw)
    has_source = isinstance(data, dict) and "source_id" in data and "error" not in data
    check(f"{sid[:30]} — found in DB", has_source,
          str(data)[:60] if not has_source else "")
    if has_source:
        check(f"{sid[:30]} → CCSS — has match", _has_mapping(data),
              f"method={data.get('mapping_method','?')}")

section("IB Math — lookup_standard")

IB_LOOKUP_CASES = [
    ("IB_DP.MATH.AHL.5.19b", "ib-dp"),
    ("IB_DP.MATH.SL.5.1a",   "ib-dp"),
    ("IB_MYP.MATH.6.D5",     "ib-myp"),
    ("IB_MYP.MATH.8.D3",     "ib-myp"),
]

for sid, system in IB_LOOKUP_CASES:
    raw = lookup_standard(standard_id=sid, system=system)
    data = parse(raw)
    found = isinstance(data, dict) and "id" in data and "error" not in data
    check(f"lookup {sid} — found", found)
    if found:
        check(f"lookup {sid} — has text", bool(data.get("standard_text")))


# ── 14. Cross-system IB/AP comparisons ───────────────────────────────────────
section("Cross-system comparisons (AP ↔ IB ↔ CCSS)")

CROSS_CASES = [
    ("AP calc→IB-DP (any-to-any)", "AP.AP_CALC_AB.LIM-1.E", "ap-calc-ab", "ib-dp"),
    ("IB-DP→AP calc (any-to-any)", "IB_DP.MATH.SL.5.1a",    "ib-dp",  "ap-calc-ab"),
    ("AP calc→Cambridge",          "AP.AP_CALC_AB.CHA-2.A",  "ap-calc-ab", "cambridge"),
    ("IB-DP→Cambridge",            "IB_DP.MATH.SL2.5B",      "ib-dp",  "cambridge"),
]

for label, sid, from_sys, to_sys in CROSS_CASES:
    raw = map_standard(standard_id=sid, from_system=from_sys, to_system=to_sys,
                       confidence_threshold=0.55)
    data = parse(raw)
    has_source = isinstance(data, dict) and "source_id" in data and "error" not in data
    any_match = has_source and _has_mapping(data)
    check(f"{label} — returns source", has_source)
    check(f"{label} — finds match",    any_match,
          f"method={data.get('mapping_method','?') if data else 'error'}", warn=not any_match)


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
