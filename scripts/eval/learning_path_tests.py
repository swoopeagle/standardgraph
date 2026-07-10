#!/usr/bin/env python3
"""Eval for the get_learning_path MCP tool (prereq-graph pilot, Phase 4/5).

Imports the server directly (no MCP protocol), same style as scripts/mcp_test.py.
Run against the pilot scratch DB:

    DB_PATH=.../prereq_pilot.db uv run python scripts/eval/learning_path_tests.py

Asserts the structural contract of get_learning_path + lookup_standard(prefer_validated):
  - a path is returned target-last, strictly grade-non-decreasing (valid topo order)
  - the target is always the final node
  - every in-path prerequisite edge points to an earlier (lower-or-equal-grade) node
  - include_soft never shrinks the path
  - from_standard pruning yields a contiguous chain that starts at from_standard
  - at least one known cross-domain path is present (the pilot's whole point)
  - lookup_standard reports prerequisites_method and prefers validated when present
"""
import json
import sys

from common_core.server import get_learning_path, lookup_standard, _grade_key

PASS = "\033[32m PASS \033[0m"
FAIL = "\033[31m FAIL \033[0m"
_n_pass = 0
_n_fail = 0


def check(label, cond, detail=""):
    global _n_pass, _n_fail
    tag = PASS if cond else FAIL
    if cond:
        _n_pass += 1
    else:
        _n_fail += 1
    print(f"  [{tag}] {label}" + (f"  — {detail}" if detail else ""))


def gp(**kw):
    return json.loads(get_learning_path(**kw))


def section(t):
    print(f"\n── {t} " + "─" * max(0, 52 - len(t)))


# Targets spanning the grade band + cross-domain cases.
CHAINS = [
    "CCSS.MATH.5.NF.B.7.b",   # fraction division (crosses Geometry→NF)
    "CCSS.MATH.HSF.LE.A.1.b",  # recognize linear (constant-rate) situations
    "CCSS.MATH.8.EE.8.b",     # solve systems of linear equations
    "CCSS.MATH.7.RP.2.c",     # represent proportional relationships by equations
    "CCSS.MATH.HSA.REI.B.4.b",  # solve quadratic equations
    "CCSS.MATH.2.NBT.A.1.b",  # hundreds place value (early grade)
]

section("get_learning_path — structural contract")
for tgt in CHAINS:
    d = gp(target=tgt)
    path = d.get("path", [])
    ids = [n["id"] for n in path]
    grades = [_grade_key(n["grade"]) for n in path]

    check(f"{tgt} — returns a path", len(path) >= 1, f"{len(path)} nodes")
    check(f"{tgt} — target is final node", bool(path) and ids[-1] == d["target"])
    check(f"{tgt} — grade order non-decreasing", grades == sorted(grades),
          "->".join(n["grade"] for n in path))
    # every in-path prereq edge points to an earlier node in the list
    pos = {sid: i for i, sid in enumerate(ids)}
    ok_edges = all(
        pos.get(p, -1) < pos[n["id"]]
        for n in path for p in n["prerequisites_in_path"]
    )
    check(f"{tgt} — prereq edges point backward", ok_edges)

section("include_soft never shrinks the path")
for tgt in CHAINS:
    hard = gp(target=tgt)["path_length"]
    soft = gp(target=tgt, include_soft=True)["path_length"]
    check(f"{tgt} — soft ≥ hard", soft >= hard, f"hard={hard} soft={soft}")

section("cross-domain dependency present (the pilot's point)")
# 5.NF.B.7.b (Number & Operations—Fractions) should trace back through a
# Geometry standard (partitioning shapes into equal shares) — a link the
# grade-adjacency heuristic can never make (it is same-domain only).
d = gp(target="CCSS.MATH.5.NF.B.7.b", include_soft=True)
domains = {n["domain"] for n in d["path"]}
check("5.NF.B.7.b path spans >1 domain", len(domains) > 1, str(sorted(domains)))
has_geo = any("Geometry" in n["domain"] for n in d["path"])
check("5.NF.B.7.b path includes a Geometry prerequisite", has_geo)

section("from_standard pruning")
d = gp(target="CCSS.MATH.8.EE.7.b", from_standard="CCSS.MATH.7.EE.4.a")
ids = [n["id"] for n in d["path"]]
check("prune reachable flag set", d.get("from_standard_reachable") is True)
check("pruned path starts at from_standard", bool(ids) and ids[0] == d["from_standard"],
      "->".join(ids))
check("pruned path ends at target", bool(ids) and ids[-1] == d["target"])
# an unreachable from_standard should be reported, not crash
d2 = gp(target="CCSS.MATH.2.NBT.A.1.b", from_standard="CCSS.MATH.HSF.LE.A.1.b")
check("unreachable from_standard reported", d2.get("from_standard_reachable") is False)

section("error + empty handling")
err = json.loads(get_learning_path(target="CCSS.MATH.9.ZZ.9"))
check("bogus target → error", err.get("error") == "standard_not_found")
# A kindergarten standard has no lower-grade prereqs → path is just itself.
solo = gp(target="CCSS.MATH.K.CC.A.1")
check("no-prereq target → singleton path", solo["path_length"] == 1
      and "note" in solo, solo.get("note", ""))

section("lookup_standard — prefer_validated")
d = json.loads(lookup_standard(standard_id="CCSS.MATH.5.NF.B.7.b"))
check("reports prerequisites_method", "prerequisites_method" in d,
      d.get("prerequisites_method"))
check("prefers validated when present",
      d.get("prerequisites_method") == "llm_validated" and len(d["prerequisites"]) > 0)
# Fallback: a standard with no validated prereqs still returns heuristic ones (non-empty).
d2 = json.loads(lookup_standard(standard_id="CCSS.MATH.5.NF.A.1"))
check("non-empty prereqs preserved (fallback ok)", len(d2["prerequisites"]) > 0,
      f"{d2.get('prerequisites_method')}, {len(d2['prerequisites'])} prereqs")

print("\n" + "═" * 64)
print(f"  Results: {_n_pass} passed  |  {_n_fail} failed  |  {_n_pass + _n_fail} total")
sys.exit(1 if _n_fail else 0)
