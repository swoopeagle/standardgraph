#!/usr/bin/env python3
"""Post-ingestion smoke test — run after overnight_run.sh to catch regressions.

Exit 0 if all checks pass, exit 1 if any FAIL (warnings don't fail).
Usage: uv run python scripts/smoke_test.py
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "common_core.db"

EXPECTED_SYSTEMS = {
    # ── Subject hubs ──────────────────────────────────────────────────────────
    "ccss":      343,
    "ngss":      100,
    "ccss-ela":  400,
    "c3":        200,
    "csta":       80,
    # ── US states sample — math ───────────────────────────────────────────────
    "tx":        500,
    "ca":        100,
    "fl":        400,
    "ny":         80,
    # ── US states sample — science ────────────────────────────────────────────
    "tx-sci":    200,
    "ca-sci":    200,
    "fl-sci":    400,
    # ── US states sample — ELA ────────────────────────────────────────────────
    "tx-ela":    200,
    "ca-ela":    200,
    "fl-ela":    400,
    # ── US states sample — social studies ─────────────────────────────────────
    "tx-ss":     300,
    "al-ss":     300,
    # ── US states sample — CS ─────────────────────────────────────────────────
    "ut-cs":      50,
    "fl-cs":      15,
    # ── AP courses ────────────────────────────────────────────────────────────
    "ap-calc-ab":     25,
    "ap-bio":         70,
    "ap-env":         80,
    # ── Canada ───────────────────────────────────────────────────────────────
    "ca-ab":     800,
    "ca-on":     150,
    # ── International math ────────────────────────────────────────────────────
    "cambridge": 400,
    "ib-myp":     80,
    "au-acara":  100,
    "uk-nc":     150,
    "sg-moe":    150,
    "jp-mext":    50,
    "nz-moe":    200,
    "aero":       50,
    "dodea":      50,
    "ie-ncca":    30,
    "hk-edb":     15,
    "in-ncert":   10,
    "gh-nacca":   50,
    "za-caps":    10,
}

# These are crosswalk hubs — they don't get mapped to themselves
CROSSWALK_HUBS = {"ccss", "ngss", "ccss-ela", "c3", "csta"}

WARN = "\033[33mWARN\033[0m"
FAIL = "\033[31mFAIL\033[0m"
OK   = "\033[32m OK \033[0m"


def main() -> int:
    if not DB_PATH.exists():
        print(f"[{FAIL}] DB not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    failures = 0

    # ── 1. Per-system counts ───────────────────────────────────────────────────
    print("\n── System coverage ──────────────────────────────────────────────────")
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT system, COUNT(*) FROM standards GROUP BY system"
    ).fetchall()}

    for system, min_count in sorted(EXPECTED_SYSTEMS.items()):
        actual = rows.get(system, 0)
        if actual == 0:
            tag = FAIL
            failures += 1
        elif actual < min_count:
            tag = WARN
        else:
            tag = OK
        print(f"  [{tag}] {system:12s}  {actual:>5} standards  (min {min_count})")

    systems_not_expected = set(rows) - set(EXPECTED_SYSTEMS)
    if systems_not_expected:
        print(f"\n  [note] {len(systems_not_expected)} systems in DB not in checklist: "
              f"{', '.join(sorted(systems_not_expected))}")

    # ── 2. Embedding coverage ─────────────────────────────────────────────────
    print("\n── Embedding coverage ───────────────────────────────────────────────")
    total_std = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    total_emb = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    missing_emb = total_std - total_emb
    if missing_emb > 50:
        tag = FAIL; failures += 1
    elif missing_emb > 0:
        tag = WARN
    else:
        tag = OK
    print(f"  [{tag}] {total_emb:,} / {total_std:,} standards embedded  ({missing_emb} missing)")

    # ── 3. Crosswalk coverage ─────────────────────────────────────────────────
    print("\n── Crosswalk coverage ───────────────────────────────────────────────")
    total_xwalk = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    systems_with_xwalk = conn.execute(
        "SELECT COUNT(DISTINCT s.system) FROM crosswalk_mappings cm "
        "JOIN standards s ON s.id = cm.source_id"
    ).fetchone()[0]
    # Hubs are intentionally excluded — they are crosswalk targets, not sources
    hub_placeholders = ",".join("?" * len(CROSSWALK_HUBS))
    systems_missing_xwalk = conn.execute(
        f"SELECT DISTINCT system FROM standards "
        f"WHERE system NOT IN ({hub_placeholders}) "
        f"AND system NOT IN (SELECT DISTINCT s.system FROM crosswalk_mappings cm JOIN standards s ON s.id = cm.source_id)",
        list(CROSSWALK_HUBS),
    ).fetchall()
    tag = WARN if systems_missing_xwalk else OK
    print(f"  [{tag}] {total_xwalk:,} crosswalk mappings across {systems_with_xwalk} systems")
    for (s,) in systems_missing_xwalk:
        print(f"         no crosswalk: {s}")

    # ── 4. Relationship coverage ──────────────────────────────────────────────
    print("\n── Relationships ────────────────────────────────────────────────────")
    total_rel = conn.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    tag = FAIL if total_rel == 0 else OK
    if total_rel == 0:
        failures += 1
    print(f"  [{tag}] {total_rel:,} grade-progression relationships")

    conn.close()

    print(f"\n{'─'*60}")
    if failures:
        print(f"  {FAIL}  {failures} check(s) failed — review output above")
    else:
        print(f"  [{OK}]  All checks passed")
    print()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
