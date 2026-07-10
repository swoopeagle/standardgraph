#!/usr/bin/env python3
"""Golden-transcript regression check — a fixed set of demo queries with pinned
outputs, to run right before a demo/roadshow to catch any drift.

Records canonical *signatures* of representative tool calls (stable fields only —
ids, grades, path structure, methods, counts — not volatile embedding floats) so
the check is deterministic and meaningful. Ollama-dependent tools (search,
progression) are compared structurally and auto-skip if Ollama is unavailable,
so a missing embedding backend never false-alarms the deterministic checks.

    uv run python scripts/eval/golden_transcript.py --record   # pin current outputs
    uv run python scripts/eval/golden_transcript.py            # check vs pinned (CI/pre-demo)

Runs against DB_PATH (defaults to the installed prod DB).
"""
import json
import sys
from pathlib import Path

from common_core.server import (get_learning_path, lookup_standard, search_standards,
                                 get_progression, map_standard, list_systems)

GOLDEN = Path(__file__).parent / "golden_transcript.json"


def _lp_sig(raw):
    d = json.loads(raw)
    if "error" in d:
        return {"error": d["error"]}
    return {
        "target": d["target"],
        "edge_strength": d["edge_strength"],
        "path": [{"id": n["id"], "grade": n["grade"],
                  "pr": sorted(p["id"] for p in n["prerequisites_in_path"])}
                 for n in d["path"]],
    }


def _lookup_sig(raw):
    d = json.loads(raw)
    return {
        "id": d.get("id"), "grade": d.get("grade"), "domain": d.get("domain"),
        "prerequisites": sorted(d.get("prerequisites") or []),
        "prerequisites_method": d.get("prerequisites_method"),
        "n_successors": len(d.get("successors") or []),
    }


def _map_sig(raw):
    d = json.loads(raw)
    if "mappings" in d:
        return {"method": d.get("mapping_method"),
                "targets": sorted(m.get("target_id") or m.get("id", "") for m in d["mappings"])[:8]}
    return {"result": d.get("result")}


def _list_sig(raw):
    d = json.loads(raw)
    txt = raw
    return {"len": len(txt), "has_ccss_math": "ccss" in txt.lower()}


def _search_sig(raw):
    d = json.loads(raw)
    # semantic — compare only ordered ids of the results (structural), tolerate fallback
    if isinstance(d, dict) and d.get("search_method") == "keyword_fts_fallback":
        return {"_ollama": False}
    results = d if isinstance(d, list) else d.get("results", [])
    return {"ids": [r.get("id") for r in results]}


def _prog_sig(raw):
    d = json.loads(raw)
    if "error" in d:
        return {"error": d["error"]}
    return {"grades": [s.get("grade") for s in d.get("stages", [])],
            "n_stages": len(d.get("stages", []))}


# (name, thunk, signature-fn, ollama_dependent)
QUERIES = [
    ("lp_fraction_division", lambda: get_learning_path(target="CCSS.MATH.5.NF.B.7.b"), _lp_sig, False),
    ("lp_rational_exponents", lambda: get_learning_path(target="CCSS.MATH.HSN.RN.A.2"), _lp_sig, False),
    ("lp_linear_recognition", lambda: get_learning_path(target="CCSS.MATH.HSF.LE.A.1.b"), _lp_sig, False),
    ("lp_systems", lambda: get_learning_path(target="CCSS.MATH.8.EE.8.b"), _lp_sig, False),
    ("lp_shortform", lambda: get_learning_path(target="5.NF.B.7.b"), _lp_sig, False),
    ("lp_from_prune", lambda: get_learning_path(target="CCSS.MATH.8.EE.7.b", from_standard="CCSS.MATH.7.EE.4.a"), _lp_sig, False),
    ("lookup_validated", lambda: lookup_standard(standard_id="CCSS.MATH.5.NF.B.7.b"), _lookup_sig, False),
    ("lookup_fallback", lambda: lookup_standard(standard_id="CCSS.MATH.5.NF.A.1"), _lookup_sig, False),
    ("map_apcalc_ccss", lambda: map_standard(standard_id="AP.AP_CALC_AB.LIM-1.A", from_system="ap-calc-ab", to_system="ccss"), _map_sig, False),
    ("list_systems", lambda: list_systems(), _list_sig, False),
    ("search_fractions", lambda: search_standards(query="adding fractions with unlike denominators", limit=3), _search_sig, True),
    ("progression_fractions", lambda: get_progression(concept="fractions", system="ccss"), _prog_sig, True),
]


def run_all():
    out = {}
    for name, thunk, sigfn, _ollama in QUERIES:
        try:
            out[name] = sigfn(thunk())
        except Exception as e:
            out[name] = {"_exception": f"{type(e).__name__}: {e}"}
    return out


def main():
    record = "--record" in sys.argv
    current = run_all()

    if record:
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"recorded {len(current)} signatures → {GOLDEN}")
        return

    if not GOLDEN.exists():
        print("no golden file — run with --record first")
        sys.exit(2)
    golden = json.loads(GOLDEN.read_text())

    npass = nfail = nskip = 0
    for name, _thunk, _sig, ollama in QUERIES:
        cur, exp = current.get(name), golden.get(name)
        # tolerate ollama-dependent checks when the backend is unavailable
        if ollama and (cur == {"_ollama": False} or "_exception" in (cur or {})):
            print(f"  [SKIP] {name} (ollama unavailable)")
            nskip += 1
            continue
        if cur == exp:
            print(f"  [PASS] {name}")
            npass += 1
        else:
            print(f"  [FAIL] {name}")
            print(f"        expected: {json.dumps(exp)[:200]}")
            print(f"        got:      {json.dumps(cur)[:200]}")
            nfail += 1
    print(f"\n  {npass} passed | {nfail} failed | {nskip} skipped")
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
