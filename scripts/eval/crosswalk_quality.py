"""Eval 3: Crosswalk quality — confidence score distribution and mapping density."""
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "common_core.db"

HUBS = {"ccss", "ccss-ela", "ngss", "c3", "csta"}

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    failures = 0

    # ── 1. Confidence score distribution ─────────────────────────────────────
    print("\n── Confidence score distribution ────────────────────────────────────")
    total = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    bands = [
        ("≥ 0.90 (strong)",    0.90, 1.01),
        ("0.80–0.90 (good)",   0.80, 0.90),
        ("0.70–0.80 (moderate)", 0.70, 0.80),
        ("< 0.70 (weak)",      0.00, 0.70),
    ]
    for label, lo, hi in bands:
        n = conn.execute(
            "SELECT COUNT(*) FROM crosswalk_mappings WHERE confidence_score>=? AND confidence_score<?",
            (lo, hi),
        ).fetchone()[0]
        pct = 100 * n / total if total else 0
        bar = "█" * int(pct / 2)
        tag = FAIL if label.startswith("< 0.70") and n > 0 else OK
        print(f"  [{tag}] {label:28s} {n:6,} ({pct:5.1f}%) {bar}")
        if label.startswith("< 0.70") and n > 0:
            failures += 1

    # ── 2. Hub-collision analysis (multiple source standards → same hub) ──────
    print("\n── Hub collision analysis (multiple standards → same hub target) ─────")
    collisions = conn.execute("""
        SELECT target_id, source_system, COUNT(*) n
        FROM crosswalk_mappings
        GROUP BY target_id, source_system
        HAVING n > 3
        ORDER BY n DESC
        LIMIT 20
    """).fetchall()

    if collisions:
        print(f"  [{WARN}] {len(collisions)} hub standards with >3 mappings from the same system:")
        for hub_id, src_sys, n in collisions[:10]:
            print(f"         {src_sys:12s} → {hub_id}  ({n} mappings)")
    else:
        print(f"  [{OK}]  No hub standard receives >3 mappings from any single system")

    # ── 3. Systems missing crosswalk coverage ────────────────────────────────
    print("\n── Systems without any crosswalk mappings ───────────────────────────")
    hub_placeholders = ",".join("?" * len(HUBS))
    missing = conn.execute(
        f"""SELECT DISTINCT system FROM standards
            WHERE system NOT IN ({hub_placeholders})
            AND system NOT IN (
                SELECT DISTINCT source_system FROM crosswalk_mappings
            )""",
        list(HUBS),
    ).fetchall()
    if missing:
        for (s,) in missing:
            print(f"  [{WARN}] {s}: no crosswalk mappings")
    else:
        print(f"  [{OK}]  All non-hub systems have crosswalk coverage")

    # ── 4. Subject routing check ─────────────────────────────────────────────
    print("\n── Subject routing (each subject maps to its hub) ───────────────────")
    SUBJECT_HUBS = {
        "mathematics":    "ccss",
        "science":        "ngss",
        "ela":            "ccss-ela",
        "social-studies": "c3",
        "computer-science": "csta",
    }
    for subject, hub in SUBJECT_HUBS.items():
        wrong = conn.execute("""
            SELECT COUNT(*) FROM crosswalk_mappings cm
            JOIN standards s ON s.id = cm.source_id
            WHERE s.subject=? AND cm.target_system != ?
        """, (subject, hub)).fetchone()[0]
        tag = FAIL if wrong > 0 else OK
        if wrong > 0:
            failures += 1
        print(f"  [{tag}] {subject:20s} → {hub:10s}  ({wrong} mis-routed)")

    conn.close()
    print(f"\n  {'FAIL' if failures else 'OK'}  {failures} check(s) failed\n")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
