"""Eval: ELA and Social Studies crosswalk semantic correctness.

Extends crosswalk_semantic_tests.py into non-math subjects. Tests whether
NLP crosswalk mappings between state ELA/SS standards and their subject hubs
(CCSS-ELA and C3 Framework) are conceptually correct.

Usage:
  uv run python scripts/eval/subject_crosswalk_tests.py
  uv run python scripts/eval/subject_crosswalk_tests.py --local-judge
  uv run python scripts/eval/subject_crosswalk_tests.py --no-judge
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
You are an expert K-12 curriculum specialist in ELA and Social Studies.

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

def _build_tests(conn) -> list[dict]:
    tests = []

    # ── ELA: HIGH confidence (≥ 0.93) ────────────────────────────────────────
    # CA-ELA adopted CCSS with minor modifications — HIGH tier should be YES
    for src, tgt, lo, hi in [
        ("ca-ela",  "ccss-ela", 0.95, 1.01),
        ("wa-ela",  "ccss-ela", 0.93, 1.00),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "ELA", "tier": "HIGH",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

    # ── ELA: MED-HIGH (0.84–0.93) ─────────────────────────────────────────────
    for src, tgt, lo, hi in [
        ("tx-ela",  "ccss-ela", 0.85, 0.93),
        ("ca-ela",  "ccss-ela", 0.84, 0.92),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "ELA", "tier": "MED-HIGH",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

    # ── ELA: MEDIUM (0.75–0.84) ───────────────────────────────────────────────
    for src, tgt, lo, hi in [
        ("ny-ela",  "ccss-ela", 0.75, 0.85),
        ("ca-ela",  "ccss-ela", 0.78, 0.84),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "ELA", "tier": "MEDIUM",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

    # ── SS: HIGH confidence (≥ 0.88) ─────────────────────────────────────────
    for src, tgt, lo, hi in [
        ("ca-ss",   "c3", 0.88, 1.01),
        ("tx-ss",   "c3", 0.86, 0.97),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "SS", "tier": "HIGH",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

    # ── SS: MED-HIGH (0.80–0.88) ─────────────────────────────────────────────
    for src, tgt, lo, hi in [
        ("ny-ss",   "c3", 0.82, 0.90),
        ("ga-ss",   "c3", 0.80, 0.88),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "SS", "tier": "MED-HIGH",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

    # ── SS: MEDIUM (0.72–0.80) ────────────────────────────────────────────────
    for src, tgt, lo, hi in [
        ("fl-ss",   "c3", 0.72, 0.82),
    ]:
        rows = conn.execute("""
            SELECT cm.source_id, s1.standard_text, s1.system,
                   cm.target_id, s2.standard_text, s2.system,
                   cm.confidence_score, cm.grade_delta
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id=cm.source_id
            JOIN standards s2 ON s2.id=cm.target_id
            WHERE s1.system=? AND cm.target_system=?
              AND cm.confidence_score>=? AND cm.confidence_score<?
              AND s1.standard_text != s2.standard_text
            ORDER BY cm.source_id LIMIT 1
        """, (src, tgt, lo, hi)).fetchall()
        for r in rows:
            tests.append({
                "subject": "SS", "tier": "MEDIUM",
                "source_id": r[0], "source_text": r[1], "source_system": r[2],
                "target_id": r[3], "target_text": r[4], "target_system": r[5],
                "confidence": r[6], "grade_delta": r[7],
            })

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
    if first.startswith("YES"):     return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):      return "NO", reason
    return "PARTIAL", raw


# ── Runner ────────────────────────────────────────────────────────────────────

def main(no_judge: bool = False, local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL

    conn = sqlite3.connect(str(DB_PATH))
    tests = _build_tests(conn)
    conn.close()

    if not tests:
        print("  ERROR: no test cases found in DB")
        return 1

    n_yes = n_partial = n_no = n_err = 0
    subject_stats: dict[str, dict] = {}
    tier_stats: dict[str, dict]    = {}

    print(f"\n── ELA + SS crosswalk tests ({len(tests)} pairs) ─────────────────────")
    if not no_judge:
        label = "gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
        print(f"  Judge: {label}")
    print(f"  {'Subj':<5} {'Tier':<9} {'Conf':>6} {'Δgr':>4}  {'Src→Tgt':<20} {'LLM':>4}  Reason")
    print(f"  {'-'*5} {'-'*9} {'-'*6} {'-'*4}  {'-'*20} {'----':>4}  {'-'*38}")

    for t in tests:
        subj = t["subject"]
        tier = t["tier"]
        subject_stats.setdefault(subj, {"YES": 0, "PARTIAL": 0, "NO": 0, "ERR": 0})
        tier_stats.setdefault(f"{subj}/{tier}", {"YES": 0, "PARTIAL": 0, "NO": 0, "ERR": 0})

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
            bucket = verdict if verdict in subject_stats[subj] else "ERR"
            subject_stats[subj][bucket] += 1
            tier_stats[f"{subj}/{tier}"][bucket] += 1
            if verdict == "YES":     n_yes += 1
            elif verdict == "PARTIAL": n_partial += 1
            elif verdict == "NO":    n_no += 1
            else:                    n_err += 1

        pair = f"{t['source_system']}→{t['target_system']}"[:20]
        short_reason = reason[:38] if reason else ""
        delta = t.get("grade_delta") or 0
        print(f"  {subj:<5} {tier:<9} {t['confidence']:>6.3f} {delta:>+4}  {pair:<20} [{tag}]  {short_reason}")
        if verdict and verdict != "YES":
            print(f"    src: {t['source_text'][:65]}")
            print(f"    tgt: {t['target_text'][:65]}")

    print(f"\n  Overall: {n_yes} YES / {n_partial} PARTIAL / {n_no} NO / {n_err} ERR")
    if not no_judge:
        print(f"\n  By subject:")
        for subj in ["ELA", "SS"]:
            if subj in subject_stats:
                s = subject_stats[subj]
                total = sum(s.values())
                pct = 100 * s["YES"] // total if total else 0
                print(f"    {subj}: {s['YES']} YES / {s['PARTIAL']} PARTIAL / {s['NO']} NO  ({pct}% match)")
        print(f"\n  By tier:")
        for key in sorted(tier_stats):
            s = tier_stats[key]
            total = sum(s.values())
            pct = 100 * s["YES"] // total if total else 0
            print(f"    {key:<18}: {s['YES']} YES / {s['PARTIAL']} PARTIAL / {s['NO']} NO  ({pct}% match)")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--local-judge", action="store_true")
    args = p.parse_args()
    sys.exit(main(no_judge=args.no_judge, local_judge=args.local_judge))
