"""Generate LLM rationales for crosswalk mappings using qwen2.5:72b on the Studio.

Run this on the Mac Studio (OLLAMA_BASE_URL=http://169.254.1.1:11434).

What it does:
  1. Samples crosswalk mappings stratified by confidence band and source system.
  2. Calls qwen2.5:72b to score each mapping (1-5) and write a 1-sentence rationale.
  3. Writes the rationale into crosswalk_mappings.notes.
  4. Sets flagged_for_review=1 for mappings the model scores ≤ 2.

Why this matters for machine usability:
  AI agents calling map_standard currently get only a cosine similarity score.
  With a rationale, they understand *why* two standards are related — enabling
  higher-quality pedagogical reasoning without human review.

Usage:
  OLLAMA_BASE_URL=http://169.254.1.1:11434 OLLAMA_MODEL=qwen2.5:72b \\
  DB_PATH=/path/to/common_core.db \\
  python scripts/crosswalk_rationale_gen.py [--sample N] [--system SYSTEM] [--band BAND]

  --sample N       Number of mappings to process (default 500; use 0 for all)
  --system SYSTEM  Limit to a specific source system (e.g. sg-moe, cambridge)
  --band BAND      Confidence band to focus on: high (≥0.85), mid (0.70-0.85), low (<0.70)
  --dry-run        Print prompts/responses without writing to DB
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent.parent / "data" / "common_core.db"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:72b")

RATIONALE_PROMPT = """\
You are a K-12 mathematics curriculum expert. Evaluate this crosswalk mapping between two \
curriculum standards.

SOURCE STANDARD ({src_system}, Grade {src_grade}, {src_domain}):
  {src_text}

TARGET STANDARD ({tgt_system}, Grade {tgt_grade}, {tgt_domain}):
  {tgt_text}

Cosine similarity score: {confidence:.3f}
Grade delta: {grade_delta:+d} (positive = target curriculum is later)

Tasks:
1. Rate this mapping 1-5 where:
   5 = Exact same concept, well-aligned grade level
   4 = Same concept with minor scope difference or 1-grade shift
   3 = Related concept, partial overlap, or notable grade shift
   2 = Loosely related, different scope or emphasis
   1 = Wrong mapping — different mathematical concept
2. Write ONE sentence (≤ 25 words) explaining what makes these standards related (or not).
3. If score ≤ 2, identify the specific mismatch.

