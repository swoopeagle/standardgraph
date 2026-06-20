"""Eval: Crosswalk semantic correctness — does the mapping make conceptual sense?

Cosine similarity tells us vectors are close; Gemma tells us if the *concepts* match.
Tests crosswalk pairs at four confidence tiers to see how well confidence predicts quality.

Usage:
  uv run python scripts/eval/crosswalk_semantic_tests.py
  uv run python scripts/eval/crosswalk_semantic_tests.py --local-judge
  uv run python scripts/eval/crosswalk_semantic_tests.py --no-judge
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT    = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "common_core.db"
GEMMA_STUDIO_URL   = "http://169.254.1.1:11434/api/generate"
GEMMA_STUDIO_MODEL = "gemma4:31b-it-q8_0"
GEMMA_LOCAL_URL    = "http://localhost:11434/api/generate"
GEMMA_LOCAL_MODEL  = "gemma4:26b"

_OK   = "\033[32m OK \033[0m"
_PART = "\033[33mPART\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"

_JUDGE_PROMPT = """\
You are an expert K-12 curriculum specialist.

Source standard ({src_sys}):
"{src_text}"

Mapped standard ({tgt_sys}):
"{tgt_text}"

Are these two standards teaching the same or closely related concept at an appropriate level?
- YES: same concept, appropriate grade level (grade offset ≤1 year is acceptable)
- PARTIAL: related concept but noticeably different scope, aspect, or grade level
- NO: different concepts — the mapping is incorrect

Reply with ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""

# ── Test case selection ────────────────────────────────────────────────────────

def _load_tier(conn, lo: float, hi: float, systems: list[str], n: int) -> list[dict]:
    placeholders = ",".join("?" * len(systems))
    rows = conn.execute(
        f"""SELECT cm.source_id, s1.standard_text, s1.system,
                  cm.target_id, s2.standard_text, s2.system,
                  cm.confidence_score, cm.grade_delta
           FROM crosswalk_mappings cm
           JOIN standards s1 ON s1.id=cm.source_id
           JOIN standards s2 ON s2.id=cm.target_id
           WHERE s1.system IN ({placeholders})
             AND cm.confidence_score >= ? AND cm.confidence_score < ?
             AND s1.standard_text != s2.standard_text
           ORDER BY s1.system, cm.source_id
           LIMIT ?""",
        (*systems, lo, hi, n),
    ).fetchall()
    return [
        {
            "source_id": r[0], "source_text": r[1], "source_system": r[2],
            "target_id": r[3], "target_text": r[4], "target_system": r[5],
            "confidence": r[6], "grade_delta": r[7],
        }
        for r in rows
    ]


def _build_tests(conn) -> list[dict]:
    tests = []

    # Tier 1 — HIGH (≥ 0.95): CS, science, ELA adopted standards
    for src, tgt, lo, hi in [
        ("nh-cs",  "csta",     0.98, 1.01),
        ("ca-sci", "ngss",     0.98, 1.01),
        ("wi-cs",  "csta",     0.90, 0.98),
        ("ca-ela", "ccss-ela", 0.95, 1.01),
    ]:
        rows = _load_tier(conn, lo, hi, [src], 1)
        for r in rows:
            tests.append({**r, "tier": "HIGH", "expect": "YES"})

    # Tier 2 — MEDIUM-HIGH (0.85–0.95): strong but not identical
    for src, lo, hi in [
        ("sg-moe",   0.88, 0.95),
        ("ca-sci",   0.88, 0.95),
        ("ca-ela",   0.88, 0.95),
    ]:
        rows = _load_tier(conn, lo, hi, [src], 1)
        for r in rows:
            tests.append({**r, "tier": "MED-HIGH", "expect": "YES"})

    # Tier 3 — MEDIUM (0.78–0.85): plausible but might differ in scope
    for src, lo, hi in [
        ("sg-moe",   0.80, 0.88),
        ("in-ncert", 0.78, 0.88),
        ("tx",       0.78, 0.85),
    ]:
        rows = _load_tier(conn, lo, hi, [src], 1)
        for r in rows:
            tests.append({**r, "tier": "MEDIUM", "expect": "PARTIAL"})

    # Tier 4 — LOW (0.70–0.78): borderline — likely PARTIAL or NO
    rows = _load_tier(conn, 0.70, 0.78, ["tx", "ak", "aero"], 3)
    for r in rows:
        tests.append({**r, "tier": "LOW", "expect": "NO"})

    return tests


# ── Judge ─────────────────────────────────────────────────────────────────────

def _judge(case: dict, url: str, model: str) -> tuple[str, str]:
    prompt = _JUDGE_PROMPT.format(
        src_sys=case["source_system"],
        src_text=case["source_text"][:400],
        tgt_sys=case["target_system"],
        tgt_text=case["target_text"][:400],
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
    if first.startswith("YES"):    return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):     return "NO", reason
    return "PARTIAL", raw


# ── Main ──────────────────────────────────────────────────────────────────────

def main(no_judge: bool = False, local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL

    conn = sqlite3.connect(str(DB_PATH))
    tests = _build_tests(conn)
    conn.close()

    if not tests:
        print("  ERROR: no test cases found in DB")
        return 1

    tier_stats: dict[str, dict[str, int]] = {}
    n_yes = n_partial = n_no = n_err = 0

    print(f"\n── Crosswalk semantic tests ({len(tests)} pairs) ────────────────────────")
    if not no_judge:
        judge_label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {judge_label}")
    print(f"  {'Tier':<10} {'Conf':>6} {'Δgr':>4}  {'Src→Tgt':<22} {'LLM':>4}  Reason")
    print(f"  {'-'*10} {'-'*6} {'-'*4}  {'-'*22} {'----':>4}  {'-'*40}")

    for t in tests:
        tier = t["tier"]
        tier_stats.setdefault(tier, {"YES": 0, "PARTIAL": 0, "NO": 0, "ERR": 0})

        verdict = reason = ""
        tag = _SKIP
        if not no_judge:
            verdict, reason = _judge(t, judge_url, judge_model)
            tag = (
                _OK   if verdict == "YES"     else
                _PART if verdict == "PARTIAL" else
                _ERR  if verdict == "ERR"     else
                _FAIL
            )
            tier_stats[tier][verdict if verdict in tier_stats[tier] else "ERR"] += 1
            if verdict == "YES":    n_yes += 1
            elif verdict == "PARTIAL": n_partial += 1
            elif verdict == "NO":   n_no += 1
            else:                   n_err += 1

        pair = f"{t['source_system']}→{t['target_system']}"[:22]
        short_reason = reason[:50] if reason else ""
        print(f"  {tier:<10} {t['confidence']:>6.3f} {t['grade_delta'] or 0:>4}  "
              f"{pair:<22} [{tag}]  {short_reason}")
        if verdict and verdict != "YES":
            src_snip = t["source_text"][:60]
            tgt_snip = t["target_text"][:60]
            print(f"    src: {src_snip}")
            print(f"    tgt: {tgt_snip}")

    print(f"\n  Overall: {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_err} ERR")
    if not no_judge:
        print(f"\n  By confidence tier:")
        tier_order = ["HIGH", "MED-HIGH", "MEDIUM", "LOW"]
        for tier in tier_order:
            if tier in tier_stats:
                s = tier_stats[tier]
                total = sum(s.values())
                yes_pct = 100 * s["YES"] // total if total else 0
                print(f"    {tier:<10}: {s['YES']} YES / {s['PARTIAL']} PARTIAL / {s['NO']} NO  ({yes_pct}% match)")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--local-judge", action="store_true")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
