#!/usr/bin/env python3
"""Concurrency / load check for the DB-backed MCP tools.

The test suites are all single-threaded; a hosted MCP serves many callers at once.
Each tool call opens its own sqlite connection and only reads, so SQLite's
multi-reader model should hold — but "should" isn't "verified". This fires a large
number of mixed tool calls from a thread pool and asserts: zero errors (esp. no
'database is locked'), correct results under contention, and acceptable tail
latency.

Only DB-bound tools are exercised (get_learning_path, lookup_standard, map_standard,
list_systems) — search/progression depend on Ollama and would measure the embedding
backend, not our concurrency. Run against DB_PATH (defaults to installed prod DB).

    uv run python scripts/eval/concurrency_check.py [workers] [total_calls]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from common_core.server import (get_learning_path, lookup_standard,
                                 map_standard, list_systems)

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 32
TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 800
P95_BUDGET_MS = 500  # generous; these are single-digit-ms locally

# (thunk, validator) — validator returns True if the result looks right.
# NB: intentionally excludes map_standard's semantic-fallback path and list_systems,
# which are Ollama-bound / pre-existing-slow respectively and would measure those
# subsystems rather than the prerequisite-graph tools this study is about. See
# docs/prereq_graph_pilot_report.md (concurrency section) for the per-tool profile.
JOBS = [
    (lambda: get_learning_path(target="CCSS.MATH.5.NF.B.7.b"),
     lambda r: json.loads(r)["path_length"] == 5),
    (lambda: get_learning_path(target="CCSS.MATH.HSA.REI.B.4.b", include_soft=True),
     lambda r: json.loads(r)["path_length"] > 50),
    (lambda: get_learning_path(target="CCSS.MATH.HSF.LE.A.1.b"),
     lambda r: json.loads(r)["path"][-1]["id"] == "CCSS.MATH.HSF.LE.A.1.b"),
    (lambda: get_learning_path(target="CCSS.MATH.8.EE.8.b"),
     lambda r: json.loads(r)["path_length"] == 3),
    (lambda: lookup_standard(standard_id="CCSS.MATH.5.NF.B.7.b"),
     lambda r: json.loads(r)["prerequisites_method"] == "llm_validated"),
    (lambda: lookup_standard(standard_id="CCSS.MATH.5.NF.A.1"),
     lambda r: len(json.loads(r)["prerequisites"]) > 0),
]


def one(i):
    thunk, valid = JOBS[i % len(JOBS)]
    t0 = time.perf_counter()
    try:
        r = thunk()
        ok = valid(r)
        return (time.perf_counter() - t0, ok, None)
    except Exception as e:
        return (time.perf_counter() - t0, False, f"{type(e).__name__}: {e}")


def main():
    print(f"concurrency check: {TOTAL} calls across {WORKERS} workers "
          f"(mixed DB-bound tools)")
    wall0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(one, range(TOTAL)))
    wall = time.perf_counter() - wall0

    lat = sorted(r[0] * 1000 for r in results)
    errors = [r[2] for r in results if r[2]]
    bad = [r for r in results if not r[1] and not r[2]]  # ran but wrong result

    def pct(p):
        return lat[min(len(lat) - 1, int(len(lat) * p))]

    print(f"  wall time:   {wall:.2f}s   throughput: {TOTAL/wall:.0f} calls/s")
    print(f"  latency ms:  p50={pct(.50):.1f}  p95={pct(.95):.1f}  p99={pct(.99):.1f}  max={lat[-1]:.1f}")
    print(f"  errors:      {len(errors)}")
    print(f"  wrong-result:{len(bad)}")
    if errors:
        from collections import Counter
        for msg, n in Counter(errors).most_common(5):
            print(f"    {n}x  {msg}")

    ok = not errors and not bad
    if ok and pct(.95) > P95_BUDGET_MS:
        print(f"  ⚠ p95 {pct(.95):.0f}ms over budget {P95_BUDGET_MS}ms (correctness fine)")
    print("\n  RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