Respond in JSON only:
{{"score": <1-5>, "rationale": "<one sentence>", "mismatch": "<only if score ≤ 2, else null>"}}
"""


def _call_model(prompt: str) -> dict | None:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0, "num_ctx": 4096},
    }
    try:
        resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Model error: {e}", file=sys.stderr)
        return None

    content = resp.json()["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def sample_mappings(
    conn: sqlite3.Connection,
    n: int,
    system: str | None,
    target: str | None,
    band: str | None,
    review_only: bool = False,
) -> list[sqlite3.Row]:
    if review_only:
        conditions = ["cm.notes IS NOT NULL", "cm.verified_by_human = 0"]
    else:
        conditions = ["cm.notes IS NULL", "cm.verified_by_human = 0"]
    params: list = []

    if system:
        conditions.append("cm.source_system = ?")
        params.append(system)

    if target:
        conditions.append("cm.target_system = ?")
        params.append(target)

    if band == "high":
        conditions.append("cm.confidence_score >= 0.85")
    elif band == "mid":
        conditions.append("cm.confidence_score >= 0.70 AND cm.confidence_score < 0.85")
    elif band == "low":
        conditions.append("cm.confidence_score < 0.70")

    where = " AND ".join(conditions)
    limit_clause = f"LIMIT {n}" if n > 0 else ""

    return conn.execute(
        f"""SELECT cm.id, cm.source_id, cm.target_id, cm.source_system, cm.target_system,
                   cm.confidence_score, cm.grade_delta,
                   s1.standard_text AS src_text, s1.grade AS src_grade, s1.domain AS src_domain,
                   s2.standard_text AS tgt_text, s2.grade AS tgt_grade, s2.domain AS tgt_domain
            FROM crosswalk_mappings cm
            JOIN standards s1 ON s1.id = cm.source_id
            JOIN standards s2 ON s2.id = cm.target_id
            WHERE {where}
            ORDER BY cm.confidence_score DESC
            {limit_clause}""",
        params,
    ).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate crosswalk rationales via LLM")
    parser.add_argument("--sample", type=int, default=500, help="Mappings to process (0=all)")
    parser.add_argument("--system", type=str, default=None, help="Filter by source system")
    parser.add_argument("--target", type=str, default=None, help="Filter by target system")
    parser.add_argument("--band", choices=["high", "mid", "low"], default=None)
    parser.add_argument("--review-only", action="store_true",
                        help="Re-score already-annotated mappings (for flagging bad ones)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    rows = sample_mappings(conn, args.sample, args.system, args.target, args.band,
                           review_only=args.review_only)
    total = len(rows)
    print(f"Processing {total} mappings with {OLLAMA_MODEL} @ {OLLAMA_BASE_URL}")
    print(f"  Filter — system: {args.sample or 'all'}, band: {args.band or 'all'}")
    if args.dry_run:
        print("  DRY RUN — no DB writes")
    print()

    scored_1_2 = 0
    scored_3 = 0
    scored_4_5 = 0
    errors = 0
    t0 = time.time()

    for i, row in enumerate(rows, 1):
        prompt = RATIONALE_PROMPT.format(
            src_system=row["source_system"],
            src_grade=row["src_grade"],
            src_domain=row["src_domain"],
            src_text=row["src_text"],
            tgt_system=row["target_system"],
            tgt_grade=row["tgt_grade"],
            tgt_domain=row["tgt_domain"],
            tgt_text=row["tgt_text"],
            confidence=row["confidence_score"],
            grade_delta=row["grade_delta"],
        )

        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (total - i) / rate if rate > 0 else 0
        print(
            f"  [{i:4d}/{total}] {row['source_system']:12s} → {row['target_system']:12s} "
            f"conf={row['confidence_score']:.3f}  ETA {eta/60:.1f}m",
            end="", flush=True,
        )

        result = _call_model(prompt)
        if result is None:
            print("  ERROR")
            errors += 1
            continue

        score = result.get("score", 3)
        rationale = (result.get("rationale") or "").strip()
        mismatch = (result.get("mismatch") or "").strip() or None

        notes = f"[LLM score {score}/5] {rationale}"
        if mismatch:
            notes += f" | MISMATCH: {mismatch}"

        if score <= 2:
            scored_1_2 += 1
        elif score == 3:
            scored_3 += 1
        else:
            scored_4_5 += 1

        print(f"  score={score}  {rationale[:60]}")

        if not args.dry_run:
            conn.execute(
                """UPDATE crosswalk_mappings
                   SET notes = ?, flagged_for_review = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (notes, 1 if score <= 2 else 0, row["id"]),
            )
            conn.commit()

    elapsed_total = time.time() - t0
    conn.close()

    print(f"\n── Results ─────────────────────────────────────────────────────────")
    print(f"  Processed:   {total} mappings in {elapsed_total/60:.1f}m")
    print(f"  Score 4-5:   {scored_4_5} ({100*scored_4_5/total:.1f}%)  [good/exact]")
    print(f"  Score 3:     {scored_3} ({100*scored_3/total:.1f}%)  [plausible]")
    print(f"  Score 1-2:   {scored_1_2} ({100*scored_1_2/total:.1f}%)  [flagged for review]")
    print(f"  Errors:      {errors}")
    if scored_1_2 > 0:
        print(f"\n  Run this to see flagged mappings:")
        print(f"  python3 -c \"import sqlite3; c=sqlite3.connect('{DB_PATH}'); "
              f"[print(r) for r in c.execute('SELECT source_id, target_id, notes FROM crosswalk_mappings WHERE flagged_for_review=1 LIMIT 20').fetchall()]\"")


if __name__ == "__main__":
    main()
