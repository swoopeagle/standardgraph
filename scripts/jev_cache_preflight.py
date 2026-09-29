"""Jev caching pre-flight (jev-roadmap.md, Update 2026-09-26).

Sends the SAME ~8k-token state N times and compares usage.input_tokens,
any cache-related fields, and latency. If billed tokens never drop and no
cache field appears, assume NO cross-call caching — Phase 3 cost estimates
hold as written.

Usage: TYPESAFE_API_KEY=... uv run python scripts/jev_cache_preflight.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
DB = os.path.expanduser("~/.standardgraph/common_core.db")
N_CALLS = 5


def build_state() -> str:
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT id, standard_text FROM standards "
        "WHERE system='ccss' ORDER BY id LIMIT 250"
    ).fetchall()
    con.close()
    return "\n".join(f"{sid}: {desc}" for sid, desc in rows)


def call(key: str, state: str) -> tuple[dict, float]:
    body = json.dumps({
        "state": state,
        "model": "jev-1.13",
        "questions": {
            "has_fractions": {
                "type": "noul",
                "instructions": "These standards include fraction arithmetic",
            }
        },
    }).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    return resp, time.monotonic() - t0


def main() -> None:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        sys.exit("Set TYPESAFE_API_KEY")
    state = build_state()
    print(f"state: {len(state)} chars, {N_CALLS} identical calls\n")
    usages = []
    for i in range(N_CALLS):
        resp, dt = call(key, state)
        usage = resp.get("usage", {})
        usages.append(usage)
        print(f"call {i+1}: {dt*1000:6.0f} ms  usage={usage}")
        time.sleep(1)
    keys = {k for u in usages for k in u}
    cache_fields = [k for k in keys if "cach" in k.lower()]
    same_billing = len({u.get("input_tokens") for u in usages}) == 1
    print(f"\ncache-related usage fields: {cache_fields or 'NONE'}")
    print(f"input_tokens identical across calls: {same_billing}")
    print("verdict:",
          "no evidence of cross-call caching in API responses"
          if same_billing and not cache_fields
          else "POSSIBLE caching — inspect above")
    print("note: also eyeball console.typesafe.ai billing — a silent "
          "discount would show there, not in usage.")


if __name__ == "__main__":
    main()
