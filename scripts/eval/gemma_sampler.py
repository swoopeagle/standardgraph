"""Eval 5: Gemma extraction spot-check sampler.

Prints a random sample of N standards per Gemma-extracted system for manual
human verification against the source document. Outputs a readable report.

Usage:
    uv run python scripts/eval/gemma_sampler.py [--per-system 5] [--seed 42]
"""
import argparse
import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "common_core.db"

# Systems populated via Gemma PDF extraction (not CSP API)
GEMMA_SYSTEMS = {
    # International math
    "gb-sco": "Scotland CfE Numeracy & Mathematics",
    "ie-ncca": "Ireland NCCA Junior Cycle Mathematics",
    "hk-edb": "Hong Kong EDB Mathematics",
    "jp-mext": "Japan MEXT Elementary Arithmetic",
    "sg-moe": "Singapore MOE Mathematics",
    "nz-moe": "New Zealand Mathematics & Statistics",
    "au-acara": "Australia ACARA Mathematics",
    "au-vic": "Victoria Mathematics",
    "gh-nacca": "Ghana NaCCA Mathematics",
    "za-caps": "South Africa CAPS Mathematics",
    "rw-reb": "Rwanda REB Mathematics",
    "ca-qc": "Quebec MEES Mathematics",
    "in-ncert": "India NCERT Mathematics",
    # AP courses
    "ap-calc-ab": "AP Calculus AB",
    "ap-calc-bc": "AP Calculus BC",
    "ap-stats": "AP Statistics",
    "ap-precalc": "AP Precalculus",
    "ap-bio": "AP Biology",
    "ap-chem": "AP Chemistry",
    "ap-env": "AP Environmental Science",
    "ap-phys-1": "AP Physics 1",
    "ap-phys-2": "AP Physics 2",
    # Social studies
    "ca-ss": "California H-SS Standards",
    "il-ss": "Illinois Social Science Standards",
    "ma-ss": "Massachusetts H-SS Framework",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-system", type=int, default=5, help="Standards to sample per system")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--system", type=str, default=None, help="Limit to one system")
    args = parser.parse_args()

    random.seed(args.seed)
    conn = sqlite3.connect(DB_PATH)

    systems = {args.system: GEMMA_SYSTEMS.get(args.system, args.system)} if args.system else GEMMA_SYSTEMS

    print("=" * 70)
    print("  StandardGraph — Gemma Extraction Spot-Check")
    print(f"  {args.per_system} standards per system, seed={args.seed}")
    print("=" * 70)
    print()
    print("For each standard below, verify against the source document that:")
    print("  ✓ The text is a real standard (not a header, footnote, or prose)")
    print("  ✓ The grade level is correct")
    print("  ✓ The domain/strand label makes sense")
    print("  ✓ The text is not truncated or garbled")
    print()

    total_shown = 0
    for system, label in systems.items():
        rows = conn.execute(
            "SELECT id, grade, domain, cluster, standard_text, source_url "
            "FROM standards WHERE system=? ORDER BY RANDOM() LIMIT ?",
            (system, args.per_system),
        ).fetchall()

        if not rows:
            continue

        print(f"{'─'*70}")
        print(f"  {label} ({system})  —  {args.per_system} of "
              f"{conn.execute('SELECT COUNT(*) FROM standards WHERE system=?',(system,)).fetchone()[0]} standards")
        print(f"  Source: {rows[0][5]}")
        print()

        for sid, grade, domain, cluster, text, _ in rows:
            print(f"  ID:     {sid}")
            print(f"  Grade:  {grade or '—'}")
            print(f"  Domain: {domain or '—'}")
            if cluster:
                print(f"  Topic:  {cluster}")
            print(f"  Text:   {text[:300]}{'...' if len(text)>300 else ''}")
            print()
            total_shown += 1

    print(f"{'─'*70}")
    print(f"  Total shown: {total_shown} standards across {len(systems)} systems")
    print()
    conn.close()


if __name__ == "__main__":
    main()
