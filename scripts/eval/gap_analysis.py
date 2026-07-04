"""Gap analysis — surface crosswalk coverage holes for planning.

For each non-hub system (AP, IB, state standards), a "gap" is a source standard
with no crosswalk mapping, or whose best mapping is below a usable confidence
threshold. Hubs (ccss, ngss, ccss-ela, c3, csta) are crosswalk *targets*, so they
are correctly expected to have ~zero mappings as source and are excluded.

Usage:
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/eval/gap_analysis.py
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/eval/gap_analysis.py --threshold 0.65
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/eval/gap_analysis.py --systems ap-calc-ab,ib-dp
    DB_PATH=~/.standardgraph/common_core.db uv run python scripts/eval/gap_analysis.py --json /tmp/gaps.json
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# Prefer DB_PATH env (installed DB); fall back to the pipeline DB for parity with run_all.py.
DB_PATH = Path(
    os.environ.get("DB_PATH", Path(__file__).parent.parent.parent / "data" / "common_core.db")
).expanduser()

# Crosswalk hubs — these are targets, not sources, so zero mappings-as-source is correct.
HUBS = {"ccss", "ngss", "ccss-ela", "c3", "csta"}

# Systems we most care about strengthening (AP + IB across subjects).
FOCUS_PREFIXES = ("ap-", "ib-")

OK   = "\033[32m OK \033[0m"
WARN = "\033[33mWARN\033[0m"
GAP  = "\033[31m GAP\033[0m"


def analyze(conn: sqlite3.Connection, threshold: float, only_systems: set[str] | None):
    # Per-system: total standards, standards with >=1 mapping, best-mapping distribution.
    rows = conn.execute(
        """
        SELECT s.system                                   AS system,
               COUNT(DISTINCT s.id)                        AS total,
               COUNT(DISTINCT cm.source_id)               AS mapped,
               COUNT(DISTINCT CASE WHEN best.best_conf >= ? THEN s.id END) AS mapped_usable
        FROM standards s
        LEFT JOIN crosswalk_mappings cm ON cm.source_id = s.id
        LEFT JOIN (
            SELECT source_id, MAX(confidence_score) AS best_conf
            FROM crosswalk_mappings GROUP BY source_id
        ) best ON best.source_id = s.id
        GROUP BY s.system
        ORDER BY s.system
        """,
        (threshold,),
    ).fetchall()

    report = []
    for system, total, mapped, mapped_usable in rows:
        if system in HUBS:
            continue
        if only_systems is not None and system not in only_systems:
            continue
        unmapped = total - mapped
        below = mapped - mapped_usable  # mapped but best confidence < threshold
        coverage = mapped_usable / total if total else 0.0
        report.append({
            "system":        system,
            "total":         total,
            "unmapped":      unmapped,
            "below_thresh":  below,
            "usable":        mapped_usable,
            "coverage":      round(coverage, 3),
        })
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Crosswalk coverage gap analysis")
    ap.add_argument("--threshold", type=float, default=0.65,
                    help="Usable-confidence floor (default 0.65)")
    ap.add_argument("--systems", default=None,
                    help="Comma-separated systems to restrict to (default: all non-hub)")
    ap.add_argument("--focus", action="store_true",
                    help="Restrict to AP + IB systems only")
    ap.add_argument("--json", default=None, help="Also write full report to this JSON path")
    ap.add_argument("--top", type=int, default=25, help="Show N worst-coverage systems (default 25)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}  (set DB_PATH env var)", file=sys.stderr)
        return 2

    only = set(args.systems.split(",")) if args.systems else None
    conn = sqlite3.connect(DB_PATH)
    report = analyze(conn, args.threshold, only)
    conn.close()

    if args.focus:
        report = [r for r in report if r["system"].startswith(FOCUS_PREFIXES)]

    totals = {
        "systems":   len(report),
        "standards": sum(r["total"] for r in report),
        "unmapped":  sum(r["unmapped"] for r in report),
        "below":     sum(r["below_thresh"] for r in report),
        "usable":    sum(r["usable"] for r in report),
    }

    print(f"\n── Crosswalk gap analysis (threshold {args.threshold}) ─────────────────────")
    print(f"   DB: {DB_PATH}")
    print(f"   Non-hub systems: {totals['systems']}  |  standards: {totals['standards']:,}")
    print(f"   Unmapped: {totals['unmapped']:,}   Below-threshold: {totals['below']:,}   "
          f"Usable (≥{args.threshold}): {totals['usable']:,}")

    worst = sorted(report, key=lambda r: r["coverage"])[: args.top]
    print(f"\n── {len(worst)} worst-coverage systems ─────────────────────────────────────")
    print(f"   {'system':16s} {'total':>6} {'unmapped':>9} {'<thresh':>8} {'usable':>7} {'cov':>6}")
    for r in worst:
        tag = GAP if r["coverage"] < 0.20 else (WARN if r["coverage"] < 0.50 else OK)
        print(f"  [{tag}] {r['system']:16s} {r['total']:>6} {r['unmapped']:>9} "
              f"{r['below_thresh']:>8} {r['usable']:>7} {r['coverage']*100:>5.1f}%")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"threshold": args.threshold, "totals": totals, "systems": report}, indent=2))
        print(f"\n   Full report → {args.json}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
